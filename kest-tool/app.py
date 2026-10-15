"""KESt-Tool – lokale Streamlit-Anwendung.

Start:  streamlit run app.py   (oder start.bat unter Windows)
Die Oberfläche ist nur unter http://localhost:8501 bzw. 127.0.0.1 erreichbar (siehe .streamlit/config.toml).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from kest_tool import __version__  # noqa: E402
from kest_tool.diagnostics import record_error  # noqa: E402
from kest_tool.config import load_env_file  # noqa: E402
from kest_tool.ui import common as C  # noqa: E402
from kest_tool.ui import pages_basic, pages_data, pages_import, pages_tax  # noqa: E402
from kest_tool.ui.admin_theme import apply_admin_theme, render_page_header  # noqa: E402

load_env_file()  # optionale API-Schlüssel aus .env (nie in config.yaml)
st.set_page_config(page_title="KESt-Tool | Verwaltung", page_icon="🧾", layout="wide",
                   initial_sidebar_state="expanded")
apply_admin_theme()

import logging  # noqa: E402

try:  # Steuerausnahmen von Streamlit (st.rerun/st.stop) dürfen nicht abgefangen werden
    from streamlit.runtime.scriptrunner_utils.exceptions import ScriptControlException  # noqa: E402
except ImportError:  # pragma: no cover
    ScriptControlException = ()  # type: ignore[assignment]

def admin_page(key: str, render):
    """Apply the same header and layout to every page without changing its logic."""
    def page() -> None:
        render_page_header(key)
        render()
    return page


P = {
    "dashboard": st.Page(admin_page("dashboard", pages_basic.dashboard), title="Übersicht", icon="🏠", default=True),
    "import": st.Page(admin_page("import", pages_import.render), title="Import", icon="📥", url_path="import"),
    "dokumente": st.Page(admin_page("dokumente", pages_data.documents), title="Dokumente", icon="📄", url_path="dokumente"),
    "transaktionen": st.Page(admin_page("transaktionen", pages_data.transactions), title="Transaktionen", icon="📒", url_path="transaktionen"),
    "wertpapiere": st.Page(admin_page("wertpapiere", pages_data.securities), title="Wertpapiere", icon="📈", url_path="wertpapiere"),
    "fonds": st.Page(admin_page("fonds", pages_data.funds), title="Fonds & OeKB", icon="🗂️", url_path="fonds"),
    "depots": st.Page(admin_page("depots", pages_basic.brokers), title="Broker & Depots", icon="🏦", url_path="depots"),
    "steuer": st.Page(admin_page("steuer", pages_tax.tax), title="Steuerberechnung", icon="🧮", url_path="steuer"),
    "exporte": st.Page(admin_page("exporte", pages_tax.exports), title="Exporte", icon="💾", url_path="exporte"),
    "einstellungen": st.Page(admin_page("einstellungen", pages_basic.settings_page), title="Einstellungen", icon="⚙️", url_path="einstellungen"),
}
C.PAGES.update(P)

nav = st.navigation({
    "ÜBERSICHT": [P["dashboard"]],
    "DOKUMENTE & BUCHUNGEN": [P["import"], P["dokumente"], P["transaktionen"]],
    "STAMMDATEN": [P["wertpapiere"], P["fonds"], P["depots"]],
    "STEUERN & BERICHTE": [P["steuer"], P["exporte"]],
    "SYSTEM": [P["einstellungen"]],
})
with st.sidebar:
    st.markdown('<div class="kest-admin-brand">KESt<span>Manager</span></div>',
                unsafe_allow_html=True)
    st.page_link(P["import"], label="Dokumente hochladen", icon="📥")
    st.markdown(f'<div class="kest-sidebar-caption">Version {__version__} · lokal</div>',
                unsafe_allow_html=True)
    st.caption(C.DISCLAIMER)
st.markdown('<div class="kest-admin-context">Lokale Steuerverwaltung · Keine automatische Übermittlung an FinanzOnline</div>',
            unsafe_allow_html=True)
try:
    nav.run()
except ScriptControlException:
    raise
except Exception as exc:  # noqa: BLE001 – verständliche Fehlerseite statt Traceback
    error_id = record_error(str(nav.title), exc)
    st.error("**Ein unerwarteter Fehler ist aufgetreten.** Prüfen Sie vor einem erneuten Versuch, "
             "ob die letzte Aktion bereits gespeichert wurde.\n\n"
             "Laden Sie die Seite neu (F5). Bei wiederholten Fehlern können Sie unter "
             "Einstellungen → Diagnose einen Bericht exportieren.")
    st.caption(f"Fehlerkennung: {error_id}. Unter Einstellungen → Diagnose können Sie einen Bericht exportieren.")
