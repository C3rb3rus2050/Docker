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
from kest_tool.ui import common as C  # noqa: E402
from kest_tool.ui import pages_basic, pages_data, pages_import, pages_tax  # noqa: E402

st.set_page_config(page_title="KESt-Tool", page_icon="🧾", layout="wide")

pages = [
    st.Page(pages_basic.dashboard, title="Dashboard", icon="📊", default=True),
    st.Page(pages_basic.brokers, title="Broker & Depots", icon="🏦", url_path="depots"),
    st.Page(pages_import.render, title="Import", icon="📥", url_path="import"),
    st.Page(pages_data.transactions, title="Transaktionen", icon="📒", url_path="transaktionen"),
    st.Page(pages_data.securities, title="Wertpapiere", icon="📈", url_path="wertpapiere"),
    st.Page(pages_data.funds, title="Fonds & OeKB", icon="🗂️", url_path="fonds"),
    st.Page(pages_data.documents, title="Dokumente", icon="📄", url_path="dokumente"),
    st.Page(pages_tax.tax, title="Steuerberechnung", icon="🧮", url_path="steuer"),
    st.Page(pages_tax.exports, title="Exporte", icon="💾", url_path="exporte"),
    st.Page(pages_basic.settings_page, title="Einstellungen", icon="⚙️", url_path="einstellungen"),
]

nav = st.navigation(pages)
with st.sidebar:
    st.caption(f"KESt-Tool {__version__} · lokal · Ablage: `{C.ctx().store.base}`")
    st.caption(C.DISCLAIMER)
nav.run()
