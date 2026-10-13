"""Vollständigkeits- und Scanberichte (JSON, Markdown, HTML) pro Broker und Lauf.

Der Bericht behauptet NIE, dass alle Dokumente heruntergeladen wurden. Er unterscheidet:
vollständig / teilweise / nicht zugänglich untersuchte Bereiche sowie erfolgreich
heruntergeladene / gefundene, aber nicht herunterladbare Dokumente.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .database import Database
from .reconciliation import SOURCE_NAMES, reconcile
from .security import redact

BROKER_NAMES = {"trade_republic": "Trade Republic", "scalable_capital": "Scalable Capital"}
AREA_STATUS_DE = {
    "complete": "vollständig untersucht",
    "partial": "teilweise untersucht",
    "inaccessible": "nicht zugänglich",
    "pending": "nicht untersucht",
}
ITEM_STATUS_DE = {
    "downloaded": "heruntergeladen",
    "duplicate": "Duplikat (Inhalt bereits vorhanden)",
    "failed": "Download fehlgeschlagen",
    "invalid": "ungültige Datei",
    "not_downloadable": "gefunden, aber nicht herunterladbar",
    "skipped_known": "bereits bekannt (übersprungen)",
    "found": "gefunden (noch nicht verarbeitet)",
}


def build_report(db: Database, run_id: int, extra_notes: list[str] | None = None) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise ValueError(f"Scanlauf {run_id} nicht gefunden")
    broker = run["broker"]
    areas = db.areas_for_run(run_id)
    results = db.run_results(run_id)
    counts = Counter(r["status"] for r in results)
    rec = reconcile(db.source_records(run_id)).to_dict()

    by_status: dict[str, list[dict[str, Any]]] = {}
    for a in areas:
        by_status.setdefault(a["status"], []).append(
            {"name": a["name"], "source": a["source"], "pages_visited": a["pages_visited"],
             "periods": a["periods"], "note": a["note"] or ""}
        )
    periods = sorted({p for a in areas for p in a["periods"]})

    failed = [
        {"title": r["title"], "area": r["area"], "source": r["source"], "status": r["status"],
         "error": redact(r["error_message"] or "")}
        for r in results if r["status"] in ("failed", "invalid")
    ]
    manual = [
        {"title": r["title"], "area": r["area"], "source": r["source"], "reason": redact(r["error_message"] or "")}
        for r in results if r["status"] == "not_downloadable"
    ]

    # Hinweise auf mögliche Lücken
    hints: list[str] = []
    if by_status.get("partial"):
        hints.append(f"{len(by_status['partial'])} Bereich(e) nur teilweise untersucht – dort können ältere "
                     "Dokumente fehlen.")
    if by_status.get("inaccessible"):
        hints.append(f"{len(by_status['inaccessible'])} Bereich(e) waren nicht zugänglich.")
    if failed:
        hints.append(f"{len(failed)} Dokument(e) konnten nicht heruntergeladen werden (siehe Fehlerliste).")
    if manual:
        hints.append(f"{len(manual)} Dokument(e) erfordern eine manuelle Anforderung oder Freigabe.")
    years = sorted({(d["doc_date"] or "")[:4] for d in db.documents(broker=broker, status="downloaded", limit=100000)
                    if d.get("doc_date")})
    if len(years) >= 2:
        missing = [str(y) for y in range(int(years[0]), int(years[-1]) + 1) if str(y) not in years]
        if missing:
            hints.append("Für folgende Jahre liegen keine Dokumente mit Datum vor (möglicherweise fehlend oder "
                         f"keine Aktivität): {', '.join(missing)}.")
    for key, items in rec.get("only_in", {}).items():
        if items:
            label = (f"fehlen in Quelle '{SOURCE_NAMES.get(key[9:], key[9:])}'" if key.startswith("fehlt_in_")
                     else f"nur in Quelle '{SOURCE_NAMES.get(key, key)}' gefunden")
            hints.append(f"Quellenabgleich: {len(items)} Dokument(e) {label}.")
    if run["status"] not in ("finished", "finished_with_errors"):
        hints.append(f"Der Lauf wurde nicht regulär beendet (Status: {run['status']}). Bitte fortsetzen.")
    if broker == "scalable_capital":
        hints.append("Dokumente früherer Kontomodelle/Bankpartner sind nur enthalten, wenn das aktuelle "
                     "Kundenkonto sie anzeigt.")
    hints.extend(extra_notes or [])

    all_complete = bool(areas) and not by_status.get("partial") and not by_status.get("inaccessible") \
        and not by_status.get("pending")
    if all_complete and not failed and not manual and len(rec["sources"]) >= 2 and not rec.get("only_in"):
        verdict = ("Alle erkannten Bereiche wurden vollständig untersucht und die Quellen stimmen überein. "
                   "Ob der Broker weitere, nicht angezeigte Dokumente führt, kann nicht verifiziert werden.")
    elif all_complete and not failed:
        verdict = ("Alle erkannten Bereiche wurden vollständig untersucht. Eine Garantie, dass sämtliche "
                   "Dokumente des Kontos erfasst wurden, ist nicht möglich.")
    else:
        verdict = ("Der Scan ist NICHT als vollständig verifiziert. Bitte die Hinweise, teilweise untersuchten "
                   "Bereiche und Fehler prüfen.")

    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "broker": broker,
        "broker_name": BROKER_NAMES.get(broker, broker),
        "run": {k: run[k] for k in ("id", "mode", "started_at", "finished_at", "status", "message")},
        "summary": {
            "documents_found": len(results),
            "downloaded": counts.get("downloaded", 0),
            "duplicates": counts.get("duplicate", 0),
            "failed": counts.get("failed", 0) + counts.get("invalid", 0),
            "not_downloadable": counts.get("not_downloadable", 0),
            "skipped_known": counts.get("skipped_known", 0),
            "pages_visited": sum(a["pages_visited"] or 0 for a in areas),
            "areas_total": len(areas),
        },
        "areas": by_status,
        "periods": periods,
        "failed": failed,
        "manual_required": manual,
        "reconciliation": rec,
        "hints": hints,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- #
# Ausgabeformate
# --------------------------------------------------------------------------- #


def to_markdown(rep: dict[str, Any]) -> str:
    s = rep["summary"]
    lines = [
        f"# Prüfbericht {rep['broker_name']} – Lauf {rep['run']['id']}",
        "",
        f"Erstellt: {rep['generated_at']}  ",
        f"Modus: {rep['run']['mode']} · Status: {rep['run']['status']} · Start: {rep['run']['started_at']} · "
        f"Ende: {rep['run']['finished_at'] or '-'}",
        "",
        f"> **Bewertung:** {rep['verdict']}",
        "",
        "## Zusammenfassung",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Untersuchte Bereiche | {s['areas_total']} |",
        f"| Besuchte Seiten / Nachladeschritte | {s['pages_visited']} |",
        f"| Gefundene Dokumente | {s['documents_found']} |",
        f"| Heruntergeladen | {s['downloaded']} |",
        f"| Duplikate | {s['duplicates']} |",
        f"| Bereits bekannt (übersprungen) | {s['skipped_known']} |",
        f"| Fehlgeschlagen | {s['failed']} |",
        f"| Gefunden, nicht herunterladbar | {s['not_downloadable']} |",
        "",
        "## Dokumentenbereiche",
        "",
    ]
    for status in ("complete", "partial", "inaccessible", "pending"):
        items = rep["areas"].get(status) or []
        if not items:
            continue
        lines.append(f"### {AREA_STATUS_DE[status].capitalize()} ({len(items)})")
        lines.append("")
        for a in items:
            per = f" · Zeiträume: {', '.join(a['periods'])}" if a["periods"] else ""
            note = f" – {a['note']}" if a["note"] else ""
            lines.append(f"- **{a['name']}** ({SOURCE_NAMES.get(a['source'], a['source'])}, "
                         f"{a['pages_visited']} Seiten{per}){note}")
        lines.append("")
    lines += ["## Erkannte historische Zeiträume", "",
              ", ".join(rep["periods"]) if rep["periods"] else "Keine Zeitraumfilter erkannt.", ""]
    rec = rep["reconciliation"]
    lines += ["## Quellenabgleich", "", rec["note"], ""]
    if rec["per_source"]:
        lines += ["| Quelle | Einträge |", "|---|---|"]
        lines += [f"| {SOURCE_NAMES.get(k, k)} | {v} |" for k, v in rec["per_source"].items()]
        lines += ["", f"Eindeutige Dokumente: {rec['unique_documents']} · in allen Quellen: {rec['in_all_sources']}",
                  ""]
    for key, items in rec.get("only_in", {}).items():
        lines.append(f"**{key}** ({len(items)}):")
        lines += [f"- {g['title']} ({g['date'] or 'ohne Datum'})" for g in items[:200]]
        lines.append("")
    if rep["failed"]:
        lines += ["## Fehlgeschlagene Downloads", ""]
        lines += [f"- {f['title']} [{f['area']}] – {f['error']}" for f in rep["failed"]]
        lines.append("")
    if rep["manual_required"]:
        lines += ["## Manuelle Freigabe/Anforderung erforderlich", ""]
        lines += [f"- {m['title']} [{m['area']}] – {m['reason']}" for m in rep["manual_required"]]
        lines.append("")
    lines += ["## Hinweise auf möglicherweise fehlende Dokumente", ""]
    lines += [f"- {h}" for h in rep["hints"]] or ["- Keine"]
    lines.append("")
    return "\n".join(lines)


def to_html(rep: dict[str, Any]) -> str:
    md = to_markdown(rep)
    body = []
    in_table = False
    for line in md.splitlines():
        esc = html.escape(line)
        if line.startswith("|"):
            if set(line.replace("|", "").strip()) <= {"-"}:
                continue
            cells = [html.escape(c.strip()) for c in line.strip("|").split("|")]
            if not in_table:
                body.append("<table>")
                in_table = True
            body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("> "):
            body.append(f"<p class='verdict'>{html.escape(line[2:]).replace('**', '')}</p>")
        elif line.startswith("- "):
            body.append(f"<li>{esc[2:].replace('**', '')}</li>")
        elif line.strip():
            body.append(f"<p>{esc.replace('**', '')}</p>")
    if in_table:
        body.append("</table>")
    style = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:2em auto;padding:0 1em;color:#222}"
             "table{border-collapse:collapse}td{border:1px solid #ccc;padding:4px 8px}"
             ".verdict{background:#fff4d6;border-left:4px solid #e0a800;padding:.6em}")
    return (f"<!doctype html><html lang='de'><head><meta charset='utf-8'><title>Prüfbericht</title>"
            f"<style>{style}</style></head><body>{''.join(body)}</body></html>")


def write_report(db: Database, run_id: int, reports_dir: Path, extra_notes: list[str] | None = None) -> dict[str, str]:
    rep = build_report(db, run_id, extra_notes)
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = reports_dir / f"bericht_{rep['broker']}_lauf{run_id}_{stamp}"
    paths = {
        "json": str(base.with_suffix(".json")),
        "markdown": str(base.with_suffix(".md")),
        "html": str(base.with_suffix(".html")),
    }
    Path(paths["json"]).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(paths["markdown"]).write_text(to_markdown(rep), encoding="utf-8")
    Path(paths["html"]).write_text(to_html(rep), encoding="utf-8")
    return paths
