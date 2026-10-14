import json
import logging
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from broker_collector import cli
from broker_collector.config import Settings, load_settings, save_settings
from broker_collector.logging_setup import setup_logging
from broker_collector.maintenance import delete_browser_profile, delete_database, delete_downloads
from broker_collector.scheduler import SchedulerError, build_create_command
from broker_collector.ui import App, make_handler


class FakeManager:
    busy = False

    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"busy": False, "task": "", "status": {}, "paused": False, "login": {}, "messages": [],
                "last_reports": {}}

    def scan(self, brokers, mode):
        self.calls.append(("scan", brokers, mode))
        return True

    def login(self, broker, auto_scan=True, mode="sync"):
        self.calls.append(("login", broker))
        return True

    def pause(self):
        self.calls.append(("pause",))


@pytest.fixture
def server(settings, db, tmp_path):
    app = App(settings, db, FakeManager(), tmp_path / "config.toml")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(app, port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield app, port
    httpd.shutdown()
    httpd.server_close()


def request(port, path, method="GET", body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_index_contains_token_and_german_ui(server):
    app, port = server
    status, body = request(port, "/")
    text = body.decode()
    assert status == 200 and app.token in text
    for label in ("Anmelden &amp; Dokumente holen", "Ich bin angemeldet – weiter", "Automatischen Scan starten", "Pausieren", "Abbrechen", "Duplikate",
                  "Ausgabeordner öffnen", "Bericht exportieren", "Einstellungen"):
        assert label in text
    assert "http://" not in text.replace("http://127.0.0.1", "") and "https://" not in text  # keine externen Quellen


def test_post_requires_token(server):
    app, port = server
    assert request(port, "/api/scan", "POST", {"mode": "sync"})[0] == 403
    status, _ = request(port, "/api/scan", "POST", {"mode": "sync", "brokers": ["trade_republic"]},
                        {"X-BDC-Token": app.token})
    assert status == 202
    assert app.manager.calls == [("scan", ["trade_republic"], "sync")]


def test_host_header_checked(server):
    app, port = server
    assert request(port, "/api/state", headers={"Host": "evil.example.com"})[0] == 403


def test_state_and_delete_confirmation(server):
    app, port = server
    status, body = request(port, "/api/state")
    data = json.loads(body)
    assert status == 200 and "settings" in data and "password" not in json.dumps(data).lower()
    status, body = request(port, "/api/delete", "POST", {"what": "downloads"}, {"X-BDC-Token": app.token})
    assert status == 400 and "LÖSCHEN" in json.loads(body)["error"]


def test_settings_roundtrip(tmp_path):
    s = Settings(output_dir=tmp_path / "o", profile_dir=tmp_path / "p")
    s.ocr_enabled = True
    cfg = tmp_path / "config.toml"
    save_settings(s, cfg)
    loaded = load_settings(cfg)
    assert loaded.ocr_enabled is True and loaded.output_dir == tmp_path / "o"
    assert "password" not in cfg.read_text(encoding="utf-8").lower()


def test_logging_rotating_and_redacted(tmp_path):
    setup_logging(tmp_path, console=False)
    logging.getLogger("broker_collector.test").warning(
        "Fehler bei https://x.traderepublic.com/a.pdf?X-Amz-Signature=GEHEIM token=ABC cookie: tr_session=XYZ")
    for h in logging.getLogger().handlers:
        h.flush()
    content = (tmp_path / "collector.log").read_text(encoding="utf-8")
    assert "GEHEIM" not in content and "tr_session=XYZ" not in content and "a.pdf" in content
    from logging.handlers import RotatingFileHandler

    assert any(isinstance(h, RotatingFileHandler) for h in logging.getLogger().handlers)


def test_separate_deletion(settings):
    (settings.profile_dir / "trade_republic").mkdir(parents=True)
    (settings.profile_dir / "scalable_capital").mkdir(parents=True)
    (settings.output_dir / "TradeRepublic" / "Steuer").mkdir(parents=True)
    (settings.output_dir / "TradeRepublic" / "Steuer" / "a.pdf").write_bytes(b"x")
    settings.database_path.write_bytes(b"db")
    assert delete_browser_profile(settings, "trade_republic")
    assert not (settings.profile_dir / "trade_republic").exists()
    assert (settings.profile_dir / "scalable_capital").exists()
    assert settings.database_path.exists()
    assert delete_downloads(settings, "trade_republic")
    assert not (settings.output_dir / "TradeRepublic").exists() and settings.database_path.exists()
    assert delete_database(settings) and not settings.database_path.exists()


def test_scheduler_command():
    cmd = build_create_command(Path("C:/bdc/start.bat"), "07:30")
    assert cmd[:2] == ["schtasks", "/Create"] and "/IT" in cmd and "LIMITED" in cmd
    assert cmd[cmd.index("/TR") + 1].endswith('start.bat" --sync')
    with pytest.raises(SchedulerError):
        build_create_command(Path("start.bat"), "25:00")


def test_cli_report_and_delete(settings, db, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("BDC_OUTPUT_DIR", str(settings.output_dir))
    cfg = tmp_path / "none.toml"
    run = db.start_run("trade_republic", "sync")
    db.finish_run(run, "finished")
    assert cli.main(["--config", str(cfg), "--report", str(run)]) == 0
    assert list(settings.reports_dir.glob("*.html"))
    assert cli.main(["--config", str(cfg), "--delete-downloads", "--yes"]) == 0
    assert "Gelöscht" in capsys.readouterr().out


def test_example_config_is_valid():
    import tomllib

    from broker_collector.config import apply_values

    data = tomllib.loads((Path(__file__).resolve().parents[1] / "config.example.toml").read_text(encoding="utf-8"))
    apply_values(Settings(), data)  # wirft bei unbekannten/verbotenen Schlüsseln
