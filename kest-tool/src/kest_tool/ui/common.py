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

PAGES: dict = {}   # url_path -> st.Page (wird in app.py gesetzt)


def link(page: str, label: str, icon: str = "➡️") -> None:
    """Link auf eine andere Seite der Anwendung (falls registriert)."""
    target = PAGES.get(page)
    if target is not None:
        st.page_link(target, label=label, icon=icon)


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
    invalidate_results()


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


def show_process_results(results, *, inline: bool = True, key: str = 'process') -> None:
    """Keep the import result editable in place across Streamlit reruns."""
    if not results:
        return
    from .document_review import document_cards, OPEN
    repo = ctx().repo
    pending = []
    for result in results:
        doc = repo.document(result.document_id)
        if doc and doc['status'] in OPEN and doc['id'] not in {d['id'] for d in pending}:
            pending.append(doc)
    st.info(f"{len(results)} Datei(en) geprüft · {len(pending)} noch offen")
    if inline and pending:
        document_cards(repo, pending, key=key, messages={r.document_id: r.message for r in results})
    elif inline:
        notice = st.session_state.pop('document_review_saved', None)
        if notice:
            st.success(notice)
    with st.expander('Verarbeitungsprotokoll'):
        df([{'Datei': r.filename, 'Status': r.status, 'Ergebnis': r.message} for r in results])


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
    from ..processing import data_status

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
        n_fx = missing_fx_count(y)
        if n_fx:
            rows.append(("🔴", "Devisenkurse fehlen", f"{n_fx} Buchung(en) in Fremdwährung ohne Kurs – Schaltfläche "
                                                      "unten oder Einstellungen → Devisenkurse"))
        elif c.db.one("SELECT COUNT(*) n FROM transactions WHERE deleted=0 AND currency<>'EUR'")["n"]:
            rows.append(("✅", "Devisenkurse", "für alle Fremdwährungsbuchungen vorhanden"))
        miss = missing_price_info(y)
        if miss["nmf"]:
            rows.append(("🔴", "Kurse Nichtmeldefonds fehlen", f"{len(miss['nmf'])} Fonds ohne ersten/letzten Kurs {y} "
                                                               "– Schaltfläche unten oder Fonds & OeKB"))
        if miss["year_end"] and price_service().provider.available:
            rows.append(("ℹ️", "Kurse zum 31.12. fehlen", f"{len(miss['year_end'])} Wertpapier(e) – nur für die "
                                                          "Bestandsbewertung, nicht steuerrelevant"))
        n_open = len(stt["docs_open"])
        rows.append(("🟡" if n_open else "✅", "Dokumente ohne Buchung",
                     f"{n_open} – auf der Seite **Dokumente** öffnen; dort zeigt der Prüfbericht, was fehlt"
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
        targets = {"Dokumente ohne Buchung": "dokumente", "Prüfhinweise": "steuer", "Depots angelegt": "depots",
                   "Kurse Nichtmeldefonds fehlen": "fonds"}
        for icon, label, text in rows:
            if icon in ("✅", "🟢") or label not in targets:
                st.markdown(f"{icon} **{label}:** {text}")
            else:
                cols = st.columns([5, 2])
                cols[0].markdown(f"{icon} **{label}:** {text}")
                with cols[1]:
                    link(targets[label], "Öffnen")
        from .guide import data_check
        checks = data_check(y)
        if checks:
            st.markdown("**Datenprüfung – das sollten Sie noch ergänzen:**")
            for icon, topic, text, page in checks:
                cols = st.columns([5, 2])
                cols[0].markdown(f"{icon} **{topic}:** {text}")
                with cols[1]:
                    link(page, "Beheben")
        if n_fx and st.button(f"Devisenkurse für {n_fx} Buchung(en) von der EZB ergänzen", key=f"fx_{key}"):
            fill_fx(y, allow_download=True)
            tax_result(y, force=True)
        if (miss["nmf"] or (miss["year_end"] and price_service().provider.available)) and \
                st.button("Wertpapierkurse automatisch laden", key=f"px_{key}"):
            fill_prices(y)
            tax_result(y, force=True)
        pdf_open = [d for d in stt["docs_open"] if d["file_type"] == "pdf"]
        if pdf_open:
            deps = depot_options()
            cols = st.columns([2, 1])
            dflt = cols[0].selectbox("Standarddepot, falls das Depot nicht eindeutig ist", ["—"] + list(deps),
                                     key=f"dflt_depot_{key}")
            if cols[1].button(f"{len(pdf_open)} offene PDF(s) erneut verarbeiten", key=f"proc_{key}"):
                results = process_documents(c.repo, [d["id"] for d in pdf_open], deps.get(dflt))
                after_processing(results)


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


def missing_fx_count(y: int | None = None) -> int:
    sql = "SELECT COUNT(*) n FROM transactions WHERE deleted=0 AND currency<>'EUR' AND (fx_rate IS NULL OR fx_rate<=0)"
    params: tuple = ()
    if y:
        sql += " AND trade_date<=?"
        params = (f"{y}-12-31",)
    return ctx().db.one(sql, params)["n"]


def fill_fx(y: int | None = None, allow_download: bool | None = None, show: bool = True) -> list:
    """Ergänzt fehlende Devisenkurse aus EZB-Referenzkursen und zeigt das Ergebnis."""
    from ..fx import FxError, FxService, fill_missing_fx

    c = ctx()
    if allow_download is None:
        allow_download = bool(c.settings.get("fx.auto_fetch", True))
    try:
        with st.spinner("Lade EZB-Referenzkurse …"):
            res = fill_missing_fx(c.repo, FxService(c.store.base), y, allow_download=allow_download)
    except FxError as exc:
        if show:
            st.error(str(exc))
        return []
    if res:
        invalidate_results()
        if show:
            ok = [r for r in res if r.status == "gesetzt"]
            (st.success if len(ok) == len(res) else st.warning)(
                f"Devisenkurse ergänzt: {len(ok)} von {len(res)} Buchungen (EZB-Referenzkurs; Belegkurse werden nie "
                "überschrieben).")
            df([{"Buchung": r.tx_id, "Datum": r.trade_date, "Währung": r.currency, "Kurs je EUR": r.rate,
                 "Kursdatum": r.rate_date, "Ergebnis": r.message} for r in res])
    return res


def auto_fill_fx(y: int | None = None) -> None:
    """Automatischer Abruf (einmal je Sitzung und Datenstand), sofern in der Konfiguration erlaubt."""
    c = ctx()
    if not c.settings.get("fx.auto_fetch", True):
        return
    n = missing_fx_count(y)
    marker = f"fx_auto_{y}_{n}"
    if n and not st.session_state.get(marker):
        st.session_state[marker] = True
        fill_fx(y)


def price_service():
    from ..prices import EodhdProvider, PriceService

    c = ctx()
    return PriceService(c.repo, EodhdProvider(exchanges=c.settings.get("prices.preferred_exchanges")))


def missing_price_info(y: int) -> dict:
    """Welche Kurse für das Jahr fehlen (Nichtmeldefonds-Jahreskurse, Bewertung 31.12.)."""
    c = ctx()
    nmf = c.db.query(
        "SELECT DISTINCT t.isin FROM transactions t JOIN securities s ON s.isin=t.isin WHERE t.deleted=0 "
        "AND s.fund_status='nichtmeldefonds' AND t.trade_date<=? AND NOT EXISTS (SELECT 1 FROM nmf_prices p "
        "WHERE p.isin=t.isin AND p.tax_year=? AND p.first_price IS NOT NULL AND p.last_price IS NOT NULL)",
        (f"{y}-12-31", y))
    held = c.db.query(
        "SELECT DISTINCT t.isin FROM transactions t WHERE t.deleted=0 AND t.isin IS NOT NULL AND t.trade_date<=? "
        "AND NOT EXISTS (SELECT 1 FROM security_prices p WHERE p.isin=t.isin AND p.price_date BETWEEN ? AND ?)",
        (f"{y}-12-31", f"{y}-12-21", f"{y}-12-31"))
    return {"nmf": [r["isin"] for r in nmf], "year_end": [r["isin"] for r in held]}


def fill_prices(y: int, show: bool = True) -> list:
    from ..prices import PriceError, fill_nmf_prices, fill_year_end_prices

    svc = price_service()
    from ..prices import NAV_MARKER
    has_nav_csv = ctx().db.one("SELECT COUNT(*) n FROM security_prices WHERE source LIKE ?", (f"%{NAV_MARKER}%",))["n"]
    if not svc.provider.available and not has_nav_csv:
        if show:
            st.warning("Kein API-Schlüssel für den Kursdienst hinterlegt → **Einstellungen → Wertpapierkurse**. "
                       "Alternativ Kurse als CSV importieren.")
        return []
    try:
        with st.spinner("Lade Wertpapierkurse …"):
            res = fill_nmf_prices(ctx().repo, svc, y,
                                  bool(ctx().settings.get("prices.nmf_exchange_fallback", True))) \
                + fill_year_end_prices(ctx().repo, svc, y)
    except PriceError as exc:
        if show:
            st.error(str(exc))
        return []
    invalidate_results()
    if show and res:
        icons = {"gesetzt": "✅", "identisch": "⏭️", "konflikt": "🟡", "kein_kurs": "🟡", "fehler": "🔴"}
        n_ok = sum(1 for r in res if r.status == "gesetzt")
        (st.success if n_ok else st.info)(f"Wertpapierkurse: {n_ok} neu geladen, "
                                          f"{sum(1 for r in res if r.status in ('fehler', 'kein_kurs'))} ohne Ergebnis.")
        df([{"": icons.get(r.status, ""), "ISIN": r.isin, "Zweck": r.purpose, "Status": r.status,
             "Ergebnis": r.message} for r in res])
    return res


def auto_fill_prices(y: int) -> None:
    c = ctx()
    if not c.settings.get("prices.auto_fetch", True) or not price_service().provider.available:
        return
    miss = missing_price_info(y)
    marker = f"prices_auto_{y}_{len(miss['nmf'])}_{len(miss['year_end'])}"
    if (miss["nmf"] or miss["year_end"]) and not st.session_state.get(marker):
        st.session_state[marker] = True
        fill_prices(y)


FIELD_DE = {
    "isin": "ISIN", "trade_date": "Datum", "quantity": "Stückzahl", "price": "Kurs", "amount": "Betrag",
    "fees": "Gebühren", "currency": "Währung", "fx_rate": "Devisenkurs", "withholding_tax": "Quellensteuer",
    "withholding_country": "Quellenstaat", "kest_at_eur": "KESt", "ratio": "Split-Verhältnis", "depot_id": "Depot",
    "tx_type": "Buchungsart", "report_date": "Meldedatum", "age_per_unit": "AgE je Anteil", "name": "Name",
    "tax_class_source": "Quelle der Einstufung", "fund_status_source": "Quelle des Meldefondsstatus",
}
MSG_DE = [
    (r"^Value error, ", ""), (r"^Field required$", "fehlt"), (r"Input should be greater than 0", "muss größer als 0 sein"),
    (r"Input should be a valid date.*", "ist kein gültiges Datum"), (r"Input should be a valid number.*",
                                                                      "ist keine gültige Zahl"),
    (r"String should have at most (\d+) characters", r"darf höchstens \1 Zeichen haben"),
]


def form_error(exc: Exception) -> None:
    """Zeigt Validierungsfehler verständlich: je Feld eine Zeile auf Deutsch."""
    import re

    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        st.error(f"Eingabe nicht übernommen: {exc}")
        return
    lines = []
    for e in exc.errors():
        msg = str(e.get("msg", ""))
        for rx, repl in MSG_DE:
            msg = re.sub(rx, repl, msg)
        loc = [str(x) for x in e.get("loc", ()) if str(x) not in ("__root__",)]
        field = FIELD_DE.get(loc[-1], loc[-1]) if loc else ""
        lines.append(f"- **{field}:** {msg}" if field else f"- {msg}")
    st.error("Bitte korrigieren:\n" + "\n".join(lines))


def document_analysis_options() -> dict:
    """Keep network policy in the UI; the parser itself is offline unless explicitly configured."""
    from ..fx import FxService
    c = ctx()
    return {"fx_service": FxService(c.store.base),
            "allow_download": bool(c.settings.get("fx.auto_fetch", True)),
            "ocr_enabled": bool(c.settings.get("pdf.ocr_enabled", False))}


def process_documents(repo, doc_ids=None, default_depot=None, reextract=False):
    from ..processing import process_documents as process
    return process(repo, doc_ids, default_depot, reextract=reextract, **document_analysis_options())
