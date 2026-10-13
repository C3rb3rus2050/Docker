"""Gemeinsame Hilfsfunktionen der Streamlit-Oberfläche."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import streamlit as st

from ..config import load_settings
from ..context import AppContext, create_context
from ..storage import StorageError
from ..tax.engine import TaxResult, compute
from ..tax.rules import YearNotSupported, load_rules

log = logging.getLogger("kest_tool.ui")

DISCLAIMER = ("Arbeitshilfe zur Vorbereitung der Einkommensteuererklärung – ersetzt keine Steuerberatung. "
              "Es wird nichts an FinanzOnline übermittelt.")


@st.cache_resource(show_spinner=False)
def _context(base_dir: str) -> AppContext:
    # base_dir dient als Cache-Schlüssel: Nach Änderung des Ablageordners wird ein neuer Kontext erzeugt.
    return create_context(load_settings())


def ctx() -> AppContext:
    settings = load_settings()
    try:
        return _context(str(settings.base_dir))
    except (StorageError, OSError) as exc:
        st.error(f"Ablageordner nicht nutzbar: {exc}")
        st.stop()


def reset_context() -> None:
    _context.clear()
    st.session_state.pop("tax_result", None)


def year_selector(location=st.sidebar) -> int:
    c = ctx()
    years = c.settings.tax_years
    default = st.session_state.get("tax_year", c.settings.default_tax_year)
    qp = st.query_params.get("jahr")
    if qp and qp.isdigit() and int(qp) in years and "tax_year_select" not in st.session_state:
        default = int(qp)
    if default not in years:
        default = years[-1] if years else 2024
    y = location.selectbox("Steuerjahr", years, index=years.index(default) if default in years else 0,
                           key="tax_year_select")
    st.session_state["tax_year"] = int(y)
    return int(y)


def tax_result(y: int, force: bool = False) -> TaxResult | None:
    """Berechnet (und cached in der Sitzung) das Ergebnis für ein Steuerjahr."""
    key = f"tax_result_{y}"
    if force or key not in st.session_state:
        try:
            st.session_state[key] = compute(ctx().repo, y, load_rules())
        except YearNotSupported as exc:
            st.error(str(exc))
            return None
    return st.session_state[key]


def invalidate_results() -> None:
    for k in list(st.session_state.keys()):
        if str(k).startswith("tax_result_"):
            del st.session_state[k]


def df(rows, **kw) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        st.info("Keine Einträge.")
        return
    st.dataframe(frame, width="stretch", hide_index=True, **kw)


def eur(v) -> str:
    if v is None:
        return "–"
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def open_file_button(path: Path, key: str, label: str = "Mit Standardprogramm öffnen") -> None:
    c = ctx()
    if st.button(label, key=key):
        try:
            c.store.open_in_os(path)
            st.success("Datei geöffnet (lokal).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Öffnen nicht möglich: {exc}")


def download_button(path: Path, key: str, label: str = "Herunterladen") -> None:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        st.error(f"Datei nicht lesbar: {exc}")
        return
    st.download_button(label, data=data, file_name=Path(path).name, key=key)


def depot_options() -> dict[str, int]:
    return {f"{d['broker_name']} – {d['name']}": d["id"] for d in ctx().repo.depots(active_only=True)}


def status_badge(status: str) -> str:
    return {"berechnet": "🟢", "vorlaeufig": "🟡", "manuell_pruefen": "🔴"}.get(status, "⚪")
