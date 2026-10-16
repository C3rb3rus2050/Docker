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
        if key in ('wertpapiere', 'dokumente'):
            with st.container(key=f'compact_review_{key}'):
                render()
        else:
            render()
    return page


P = {
    "dashboard": st.Page(admin_page("dashboard", pages_basic.dashboard), title="Übersicht", icon="🏠", default=True),
    "import": st.Page(admin_page("import", pages_import.render), title="Dateien hinzufügen", icon="📥", url_path="import"),
    "dokumente": st.Page(admin_page("dokumente", pages_data.documents), title="Belege & Prüfung", icon="📄", url_path="dokumente"),
    "transaktionen": st.Page(admin_page("transaktionen", pages_data.transactions), title="Buchungen", icon="📒", url_path="transaktionen"),
    "wertpapiere": st.Page(admin_page("wertpapiere", pages_data.securities), title="Wertpapiere", icon="📈", url_path="wertpapiere"),
    "fonds": st.Page(admin_page("fonds", pages_data.funds), title="Fonds & OeKB", icon="🗂️", url_path="fonds"),
    "depots": st.Page(admin_page("depots", pages_basic.brokers), title="Broker & Depots", icon="🏦", url_path="depots"),
    "steuer": st.Page(admin_page("steuer", pages_tax.tax), title="Steuerberechnung", icon="🧮", url_path="steuer"),
    "exporte": st.Page(admin_page("exporte", pages_tax.exports), title="Exporte", icon="💾", url_path="exporte"),
    "einstellungen": st.Page(admin_page("einstellungen", pages_basic.settings_page), title="Einstellungen", icon="⚙️", url_path="einstellungen"),
}
C.PAGES.update(P)

groups = {
    "START": [P["dashboard"]],
    "1 · DATEIEN & PRÜFUNG": [P["import"], P["dokumente"], P["transaktionen"]],
    "2 · STAMMDATEN": [P["wertpapiere"], P["fonds"], P["depots"]],
    "3 · AUSWERTUNG": [P["steuer"], P["exporte"]],
    "SYSTEM": [P["einstellungen"]],
}
nav = st.navigation(groups, position="hidden")
with st.sidebar:
    st.markdown('<div class="kest-admin-brand"><span class="kest-brand-mark">K</span>'
                '<div>KESt<span class="kest-brand-name">Manager</span>'
                '<small>DEINE STEUERZENTRALE</small></div></div>',
                unsafe_allow_html=True)
    C.YEAR_LOCATION = st.container(key='navigation_year')
    icons = {"dashboard": "dashboard", "import": "upload_file", "dokumente": "fact_check",
             "transaktionen": "receipt_long", "wertpapiere": "monitoring", "fonds": "folder_open",
             "depots": "account_balance", "steuer": "calculate", "exporte": "download", "einstellungen": "settings"}
    menu_groups = {'ARBEITSPLATZ': ['dashboard', 'import', 'dokumente', 'transaktionen'],
                   'VERWALTUNG': ['depots', 'wertpapiere', 'fonds'],
                   'AUSWERTUNG': ['steuer', 'exporte'], 'SYSTEM': ['einstellungen']}
    for group, keys in menu_groups.items():
        st.markdown(f'<div class="kest-nav-group">{group}</div>', unsafe_allow_html=True)
        for key in keys:
            active = '_active' if nav.url_path == P[key].url_path else ''
            with st.container(key=f'nav_{key}{active}'):
                st.page_link(P[key], label=P[key].title, icon=f':material/{icons[key]}:')
    st.divider()
    st.caption('Darstellung: oben rechts ⋮ → Light (Hell), Dark (Dunkel) oder System wählen.')
    st.markdown(f'<div class="kest-sidebar-caption">Version {__version__} · Private Verwaltung</div>',
                unsafe_allow_html=True)
    st.caption(C.DISCLAIMER)
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
