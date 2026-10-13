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
    assert any("Dashboard" in t.value for t in at.title)
    for page in PAGES:
        _goto(at, page)
        _run(at)
        assert at.title, page


def test_tax_page_shows_provisional_warning(demo_home):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    _goto(at, "steuer")
    _run(at)
    at.selectbox(key="tax_year_select").set_value(2024)
    _run(at)
    assert any("Keine endgültigen Ergebnisse" in w.value for w in at.warning)


def test_dashboard_excel_button(demo_home):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.selectbox(key="tax_year_select").set_value(2024)
    _run(at)
    btn = [b for b in at.button if b.label == "Excel-Export erstellen"][0]
    btn.click()
    _run(at)
    assert list((demo_home / "exports" / "2024" / "excel").glob("KESt_Auswertung_2024_*.xlsx"))
