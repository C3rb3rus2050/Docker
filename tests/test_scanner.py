"""Scanner-Tests mit Fake-Adapter (keine Browser, keine Broker)."""

from __future__ import annotations

import threading

import pytest

from broker_collector.broker_adapter import (
    BrokerAdapter,
    DocumentArea,
    DocumentRef,
    DownloadedFile,
    DownloadError,
    ScanControl,
    ScanStatus,
    UserActionRequired,
)
from broker_collector.scanner import Collector, ScanManager
from conftest import make_pdf


class FakeAdapter(BrokerAdapter):
    broker_id = "trade_republic"
    display_name = "Fake TR"

    def __init__(self, areas_docs, failures=None, user_action_on=None, cancel_on=None, control=None,
                 logged_in=True):
        self.areas_docs = areas_docs  # {area_name: [(title, bytes|None, source)]}
        self.failures = failures or {}  # title -> list of exceptions to raise in order
        self.user_action_on = user_action_on
        self.cancel_on = cancel_on
        self.control = control
        self.logged_in = logged_in
        self.download_calls: list[str] = []
        self.discover_calls: list[str] = []
        self.login_waits = 0
        self.closed = False

    def connect(self):
        pass

    def check_session(self):
        return self.logged_in

    def wait_for_login(self, timeout_s, on_wait=None):
        self.login_waits += 1
        if on_wait:
            on_wait("Bitte anmelden")
        self.logged_in = True
        return True

    def discover_document_areas(self):
        return [DocumentArea(self.broker_id, name, url=f"https://app.traderepublic.com/{i}")
                for i, name in enumerate(self.areas_docs)]

    def discover_documents(self, area):
        self.discover_calls.append(area.name)
        for title, data, source in self.areas_docs[area.name]:
            if self.user_action_on == title:
                self.user_action_on = None
                raise UserActionRequired("2fa", "Bitte in der App bestätigen")
            if self.cancel_on == title and self.control:
                self.control.cancel()
            yield DocumentRef(self.broker_id, title, source=source, area=area.name,
                              url=f"https://app.traderepublic.com/docs/{title}.pdf" if data is not None else "",
                              downloadable=data is not None,
                              not_downloadable_reason="" if data is not None else "Nur manuell anforderbar")
        area.status = "complete"
        area.pages_visited = 1

    def download_document(self, ref):
        self.download_calls.append(ref.title)
        errs = self.failures.get(ref.title)
        if errs:
            raise errs.pop(0)
        data = next(d for t, d, _ in self.areas_docs[ref.area] if t == ref.title)
        return DownloadedFile(data, f"{ref.title}.pdf", ref.url)

    def paginate_history(self, area):
        return iter(())

    def get_scan_status(self):
        return ScanStatus(self.broker_id)

    def close(self):
        self.closed = True


def docs():
    return {
        "Postfach": [("Abrechnung Kauf 2024-03-12", make_pdf("Kauf"), "ui"),
                     ("Kontoauszug 2024-01-31", make_pdf("Konto"), "ui")],
        "Steuern": [("Jahressteuerbescheinigung 2023", make_pdf("Steuer 2023"), "ui"),
                    ("Steuerbescheinigung anfordern", None, "ui")],
        "API": [("Wertpapierabrechnung", make_pdf("Kauf"), "api")],  # gleicher Inhalt wie oben → Duplikat
    }


def test_full_run(settings, db):
    adapter = FakeAdapter(docs())
    run_id = Collector(settings, db).run_broker(adapter, "full")
    run = db.get_run(run_id)
    assert run["status"] == "finished_with_errors"  # manuell anforderbares Dokument zählt als offen
    assert run["downloaded"] == 3 and run["duplicates"] == 1 and run["failed"] == 1
    assert len(list(settings.output_dir.rglob("*.pdf"))) == 3
    reports = list(settings.reports_dir.glob("*.md"))
    assert reports
    text = reports[0].read_text(encoding="utf-8")
    assert "Quellenabgleich" in text and "Manuelle Freigabe" in text


def test_sync_skips_known_and_retries_failed(settings, db):
    failing = {"Kontoauszug 2024-01-31": [DownloadError("HTTP 403", retryable=False)]}
    a1 = FakeAdapter(docs(), failures=failing)
    run1 = Collector(settings, db).run_broker(a1, "sync")
    assert db.get_run(run1)["failed"] == 2  # 403 + manuell
    a2 = FakeAdapter(docs())
    run2 = Collector(settings, db).run_broker(a2, "sync")
    # Nur das zuvor fehlgeschlagene Dokument wird erneut geladen
    assert a2.download_calls == ["Kontoauszug 2024-01-31"]
    r2 = db.get_run(run2)
    assert r2["downloaded"] == 1 and r2["skipped_known"] == 3


def test_transient_errors_are_retried(settings, db):
    failing = {"Abrechnung Kauf 2024-03-12": [DownloadError("HTTP 503", retryable=True),
                                              TimeoutError("timeout")]}
    adapter = FakeAdapter({"Postfach": docs()["Postfach"]}, failures=failing)
    run = Collector(settings, db).run_broker(adapter, "sync")
    assert adapter.download_calls.count("Abrechnung Kauf 2024-03-12") == 3
    assert db.get_run(run)["downloaded"] == 2


def test_one_error_does_not_abort(settings, db):
    failing = {"Abrechnung Kauf 2024-03-12": [RuntimeError("kaputt")]}
    adapter = FakeAdapter(docs(), failures=failing)
    settings.retry_attempts = 1
    run = Collector(settings, db).run_broker(adapter, "sync")
    r = db.get_run(run)
    assert r["downloaded"] == 3 and r["failed"] == 2
    errors = db.run_results(run, "failed")
    assert "kaputt" in errors[0]["error_message"]


