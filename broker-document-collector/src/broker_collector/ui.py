"""Deutschsprachige Weboberfläche (Docker-Port nur via SSH-Tunnel, keine externen Ressourcen).

- Läuft im Hauptthread; alle Browseraktionen laufen im Worker des ScanManagers → die
  Oberfläche bleibt während eines Scans bedienbar.
- Schutz gegen fremde Webseiten (CSRF/DNS-Rebinding): Zufallstoken je Programmstart für
  alle POST-Anfragen und Prüfung des Host-Headers.
- Keine CDNs, keine Telemetrie, keine externen Schriftarten.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .config import Settings, apply_values, save_settings
from .database import Database
from .maintenance import delete_browser_profile, delete_downloads
from .reporting import write_report
from .scanner import BROKERS, ScanManager
from .security import is_probably_cloud_synced, redact

log = logging.getLogger(__name__)

EDITABLE_SETTINGS = {"output_dir", "ocr_enabled", "tesseract_cmd", "trade_republic_websocket", "network_capture",
                     "max_download_mb", "login_wait_timeout_s", "browser_channel", "recheck_old_areas"}
BROKER_LABELS = {"trade_republic": "Trade Republic", "scalable_capital": "Scalable Capital"}


def open_folder(path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, settings: Settings, db: Database, manager: ScanManager, config_path: Path):
        self.settings = settings
        self.db = db
        self.manager = manager
        self.config_path = config_path
        self.token = secrets.token_urlsafe(32)

    # ------------------------------------------------------------------ #
    def state(self) -> dict[str, Any]:
        snap = self.manager.snapshot()
        runs = self.db.query("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 20")
        counts = self.db.query("SELECT broker, download_status, COUNT(*) AS n FROM documents GROUP BY 1, 2")
        dup = self.db.query("SELECT COUNT(*) AS n FROM document_locations l JOIN documents d ON d.id = l.document_id "
                            "WHERE l.doc_key != d.doc_key")
        warnings = []
        if is_probably_cloud_synced(self.settings.output_dir):
            warnings.append("Der Ausgabeordner liegt vermutlich in einem Cloud-Sync-Ordner (z. B. OneDrive). "
                            "Dokumente würden dadurch in die Cloud übertragen. Bitte einen lokalen Ordner wählen.")
        return {
            "version": __version__, "manager": snap, "runs": runs, "counts": counts,
            "alternative_locations": dup[0]["n"] if dup else 0,
            "settings": {k: v for k, v in self.settings.to_public_dict().items() if k in EDITABLE_SETTINGS},
            "warnings": warnings, "brokers": BROKER_LABELS,
        }

    def documents(self, params: dict[str, str]) -> list[dict[str, Any]]:
        broker = params.get("broker") or None
        status = params.get("status") or None
        if status == "duplicate":
            return self.db.query(
                "SELECT l.title AS original_name, l.broker, l.doc_date, l.found_at AS downloaded_at, d.local_path, "
                "'duplicate' AS download_status, d.doc_type, d.sha256 FROM document_locations l JOIN documents d ON "
                "d.id = l.document_id WHERE l.doc_key != d.doc_key" + (" AND l.broker = ?" if broker else "") +
                " ORDER BY l.id DESC LIMIT 1000", (broker,) if broker else ())
        if status == "errors":
            rows = self.db.query("SELECT * FROM documents WHERE download_status IN ('failed','invalid',"
                                 "'not_downloadable')" + (" AND broker = ?" if broker else "") +
                                 " ORDER BY id DESC LIMIT 1000", (broker,) if broker else ())
            return rows
        return self.db.documents(broker=broker, status=status, limit=1000)

    def run_details(self, run_id: int) -> dict[str, Any]:
        return {
            "run": self.db.get_run(run_id),
            "areas": self.db.areas_for_run(run_id),
            "problems": self.db.query("SELECT * FROM run_results WHERE run_id = ? AND status IN "
                                      "('failed','invalid','not_downloadable') ORDER BY id", (run_id,)),
        }

    # ------------------------------------------------------------------ #
    def handle_post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        m = self.manager
        broker = body.get("broker")
        if path == "/api/login":
            if broker not in BROKERS:
                return 400, {"error": "Unbekannter Broker"}
            return self._accepted(m.login(broker))
        if path == "/api/check":
            if broker not in BROKERS:
                return 400, {"error": "Unbekannter Broker"}
            return self._accepted(m.check(broker))
        if path == "/api/scan":
            brokers = body.get("brokers") or list(BROKERS)
            return self._accepted(m.scan(brokers, body.get("mode", "sync")))
        if path == "/api/rerun":
            return self._accepted(m.rerun_last())
        if path == "/api/pause":
            m.pause()
            return 200, {"ok": True}
        if path == "/api/resume":
            m.resume()
            return 200, {"ok": True}
        if path == "/api/cancel":
            m.cancel()
            return 200, {"ok": True}
        if path == "/api/close_browsers":
            return self._accepted(m.close_browsers())
        if path == "/api/open_folder":
            target = {"reports": self.settings.reports_dir, "logs": self.settings.logs_dir}.get(
                body.get("which", ""), self.settings.output_dir)
            open_folder(target)
            return 200, {"ok": True}
        if path == "/api/export_report":
            run_id = body.get("run_id") or (self.db.last_run() or {}).get("id")
            if not run_id:
                return 400, {"error": "Noch kein Scanlauf vorhanden"}
            paths = write_report(self.db, int(run_id), self.settings.reports_dir)
            return 200, {"ok": True, "paths": paths}
        if path == "/api/settings":
            values = {k: v for k, v in (body.get("settings") or {}).items() if k in EDITABLE_SETTINGS}
            if m.busy:
                return 409, {"error": "Einstellungen können während eines Scans nicht geändert werden"}
            apply_values(self.settings, values)
            self.settings.ensure_dirs()
            save_settings(self.settings, self.config_path)
            return 200, {"ok": True, "note": "Gespeichert. Änderungen am Ausgabeordner wirken nach Neustart."}
        if path == "/api/delete":
            if m.busy:
                return 409, {"error": "Bitte zuerst den laufenden Vorgang beenden"}
            if body.get("confirm") != "LÖSCHEN":
                return 400, {"error": "Bitte zur Bestätigung LÖSCHEN eingeben"}
            what = body.get("what")
            b = broker if broker in BROKERS else None
            if what == "profile":
                m.close_browsers()
                m._queue.join()
                return 200, {"ok": True, "removed": delete_browser_profile(self.settings, b)}
            if what == "downloads":
                return 200, {"ok": True, "removed": delete_downloads(self.settings, b)}
            if what == "database":
                return 200, {"ok": False, "error": "Die Datenbank kann nur bei beendetem Programm gelöscht werden: "
                                                   "start.bat --delete-database"}
            return 400, {"error": "Unbekannte Löschaktion"}
        if path == "/api/scheduler":
            from .scheduler import SchedulerError, create_task, delete_task

            start_bat = Path(__file__).resolve().parents[2] / "start.bat"
            try:
                out = create_task(start_bat, body.get("time", "07:30")) if body.get("action") == "create" \
                    else delete_task()
            except SchedulerError as exc:
                return 400, {"error": str(exc)}
            return 200, {"ok": True, "output": out}
        return 404, {"error": "Unbekannte Aktion"}

    @staticmethod
    def _accepted(ok: bool) -> tuple[int, dict[str, Any]]:
        if ok:
            return 202, {"ok": True}
        return 409, {"error": "Es läuft bereits ein Vorgang. Bitte warten, pausieren oder abbrechen."}


def make_handler(app: App, port: int) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "BDC"

        def log_message(self, fmt: str, *args: Any) -> None:  # keine Zugriffslogs mit Query-Parametern
            log.debug("UI %s", redact(fmt % args))

        def _send(self, code: int, payload: Any, ctype: str = "application/json; charset=utf-8") -> None:
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False,
                                                                         default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
                             " connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._send(403, {"error": "Host nicht erlaubt"})
            url = urlsplit(self.path)
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/":
                    return self._send(200, PAGE.replace("__TOKEN__", app.token).encode("utf-8"),
                                      "text/html; charset=utf-8")
                if url.path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                if url.path == "/api/state":
                    return self._send(200, app.state())
                if url.path == "/api/documents":
                    return self._send(200, app.documents(params))
                if url.path == "/api/run":
                    return self._send(200, app.run_details(int(params.get("id", "0"))))
            except Exception as exc:  # noqa: BLE001
                log.exception("UI-Fehler")
                return self._send(500, {"error": redact(exc)})
            return self._send(404, {"error": "Nicht gefunden"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._send(403, {"error": "Host nicht erlaubt"})
            if not secrets.compare_digest(self.headers.get("X-BDC-Token", ""), app.token):
                return self._send(403, {"error": "Ungültiges Token"})
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                code, payload = app.handle_post(urlsplit(self.path).path, body if isinstance(body, dict) else {})
            except Exception as exc:  # noqa: BLE001
                log.exception("UI-Fehler")
                code, payload = 500, {"error": redact(exc)}
            return self._send(code, payload)

    return Handler


def serve(settings: Settings, db: Database, manager: ScanManager, config_path: Path,
          open_browser: bool = True) -> None:
    app = App(settings, db, manager, config_path)
    port = settings.ui_port
    server = None
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer((settings.ui_host, candidate), make_handler(app, candidate))
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("Kein freier lokaler Port für die Oberfläche gefunden")
    url = f"http://127.0.0.1:{port}/"
    print(f"\nBroker Document Collector läuft: {url}\nZum Beenden dieses Fenster schließen oder Strg+C drücken.\n")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.shutdown()


PAGE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Broker Document Collector</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--fg:#1d2330;--muted:#677084;--acc:#1f6feb;--ok:#1a7f37;--warn:#b26a00;--err:#c62828;--bd:#dde1e7}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--fg:#e6e8ec;--muted:#9aa3b2;--bd:#2d333d}}
*{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:14px 20px;background:var(--card);border-bottom:1px solid var(--bd);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0;flex:1}main{padding:16px 20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}.card h2{font-size:15px;margin:0 0 10px}
.wide{grid-column:1/-1}button{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:7px 12px;margin:2px;cursor:pointer;font-size:13px}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc)}button.dan{background:var(--err)}button:disabled{opacity:.45;cursor:not-allowed}
.muted{color:var(--muted);font-size:12px}.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;background:var(--bg);border:1px solid var(--bd)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.err{color:var(--err)}table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{text-align:left;padding:5px 6px;border-bottom:1px solid var(--bd);vertical-align:top}th{color:var(--muted);font-weight:600}
.bar{height:8px;background:var(--bg);border-radius:4px;overflow:hidden;border:1px solid var(--bd)}.bar>div{height:100%;background:var(--acc);width:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-size:13px}.banner{background:#fff4d6;color:#5a3d00;border-left:4px solid #e0a800;padding:8px 12px;border-radius:6px;margin:0 20px}
select,input[type=text],input[type=number]{padding:5px;border:1px solid var(--bd);border-radius:5px;background:var(--card);color:var(--fg)}
.tabs button{background:transparent;color:var(--fg);border:1px solid var(--bd)}.tabs button.active{background:var(--acc);color:#fff}
.scroll{max-height:380px;overflow:auto}label{font-size:13px}
</style></head><body>
<header><h1>Broker Document Collector</h1><span class="muted" id="ver"></span>
<button class="sec" onclick="post('/api/open_folder',{})">Ausgabeordner öffnen</button>
<button class="sec" onclick="post('/api/open_folder',{which:'reports'})">Berichte</button></header>
<div id="warnings"></div>
<main>
<section class="card"><h2>1. Anmeldung</h2>
<p class="muted">Sie melden sich selbst im geöffneten Browserfenster an (inkl. 2FA/Passkey). Das Programm fragt nie nach Passwörtern.</p>
<table id="login"></table></section>

<section class="card"><h2>2. Scan</h2>
<div><label><input type="checkbox" id="b_tr" checked> Trade Republic</label>
<label><input type="checkbox" id="b_sc" checked> Scalable Capital</label></div>
<div style="margin:8px 0"><label>Modus: <select id="mode">
<option value="sync">Synchronisieren (nur neue/fehlgeschlagene)</option>
<option value="full">Gesamtscan (alles erneut prüfen)</option>
<option value="resume">Unterbrochenen Scan fortsetzen</option></select></label></div>
<button onclick="startScan()" id="btnScan">Automatischen Scan starten</button>
<button class="sec" onclick="post('/api/rerun',{})">Letzten Scan erneut</button><br>
<button class="sec" onclick="post('/api/pause',{})">Pausieren</button>
<button class="sec" onclick="post('/api/resume',{})">Fortsetzen</button>
<button class="dan" onclick="post('/api/cancel',{})">Abbrechen</button>
<div style="margin-top:10px" id="progress"></div></section>

<section class="card"><h2>Status &amp; Meldungen</h2><div class="scroll" id="messages" style="max-height:220px"></div></section>

<section class="card wide"><h2>Dokumente</h2>
<div class="tabs" id="tabs">
<button data-s="downloaded" class="active">Heruntergeladen</button><button data-s="duplicate">Duplikate</button>
<button data-s="errors">Fehler / nicht herunterladbar</button><button data-s="">Alle</button>
<select id="fbroker" onchange="loadDocs()"><option value="">Alle Broker</option><option value="trade_republic">Trade Republic</option><option value="scalable_capital">Scalable Capital</option></select></div>
<div class="scroll"><table id="docs"></table></div></section>

<section class="card wide"><h2>Scanläufe &amp; Bereiche</h2><div class="scroll"><table id="runs"></table></div><div id="rundetail"></div></section>

<section class="card"><h2>Einstellungen</h2><div id="settings" class="grid2"></div>
<button onclick="saveSettings()">Speichern</button></section>

<section class="card"><h2>Daten löschen &amp; Zeitplan</h2>
<p class="muted">Browserprofil = Zugangsschlüssel (enthält Sitzungscookies). Löschen erzwingt eine Neuanmeldung.</p>
<select id="delwhat"><option value="profile">Browserprofil</option><option value="downloads">Heruntergeladene Dateien</option><option value="database">Datenbank</option></select>
<select id="delbroker"><option value="">beide Broker</option><option value="trade_republic">Trade Republic</option><option value="scalable_capital">Scalable Capital</option></select>
<button class="dan" onclick="doDelete()">Löschen …</button>
<hr style="border:0;border-top:1px solid var(--bd)">
<label>Täglicher Sync um <input type="text" id="schedtime" value="07:30" size="5"></label>
<button class="sec" onclick="post('/api/scheduler',{action:'create',time:document.getElementById('schedtime').value})">Aufgabe anlegen</button>
<button class="sec" onclick="post('/api/scheduler',{action:'delete'})">Aufgabe entfernen</button>
<p class="muted">Der Zeitplan umgeht keine abgelaufene Sitzung – ggf. wartet der Sync auf Ihre Anmeldung.</p></section>
</main>
<script>
const TOKEN="__TOKEN__";let docStatus="downloaded";let state=null;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const BN={trade_republic:"Trade Republic",scalable_capital:"Scalable Capital"};
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json","X-BDC-Token":TOKEN},body:JSON.stringify(body)});
 const j=await r.json().catch(()=>({}));if(!r.ok||j.error){alert(j.error||("Fehler "+r.status));}else if(j.paths){alert("Bericht gespeichert:\n"+j.paths.html);}else if(j.note){alert(j.note);}refresh();return j;}
function startScan(){const b=[];if(document.getElementById("b_tr").checked)b.push("trade_republic");if(document.getElementById("b_sc").checked)b.push("scalable_capital");
 if(!b.length){alert("Bitte mindestens einen Broker wählen");return;}post("/api/scan",{brokers:b,mode:document.getElementById("mode").value});}
function doDelete(){const what=document.getElementById("delwhat").value;const c=prompt("Zum Bestätigen LÖSCHEN eingeben:");if(c===null)return;
 post("/api/delete",{what,broker:document.getElementById("delbroker").value,confirm:c});}
function render(){const m=state.manager;document.getElementById("ver").textContent="v"+state.version;
 document.getElementById("warnings").innerHTML=state.warnings.map(w=>`<p class="banner">${esc(w)}</p>`).join("");
 document.getElementById("login").innerHTML=Object.keys(BN).map(b=>`<tr><td><b>${BN[b]}</b><br><span class="muted">${esc(m.login[b])}</span></td>
  <td style="text-align:right"><button onclick="post('/api/login',{broker:'${b}'})" ${m.busy?"disabled":""}>Anmeldung starten</button>
  <button class="sec" onclick="post('/api/check',{broker:'${b}'})" ${m.busy?"disabled":""}>Status prüfen</button></td></tr>`).join("")+
  `<tr><td colspan=2><button class="sec" onclick="post('/api/close_browsers',{})" ${m.busy?"disabled":""}>Browserfenster schließen</button></td></tr>`;
 const s=m.status||{};const pct=s.areas_total?Math.round(100*s.areas_done/s.areas_total):0;
 const st={running:"läuft",paused:"pausiert",waiting_user:"wartet auf Ihre Aktion im Browser",finished:"beendet",failed:"fehlgeschlagen",cancelled:"abgebrochen"}[m.paused?"paused":s.state]||"bereit";
 document.getElementById("progress").innerHTML=`<div class="bar"><div style="width:${pct}%"></div></div>
  <div class="grid2" style="margin-top:8px"><span>Status: <b class="${s.state==='waiting_user'?'warn':''}">${esc(st)}</b></span><span>${esc(BN[s.broker]||"")}</span>
  <span>Bereich: ${esc(s.current_area||"-")}</span><span>Bereiche: ${s.areas_done||0}/${s.areas_total||0}</span>
  <span>Gefunden: ${s.documents_found||0}</span><span class="ok">Heruntergeladen: ${s.downloaded||0}</span>
  <span>Duplikate: ${s.duplicates||0}</span><span class="err">Fehler: ${s.failed||0}</span><span>Bekannt/übersprungen: ${s.skipped_known||0}</span></div>
  <p class="muted">${esc(s.message||"")}</p>`;
 document.getElementById("btnScan").disabled=m.busy;
 document.getElementById("messages").innerHTML=m.messages.map(x=>`<div class="${x.level==='error'?'err':x.level==='warn'?'warn':''}"><span class="muted">${x.time}</span> ${esc(x.text)}</div>`).join("")||'<span class="muted">Keine Meldungen</span>';
 document.getElementById("runs").innerHTML="<tr><th>Lauf</th><th>Broker</th><th>Modus</th><th>Start</th><th>Status</th><th>Gefunden</th><th>Neu</th><th>Duplikate</th><th>Fehler</th><th></th></tr>"+
  state.runs.map(r=>`<tr><td>${r.id}</td><td>${esc(BN[r.broker])}</td><td>${esc(r.mode)}</td><td>${esc(r.started_at)}</td><td>${esc(r.status)}</td>
  <td>${r.documents_found}</td><td>${r.downloaded}</td><td>${r.duplicates}</td><td>${r.failed}</td>
  <td><button class="sec" onclick="showRun(${r.id})">Details</button><button class="sec" onclick="post('/api/export_report',{run_id:${r.id}})">Bericht exportieren</button></td></tr>`).join("");
 if(!document.getElementById("settings").dataset.filled){const se=state.settings;document.getElementById("settings").dataset.filled=1;
  const L={output_dir:"Ausgabeordner",ocr_enabled:"Lokale OCR (Tesseract)",tesseract_cmd:"Pfad zu tesseract.exe",trade_republic_websocket:"TR: WebSocket-Quelle (inoffiziell) für Abgleich",
   network_capture:"Webapp-Datenantworten mitlesen (Abgleich)",max_download_mb:"Max. Dateigröße (MB)",login_wait_timeout_s:"Wartezeit Anmeldung (s)",browser_channel:"Browser (leer=Chromium, msedge, chrome)",recheck_old_areas:"Ältere Einträge erneut prüfen"};
  document.getElementById("settings").innerHTML=Object.keys(L).map(k=>{const v=se[k];const inp=typeof v==="boolean"?`<input type="checkbox" id="set_${k}" ${v?"checked":""}>`:
   `<input type="${typeof v==='number'?'number':'text'}" id="set_${k}" value="${esc(v)}" style="width:100%">`;return `<label for="set_${k}">${L[k]}</label><div>${inp}</div>`}).join("");}}
function saveSettings(){const se={};for(const k of Object.keys(state.settings)){const el=document.getElementById("set_"+k);if(!el)continue;
 se[k]=el.type==="checkbox"?el.checked:el.type==="number"?Number(el.value):el.value;}post("/api/settings",{settings:se});}
async function showRun(id){const d=await (await fetch("/api/run?id="+id)).json();const SD={complete:"vollständig",partial:"teilweise",inaccessible:"nicht zugänglich",pending:"offen"};
 document.getElementById("rundetail").innerHTML=`<h3 style="font-size:14px">Lauf ${id}: Bereiche</h3><table><tr><th>Bereich</th><th>Quelle</th><th>Status</th><th>Seiten</th><th>Zeiträume</th><th>Hinweis</th></tr>`+
  d.areas.map(a=>`<tr><td>${esc(a.name)}</td><td>${esc(a.source)}</td><td class="${a.status==='complete'?'ok':a.status==='partial'?'warn':'err'}">${SD[a.status]||a.status}</td><td>${a.pages_visited}</td><td>${esc((a.periods||[]).join(", "))}</td><td class="muted">${esc(a.note)}</td></tr>`).join("")+
  `</table><h3 style="font-size:14px">Probleme</h3><table><tr><th>Dokument</th><th>Bereich</th><th>Status</th><th>Grund</th></tr>`+
  (d.problems.map(p=>`<tr><td>${esc(p.title)}</td><td>${esc(p.area)}</td><td>${esc(p.status)}</td><td class="muted">${esc(p.error_message)}</td></tr>`).join("")||"<tr><td colspan=4 class='muted'>Keine</td></tr>")+"</table>";}
async function loadDocs(){const b=document.getElementById("fbroker").value;const rows=await (await fetch(`/api/documents?status=${docStatus}&broker=${b}`)).json();
 document.getElementById("docs").innerHTML="<tr><th>Datum</th><th>Broker</th><th>Dokument</th><th>Typ</th><th>Status</th><th>Datei / Fehler</th></tr>"+
  rows.map(r=>`<tr><td>${esc(r.doc_date||"")}</td><td>${esc(BN[r.broker]||r.broker)}</td><td>${esc(r.original_name)}</td><td>${esc(r.doc_type||"")}</td>
  <td>${esc(r.download_status)}</td><td class="muted">${esc(r.error_message||r.local_path||"")}</td></tr>`).join("");}
document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#tabs button").forEach(x=>x.classList.remove("active"));b.classList.add("active");docStatus=b.dataset.s;loadDocs();});
async function refresh(){try{state=await (await fetch("/api/state")).json();render();}catch(e){}}
refresh();loadDocs();setInterval(refresh,1500);setInterval(loadDocs,6000);
</script></body></html>
"""
