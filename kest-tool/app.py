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
from kest_tool.config import load_env_file  # noqa: E402
from kest_tool.ui import common as C  # noqa: E402
from kest_tool.ui import pages_basic, pages_data, pages_import, pages_tax  # noqa: E402

load_env_file()  # optionale API-Schlüssel aus .env (nie in config.yaml)
st.set_page_config(page_title="KESt-Tool", page_icon="🧾", layout="wide")

import logging  # noqa: E402

try:  # Steuerausnahmen von Streamlit (st.rerun/st.stop) dürfen nicht abgefangen werden
    from streamlit.runtime.scriptrunner_utils.exceptions import ScriptControlException  # noqa: E402
except ImportError:  # pragma: no cover
    ScriptControlException = ()  # type: ignore[assignment]

P = {
    "dashboard": st.Page(pages_basic.dashboard, title="Übersicht", icon="🏠", default=True),
    "import": st.Page(pages_import.render, title="Import (erweitert)", icon="📥", url_path="import"),
    "dokumente": st.Page(pages_data.documents, title="Dokumente", icon="📄", url_path="dokumente"),
    "transaktionen": st.Page(pages_data.transactions, title="Transaktionen", icon="📒", url_path="transaktionen"),
    "wertpapiere": st.Page(pages_data.securities, title="Wertpapiere", icon="📈", url_path="wertpapiere"),
    "fonds": st.Page(pages_data.funds, title="Fonds & OeKB", icon="🗂️", url_path="fonds"),
    "depots": st.Page(pages_basic.brokers, title="Broker & Depots", icon="🏦", url_path="depots"),
    "steuer": st.Page(pages_tax.tax, title="Steuerberechnung", icon="🧮", url_path="steuer"),
    "exporte": st.Page(pages_tax.exports, title="Exporte", icon="💾", url_path="exporte"),
    "einstellungen": st.Page(pages_basic.settings_page, title="Einstellungen", icon="⚙️", url_path="einstellungen"),
}
C.PAGES.update(P)

nav = st.navigation({
    "Start": [P["dashboard"]],
    "1 · Daten erfassen": [P["import"], P["dokumente"], P["transaktionen"]],
    "2 · Daten ergänzen": [P["wertpapiere"], P["fonds"], P["depots"]],
    "3 · Ergebnis": [P["steuer"], P["exporte"]],
    "System": [P["einstellungen"]],
})
with st.sidebar:
    st.link_button("Broker-Dokumente synchronisieren", "http://127.0.0.1:8765", use_container_width=True)
    st.caption(f"KESt-Tool {__version__} · lokal · Ablage: `{C.ctx().store.base}`")
    st.caption(C.DISCLAIMER)
try:
    nav.run()
except ScriptControlException:
    raise
except Exception as exc:  # noqa: BLE001 – verständliche Fehlerseite statt Traceback
    logging.getLogger("kest_tool.ui").exception("Unerwarteter Fehler auf Seite %s", nav.title)
    st.error("**Hier ist leider etwas schiefgelaufen.** Ihre Daten sind nicht betroffen – es wurde nichts "
             "gespeichert, was nicht bestätigt war.\n\n"
             "Was Sie tun können: Seite neu laden (F5). Tritt der Fehler erneut auf, finden Sie Details im Protokoll "
             "unter Einstellungen → Protokolle → Anwendungslog.")
    with st.expander("Technische Details"):
        st.code(f"{type(exc).__name__}: {exc}")
