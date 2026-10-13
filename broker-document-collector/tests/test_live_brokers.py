"""ECHTE Broker-Livetests – nur manuell ausführen!

Voraussetzungen:
- Windows 11 (oder Desktop mit Anzeige), installierte Abhängigkeiten
- Umgebungsvariable ``BDC_LIVE=1``
- Sie melden sich im geöffneten Browserfenster selbst an (inkl. 2FA). Das Tool fragt keine
  Zugangsdaten ab. Es werden nur lesende Aktionen ausgeführt.

Aufruf:  set BDC_LIVE=1  &&  .venv\\Scripts\\python -m pytest -m live -s tests\\test_live_brokers.py

Ergebnis wird in ein separates Ausgabeverzeichnis geschrieben (BDC_OUTPUT_DIR oder tmp).
"""

import os

import pytest

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("BDC_LIVE") != "1",
                                                   reason="Livetest – nur manuell mit BDC_LIVE=1")]


@pytest.mark.parametrize("broker", ["trade_republic", "scalable_capital"])
def test_live_scan(broker, settings, db):
    from broker_collector.broker_adapter import ScanControl
    from broker_collector.browser_manager import BrowserManager
    from broker_collector.scanner import Collector, make_adapter

    settings.login_wait_timeout_s = 600
    browser = BrowserManager(settings.profile_dir, headless=False)
    control = ScanControl()
    try:
        run_id = Collector(settings, db, control).run_broker(make_adapter(broker, browser, settings, control), "sync")
    finally:
        browser.close_all()
    run = db.get_run(run_id)
    print("Lauf:", dict(run))
    print("Bereiche:", [(a["name"], a["status"]) for a in db.areas_for_run(run_id)])
    assert run["status"] in ("finished", "finished_with_errors")
    assert run["documents_found"] > 0, "Keine Dokumente gefunden – Selektoren/Heuristiken prüfen"
