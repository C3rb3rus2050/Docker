"""Integrationstests mit echtem (headless) Chromium gegen Mockseiten.

Keine echten Broker, keine Zugangsdaten. Die Mockseiten werden per Playwright-Routing unter
HTTPS-Adressen ausgeliefert, damit die URL-Richtlinien (nur HTTPS, nur erlaubte Hosts) greifen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from broker_collector.browser_manager import BrowserManager
from broker_collector.scanner import Collector
from broker_collector.security import UrlPolicy
from broker_collector.trade_republic import TradeRepublicAdapter
from broker_collector.web_adapter import WebBrokerAdapter
from conftest import make_pdf
from mock_site import PDFS, MockSite

pytestmark = pytest.mark.integration


class MockBrokerAdapter(WebBrokerAdapter):
    broker_id = "scalable_capital"  # Ordnerstruktur eines echten Brokers verwenden
    display_name = "Mock Broker"
    start_url = "https://app.broker.test/"
    app_hosts = ("app.broker.test",)
    url_policy = UrlPolicy(("broker.test",))
    expand_area_pattern = re.compile("transaktion", re.I)


@pytest.fixture
def browser(settings, chromium_executable):
    bm = BrowserManager(settings.profile_dir, headless=True, executable=chromium_executable,
                        download_timeout_s=15, max_bytes=settings.max_download_bytes)
    try:
        bm._ensure_playwright()
        probe_ctx, _ = bm.open("probe")
        bm.close("probe")
    except Exception as exc:  # pragma: no cover - Umgebung ohne Chromium
        bm.close_all()
        pytest.skip(f"Chromium nicht verfügbar: {exc}")
    # In der Testumgebung existieren die Hosts nicht: Downloads über fetch() in der Seite (geroutet)
    bm.fetch = lambda ctx, page, url, policy, referer="": bm.fetch_in_page(page, url, policy)  # type: ignore
    yield bm
    bm.close_all()


def test_full_scan_against_mock_site(settings, db, browser):
    site = MockSite()
    settings.max_pages_per_area = 20
    adapter = MockBrokerAdapter(browser, settings)
    ctx, _ = browser.open(adapter.broker_id)
    ctx.route("https://app.broker.test/**", site.handler)
    run_id = Collector(settings, db).run_broker(adapter, "sync")

    run = db.get_run(run_id)
    # Sicherheitsfallen wurden nie ausgelöst
    assert site.danger == [], site.danger
    assert not any("/logout" in u or "/portfolio" in u for u in site.requests)

    results = {r["title"]: r["status"] for r in db.run_results(run_id)}
    expected_downloaded = [
        "Abrechnung Kauf Apple 12.03.2024", "Kontoauszug 31.01.2024", "Dividende Microsoft 14.03.2024",
        "Zinsabrechnung 29.02.2024",  # erst nach "Mehr laden" sichtbar
        "Kontoauszug 31.12.2023",  # nur über Jahresfilter 2023 erreichbar
        "Jahressteuerbescheinigung 2023",
        "Depotauszug 31.12.2024 PDF herunterladen",  # Blob-Download nach Klick
        "Kosteninformation 2024",  # PDF-Viewer im Dialog
        "Verkauf Tesla",  # nur in den Webapp-Daten (Netzwerk) → zusätzliche Quelle
    ]
    for title in expected_downloaded:
        assert results.get(title) == "downloaded", (title, results)
    assert results["Verlustbescheinigung 2023"] == "invalid"  # HTML statt PDF
    assert results["Abrechnung"] == "duplicate"  # Detailansicht einer Transaktion, gleicher Inhalt
    assert results["Abrechnung Kauf Apple"] == "duplicate"  # Netzwerkquelle, gleicher Inhalt
    assert results["Steuerbescheinigung anfordern"] == "not_downloadable"

    stored = {p.name for p in settings.output_dir.rglob("*.pdf")}
    assert len(stored) == 9
    for path in settings.output_dir.rglob("*.pdf"):
        assert path.read_bytes() in PDFS.values()  # unverändert

    areas = {a["name"]: a for a in db.areas_for_run(run_id)}
    assert areas["Postfach"]["status"] == "complete"
    assert areas["Postfach"]["periods"] == ["2024", "2023"]
    assert "Portfolio" not in areas

    report = json.loads(Path(next(settings.reports_dir.glob("*.json"))).read_text(encoding="utf-8"))
    rec = report["reconciliation"]
    assert set(rec["sources"]) == {"ui", "network"}
    assert any(g["title"] == "Verkauf Tesla" for g in rec["only_in"].get("network", []))
    assert run["status"] == "finished_with_errors"

    # Zweiter Lauf (Sync): nichts Neues, bekannte Dokumente werden nicht erneut geladen
    site.requests.clear()
    run2 = Collector(settings, db).run_broker(MockBrokerAdapter(browser, settings), "sync")
    r2 = db.get_run(run2)
    assert r2["downloaded"] == 0 and r2["skipped_known"] >= 9
    assert site.danger == []


def test_session_detection(settings, browser):
    site = MockSite()
    adapter = MockBrokerAdapter(browser, settings)
    ctx, page = browser.open(adapter.broker_id)
    ctx.route("https://app.broker.test/**", site.handler)
    adapter.connect()
    page.goto("https://app.broker.test/")
    assert adapter.check_session() is True
    page.set_content("<html><body><form><input type='password'></form></body></html>")
    assert adapter.check_session() is False
    page.set_content("<html><body><iframe src='https://www.google.com/recaptcha/api2/anchor'></iframe></body></html>")
    from broker_collector.broker_adapter import UserActionRequired

    with pytest.raises(UserActionRequired) as exc:
        adapter.check_session()
    assert exc.value.reason == "captcha"


# --------------------------------------------------------------------------- #
# Trade Republic: WebSocket-Quelle im Browser (gemockter Server)
# --------------------------------------------------------------------------- #

TR_HOME = """<!doctype html><html><body><nav><a href="/portfolio">Portfolio</a> <a href="/markt">Markt</a>
<a href="/suche">Suche</a> <a href="/logout">Abmelden</a></nav><main>Willkommen</main></body></html>"""
S3 = "https://traderepublic-docs.s3.eu-central-1.amazonaws.com"
TR_PDFS = {"a.pdf": make_pdf("Wertpapierabrechnung Kauf Apple"), "b.pdf": make_pdf("Kontoauszug 2024")}


class MockTRSocket:
    def __init__(self):
        self.received: list[str] = []

    def __call__(self, ws):
        def on_message(message):
            self.received.append(message)
            if message.startswith("connect "):
                ws.send("connected")
                return
            if message.startswith("unsub "):
                return
            _, sid, payload = message.split(" ", 2)
            data = json.loads(payload)
            if data["type"] == "timelineTransactions":
                body = {"items": [{"id": "t1", "timestamp": "2024-03-12T09:00:00.000+0000", "title": "Apple"}],
                        "cursors": {}}
            elif data["type"] == "timelineActivityLog":
                if data.get("after") == "p2":
                    body = {"items": [{"id": "a2", "timestamp": "2024-01-31T09:00:00.000+0000"}], "cursors": {}}
                else:
                    body = {"items": [{"id": "a1", "timestamp": "2024-02-01T09:00:00.000+0000"}],
                            "cursors": {"after": "p2"}}
            elif data["type"] == "timelineDetailV2":
                docs = {"t1": [("Abrechnung", f"{S3}/a.pdf?X-Amz-Signature=SECRET")],
                        "a1": [], "a2": [("Kontoauszug", f"{S3}/b.pdf?X-Amz-Signature=SECRET2")]}[data["id"]]
                body = {"sections": [{"type": "documents", "data": [
                    {"id": f"d-{data['id']}-{i}", "title": t, "action": {"type": "browserModal", "payload": u}}
                    for i, (t, u) in enumerate(docs)]}]}
            else:
                ws.send(f'{sid} E {{"error":"forbidden"}}')
                return
            ws.send(f"{sid} A {json.dumps(body)}")

        ws.on_message(on_message)


def test_trade_republic_websocket_source(settings, db, browser):
    settings.network_capture = False
    socket = MockTRSocket()
    ui_requests: list[str] = []

    def app_handler(route, request):
        ui_requests.append(request.url)
        if request.url.rstrip("/").endswith("app.traderepublic.com"):
            return route.fulfill(status=200, body=TR_HOME, content_type="text/html")
        return route.fulfill(status=404, body="")

    def s3_handler(route, request):
        name = request.url.split("?")[0].rsplit("/", 1)[-1]
        return route.fulfill(status=200, body=TR_PDFS[name], content_type="application/pdf",
                             headers={"Access-Control-Allow-Origin": "*"})

    adapter = TradeRepublicAdapter(browser, settings)
    ctx, _ = browser.open(adapter.broker_id)
    ctx.route("https://app.traderepublic.com/**", app_handler)
    ctx.route(f"{S3}/**", s3_handler)
    ctx.route_web_socket("wss://api.traderepublic.com/**", socket)
    ctx.route_web_socket("wss://api.traderepublic.com", socket)

    run_id = Collector(settings, db).run_broker(adapter, "sync")
    results = {r["title"]: (r["status"], r["source"]) for r in db.run_results(run_id)}
    assert results == {"Abrechnung": ("downloaded", "api"), "Kontoauszug": ("downloaded", "api")}, results
    # Nur lesende Abos wurden gesendet, jedes wieder beendet
    subs = [m for m in socket.received if m.startswith("sub ")]
    assert all(json.loads(m.split(" ", 2)[2])["type"] in
               ("timelineTransactions", "timelineActivityLog", "timelineDetailV2") for m in subs)
    assert len(subs) == len([m for m in socket.received if m.startswith("unsub ")])
    assert not any("/logout" in u for u in ui_requests)
    # Signaturen der vorab signierten Links landen nicht in der Datenbank
    db.close()
    raw = settings.database_path.read_bytes()
    wal = Path(str(settings.database_path) + "-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    assert b"SECRET" not in raw

    # Inkrementeller Lauf: bekannte Timeline-Ereignisse werden nicht erneut abgefragt
    from broker_collector.database import Database

    db2 = Database(settings.database_path)
    socket.received.clear()
    adapter2 = TradeRepublicAdapter(browser, settings)
    run2 = Collector(settings, db2).run_broker(adapter2, "sync")
    details = [m for m in socket.received if "timelineDetailV2" in m]
    assert details == []
    assert db2.get_run(run2)["status"] == "finished"
    db2.close()
