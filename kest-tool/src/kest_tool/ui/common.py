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
    default = st.session_state.get("tax_year")
    if default is None:
        # Standard: jüngstes Steuerjahr, in dem Buchungen vorhanden sind (sonst Vorjahr laut Einstellungen)
        row = c.db.one("SELECT MAX(substr(trade_date,1,4)) y FROM transactions WHERE deleted=0")
        data_year = int(row["y"]) if row and row["y"] else None
        default = data_year if data_year in years else c.settings.default_tax_year
    qp = st.query_params.get("jahr")
    if qp and qp.isdigit() and int(qp) in years and "tax_year" not in st.session_state:
        default = int(qp)
    if default not in years:
        default = years[-1] if years else 2024
    # Schlüssel mit Generationszähler: erlaubt ein programmgesteuertes Umschalten des Jahres (neuer Widget-Zustand)
    y = location.selectbox("Steuerjahr", years, index=years.index(default) if default in years else 0,
                           key=f"tax_year_select_{st.session_state.get('year_widget_gen', 0)}")
    st.session_state["tax_year"] = int(y)
    counts = c.db.query("SELECT substr(trade_date,1,4) y, COUNT(*) n FROM transactions WHERE deleted=0 "
                        "GROUP BY y ORDER BY y")
    if counts:
        location.caption("Buchungen je Jahr: " + ", ".join(f"{r['y']}: {r['n']}" for r in counts))
    return int(y)


def show_process_results(results) -> None:
    """Zeigt das Ergebnis der PDF-Stapelverarbeitung je Datei mit Status."""
    if not results:
        st.info("Keine offenen PDF-Dokumente.")
        return
    icons = {"angelegt": "✅", "dublette": "🔁", "pruefen": "🟡", "uebersprungen": "⏭️", "fehler": "🔴"}
    n_ok = sum(1 for r in results if r.status == "angelegt")
    n_rev = sum(1 for r in results if r.status == "pruefen")
    (st.success if n_ok else st.warning)(
        f"{n_ok} Buchung(en) angelegt · {n_rev} Dokument(e) brauchen Ihre Prüfung (Seite Dokumente) · "
        f"{sum(1 for r in results if r.status == 'dublette')} bereits vorhanden")
    df([{"": icons.get(r.status, ""), "Datei": r.filename, "Status": r.status, "Ergebnis / Grund": r.message}
        for r in results])
    invalidate_results()


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


def status_panel(y: int, key: str) -> None:
    """Datenstand und nächste Schritte – erklärt, warum (noch) nichts berechnet wird."""
    from ..processing import data_status, process_documents

    c = ctx()
    stt = data_status(c.repo, y)
    res = tax_result(y)
    with st.container(border=True):
        st.subheader(f"Status {y}")
        rows = []
        rows.append(("✅" if stt["depots"] else "❌", "Depots angelegt",
                     f"{stt['depots']}" if stt["depots"] else "Seite **Broker & Depots** → Broker und Depot anlegen"))
        other = {yy: n for yy, n in stt["tx_by_year"].items() if yy != y}
        if stt["tx_year"]:
            rows.append(("✅", f"Buchungen {y}", str(stt["tx_year"])))
        else:
            hint = "Seite **Import** → CSV/PDF importieren"
            if other:
                hint = ("Buchungen vorhanden in " + ", ".join(f"{yy} ({n})" for yy, n in sorted(other.items()))
                        + " → links das **Steuerjahr** wechseln")
            rows.append(("❌", f"Buchungen {y}", hint))
        n_open = len(stt["docs_open"])
        rows.append(("🟡" if n_open else "✅", "Dokumente ohne Buchung",
                     f"{n_open} – unten automatisch verarbeiten oder auf der Seite **Dokumente** prüfen"
                     if n_open else "keine"))
        if res:
            s = res.summary
            calc = s["Positionen gesamt"] - s["Positionen vorläufig"] - s["Positionen manuell zu prüfen"]
            if s["Positionen gesamt"]:
                rows.append(("🟢" if calc else "🟡", "Steuerpositionen",
                             f"{s['Positionen gesamt']} gesamt: 🟢 {calc} berechnet · 🟡 {s['Positionen vorläufig']} "
                             f"vorläufig · 🔴 {s['Positionen manuell zu prüfen']} manuell zu prüfen"))
            else:
                rows.append(("❌", "Steuerpositionen", "keine – es fehlen steuerlich relevante Buchungen in diesem Jahr"))
            errs = sum(1 for i in res.issues if i.severity == "Fehler")
            warns = sum(1 for i in res.issues if i.severity == "Warnung")
            rows.append(("🔴" if errs else ("🟡" if warns else "✅"), "Prüfhinweise",
                         f"{errs} Fehler, {warns} Warnungen – Details: **Steuerberechnung → Prüfhinweise**"))
        for icon, label, text in rows:
            st.markdown(f"{icon} **{label}:** {text}")
        pdf_open = [d for d in stt["docs_open"] if d["file_type"] == "pdf"]
        if pdf_open:
            deps = depot_options()
            cols = st.columns([2, 1])
            dflt = cols[0].selectbox("Standarddepot, falls das Depot nicht eindeutig ist", ["—"] + list(deps),
                                     key=f"dflt_depot_{key}")
            if cols[1].button(f"{len(pdf_open)} offene PDFs automatisch verarbeiten", key=f"proc_{key}",
                              type="primary"):
                results = process_documents(c.repo, [d["id"] for d in pdf_open], deps.get(dflt))
                after_processing(results)
        if "last_process_results" in st.session_state:
            show_process_results(st.session_state.pop("last_process_results"))


def after_processing(results) -> None:
    """Ergebnis merken, auf das jüngste Jahr mit neuen Buchungen wechseln und Seite neu aufbauen."""
    c = ctx()
    invalidate_results()
    st.session_state["last_process_results"] = results
    new_years = [c.repo.transaction(r.transaction_id)["trade_date"][:4] for r in results if r.transaction_id]
    if new_years:
        y = int(max(new_years))
        if y in c.settings.tax_years:
            st.session_state["tax_year"] = y
            st.session_state["year_widget_gen"] = st.session_state.get("year_widget_gen", 0) + 1
    st.rerun()
