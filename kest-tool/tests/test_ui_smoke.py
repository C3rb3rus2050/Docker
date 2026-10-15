"""Rauchtest der Streamlit-Oberfläche (headless via AppTest) mit Demo-Ablage."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from kest_tool.demo import build_demo  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PAGES = ["depots", "import", "transaktionen", "wertpapiere", "fonds", "dokumente", "steuer", "exporte",
         "einstellungen"]


@pytest.fixture()
def demo_home(tmp_path, monkeypatch):
    home = tmp_path / "KESt-Demo"
    monkeypatch.setenv("KEST_TOOL_HOME", str(home))
    build_demo(home)
    return home


def _goto(at: AppTest, url_path: str) -> None:
    """Wechselt auf eine per st.navigation registrierte (Funktions-)Seite."""
    for page_hash, info in at._registered_pages.items():
        if info.get("url_pathname") == url_path:
            at._page_hash = page_hash
            return
    raise AssertionError(f"Seite {url_path} nicht registriert: {at._registered_pages}")


def _run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_all_pages_render(demo_home):
    at = _run(AppTest.from_file(APP, default_timeout=120))
    assert any("Übersicht" in t.value for t in at.title)
    for page in PAGES:
        _goto(at, page)
        _run(at)
        assert at.title, page


def test_tax_page_shows_provisional_warning(demo_home):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    _goto(at, "steuer")
    _run(at)
    at.selectbox(key="tax_year_select_0").set_value(2024)
    _run(at)
    assert any("Keine endgültigen Ergebnisse" in w.value for w in at.warning)


def test_dashboard_excel_button(demo_home):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.selectbox(key="tax_year_select_0").set_value(2024)
    _run(at)
    btn = [b for b in at.button if b.label == "Excel-Export erstellen"][0]
    btn.click()
    _run(at)
    assert list((demo_home / "exports" / "2024" / "excel").glob("KESt_Auswertung_2024_*.xlsx"))


def test_quickstart_creates_depots(tmp_path, monkeypatch):
    home = tmp_path / "leer"
    monkeypatch.setenv("KEST_TOOL_HOME", str(home))
    at = _run(AppTest.from_file(APP, default_timeout=120))
    assert any("Schnellstart" in s.value for s in at.subheader)
    at.checkbox[1].check()                                   # Scalable Capital zusätzlich zu Trade Republic
    [b for b in at.button if b.label == "Depots anlegen"][0].click()
    _run(at)
    from kest_tool.db import Database
    db = Database(home / "database" / "kest_tool.db")
    assert {r["name"] for r in db.query("SELECT name FROM depots")} == {"Trade Republic Depot",
                                                                         "Scalable Capital Depot"}
    db.close()
    assert not any("Schnellstart" in s.value for s in at.subheader)


def test_upload_runs_without_import_button_and_survives_reruns(tmp_path, monkeypatch):
    import streamlit as st
    from kest_tool.db import Database

    home = tmp_path / 'auto-upload'
    monkeypatch.setenv('KEST_TOOL_HOME', str(home))
    class Upload:
        name = 'TradeRepublic.csv'
        def __init__(self, day):
            self.day = day
        def getvalue(self):
            return ('Datum;Typ;ISIN;Stück;Bruttobetrag;Währung\n'
                    f'{self.day}.02.2024;Kauf;US0378331005;2;300,00;EUR\n').encode()
    files = [Upload('01')]
    original = st.file_uploader
    def uploader(*args, **kwargs):
        if kwargs.get('key') == 'upl_auto_import_page':
            return files
        return original(*args, **kwargs)
    monkeypatch.setattr(st, 'file_uploader', uploader)
    at = _run(AppTest.from_file(APP, default_timeout=120))
    _goto(at, 'import')
    _run(at)
    _run(at)
    db = Database(home / 'database' / 'kest_tool.db')
    assert db.one('SELECT COUNT(*) n FROM transactions')['n'] == 1
    files.append(Upload('15'))
    _run(at)
    assert db.one('SELECT COUNT(*) n FROM transactions')['n'] == 2
    db.close()