def test_invalid_html_recorded(settings, db):
    d = {"Postfach": [("Abrechnung", b"<html><body>Login</body></html>", "ui")]}
    run = Collector(settings, db).run_broker(FakeAdapter(d), "sync")
    res = db.run_results(run)
    assert res[0]["status"] == "invalid" and "HTML" in res[0]["error_message"]
    assert not list(settings.output_dir.rglob("*.pdf"))


def test_user_action_waits_and_continues(settings, db):
    events = []
    adapter = FakeAdapter(docs(), user_action_on="Jahressteuerbescheinigung 2023")
    run = Collector(settings, db, on_event=lambda k, d: events.append(k)).run_broker(adapter, "sync")
    assert "waiting_user" in events and adapter.login_waits == 1
    assert db.get_run(run)["downloaded"] == 3


def test_not_logged_in_waits_for_user(settings, db):
    adapter = FakeAdapter(docs(), logged_in=False)
    run = Collector(settings, db).run_broker(adapter, "sync")
    assert adapter.login_waits == 1 and db.get_run(run)["downloaded"] == 3


def test_login_timeout_stops_cleanly(settings, db):
    class NeverLogin(FakeAdapter):
        def wait_for_login(self, timeout_s, on_wait=None):
            return False

    run = Collector(settings, db).run_broker(NeverLogin(docs(), logged_in=False), "sync")
    r = db.get_run(run)
    assert r["status"] == "waiting_user" and "Zeitlimit" in r["message"]


def test_cancel_and_resume(settings, db):
    control = ScanControl()
    a1 = FakeAdapter(docs(), cancel_on="Jahressteuerbescheinigung 2023", control=control)
    run1 = Collector(settings, db, control).run_broker(a1, "sync")
    assert db.get_run(run1)["status"] == "cancelled"
    assert db.completed_area_keys(run1)  # Postfach war vollständig

    a2 = FakeAdapter(docs())
    run2 = Collector(settings, db, ScanControl()).run_broker(a2, "resume")
    assert db.get_run(run2)["resumed_from"] == run1
    assert "Postfach" not in a2.discover_calls  # vollständig untersuchter Bereich wird übersprungen
    assert a2.discover_calls == ["Steuern", "API"]
    areas = {a["name"]: a for a in db.areas_for_run(run2)}
    assert areas["Postfach"]["status"] == "complete" and "unterbrochenen Lauf" in areas["Postfach"]["note"]


def test_pause_blocks_until_resume(settings, db):
    control = ScanControl()
    control.pause()
    adapter = FakeAdapter(docs())
    result = {}

    def run():
        result["run"] = Collector(settings, db, control).run_broker(adapter, "sync")

    t = threading.Thread(target=run)
    t.start()
    t.join(0.6)
    assert t.is_alive() and adapter.download_calls == []
    control.resume()
    t.join(10)
    assert not t.is_alive() and db.get_run(result["run"])["downloaded"] == 3


def test_scan_manager_background(settings, db):
    created = {}

    def factory(broker, browser, s, control):
        created[broker] = FakeAdapter(docs())
        created[broker].broker_id = broker
        return created[broker]

    manager = ScanManager(settings, db, headless=True, adapter_factory=factory)
    try:
        assert manager.scan(["trade_republic", "scalable_capital"], "sync")
        assert not manager.scan(["trade_republic"], "sync")  # parallel nicht erlaubt
        manager._queue.join()
        snap = manager.snapshot()
        assert set(snap["last_reports"]) == {"trade_republic", "scalable_capital"}
        assert not snap["busy"]
        assert manager.rerun_last()
        manager._queue.join()
    finally:
        manager.shutdown()
    assert len(db.query("SELECT * FROM scan_runs")) == 4


def test_invalid_mode(settings, db):
    with pytest.raises(ValueError):
        Collector(settings, db).run_broker(FakeAdapter(docs()), "brute")


def test_login_starts_scan_automatically(settings, db):
    def factory(broker, browser, s, control):
        a = FakeAdapter(docs(), logged_in=False)
        a.broker_id = broker
        return a

    manager = ScanManager(settings, db, headless=True, adapter_factory=factory)
    try:
        assert manager.login("trade_republic")
        manager._queue.join()
        assert manager.login_state["trade_republic"] in ("angemeldet",)
        runs = db.query("SELECT * FROM scan_runs")
        assert len(runs) == 1 and runs[0]["broker"] == "trade_republic" and runs[0]["downloaded"] == 3
    finally:
        manager.shutdown()


def test_session_heuristic_without_nav_or_logout(settings):
    from broker_collector.trade_republic import TradeRepublicAdapter

    a = TradeRepublicAdapter(browser=None, settings=settings)  # type: ignore[arg-type]
    base = {"url": "https://app.traderepublic.com/portfolio", "passwordInputs": 0, "pinInputs": 0, "otpInputs": 0,
            "loginInputs": 0, "navLinks": 0, "links": 2, "textLength": 800, "logoutPresent": False}
    assert a.is_logged_in(base)  # gerenderte App ohne <nav>/Abmelden-Text
    assert not a.is_logged_in({**base, "url": "https://app.traderepublic.com/login"})
    assert not a.is_logged_in({**base, "loginInputs": 1})  # Telefonnummernfeld sichtbar
    assert not a.is_logged_in({**base, "pinInputs": 4})
    assert not a.is_logged_in({**base, "url": "https://evil.example.com/portfolio"})
    sparse = {**base, "textLength": 20}
    assert not a.is_logged_in(sparse)
    a.user_confirmed_login = True  # Benutzer hat bestätigt
    assert a.is_logged_in(sparse)
    assert not a.is_logged_in({**sparse, "passwordInputs": 1})  # Bestätigung überstimmt kein Loginformular
