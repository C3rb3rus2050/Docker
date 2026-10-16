"""Seite Import: CSV/Excel, PDF-Abrechnungen, OeKB-Daten, Ordnerimport."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ..importers.csv_importer import (
    TARGET_FIELDS,
    ImportError_,
    ImportOptions,
    auto_mapping,
    build_preview,
    commit_preview,
    preview_frame,
    read_table,
)
from ..importers.oekb_importer import (
    FUND_FIELDS,
    commit_fund_previews,
    extract_fund_pdf,
    get_provider,
    preview_fund_table,
    read_fund_table,
)
from ..importers.parsing import parse_tx_type
from ..importers.pdf_importer import PdfError, extract_pdf
from ..models import DOC_SOURCES, FundReportIn, ReviewStatus, TransactionIn, TxType
from ..storage import sha256_bytes
from . import common as C

NONE = "— nicht zugeordnet —"
IMPORT_TYPES = ["CSV/Excel – Transaktionen", "PDF – Abrechnungen (Kauf/Verkauf/Dividende/…)",
                "PDF – Jahressteuerbescheinigung/sonstige Belege", "OeKB – Fondsdaten (CSV/Excel)",
                "OeKB – Fondsmeldung (PDF)", "Serverordner einlesen (optional)"]


def _check_upload(name: str, data: bytes) -> str | None:
    c = C.ctx()
    ext = Path(name).suffix.lower()
    if ext not in c.settings.get("import.allowed_extensions", []):
        return f"Dateityp {ext} nicht erlaubt"
    if len(data) > int(c.settings.get("import.max_upload_mb", 50)) * 1024 * 1024:
        return "Datei ist zu groß"
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        return "Datei ist keine gültige PDF-Datei"
    if ext in (".xlsx",) and not data.startswith(b"PK"):
        return "Datei ist keine gültige Excel-Datei"
    return None


def _source_for_depot(depot_id: int | None) -> str:
    if not depot_id:
        return "Unclassified"
    d = C.ctx().repo.depot(depot_id)
    return d["broker_key"] if d and d["broker_key"] in DOC_SOURCES else "Other"


def render() -> None:
    c = C.ctx()
    y = C.year_selector()
    st.title("Dokumente importieren")
    from .guide import upload_box
    upload_box(y, "import_page", expanded=True)
    st.caption("Format, Spalten und eindeutige Depots werden automatisch erkannt. "
               "Originale bleiben erhalten; identische Dateien und Buchungen werden erkannt.")
    C.link("dashboard", "Zur Übersicht")
    with st.expander("Manuelle Sonderimporte und Serverordner (optional)"):
        kind = st.selectbox("Erweiterte Importart", IMPORT_TYPES)
        deps = C.depot_options()
        if kind.startswith("CSV") and not deps:
            st.warning("Bitte zuerst unter **Broker & Depots** ein Depot anlegen.")
            return
        if kind.startswith("CSV"):
            _csv_import(y, deps)
        elif kind.startswith("PDF – Abr"):
            _pdf_import(y, deps)
        elif kind.startswith("PDF – Jahres"):
            _doc_only_import(y)
        elif kind.startswith("OeKB – Fondsdaten"):
            _oekb_csv(y)
        elif kind.startswith("OeKB – Fondsmeldung"):
            _oekb_pdf(y)
        else:
            _folder_import(y, deps)
    st.divider()
    st.subheader("Fehler- und Importprotokoll")
    runs = c.repo.import_runs(20)
    if runs:
        rid = st.selectbox("Importlauf", [f"#{r['id']} {r['import_type']} {r['started_at']} – {r['status']}"
                                          for r in runs], key="imp_log_sel")
        run_id = int(rid.split()[0][1:])
        C.df(c.repo.import_log(run_id))


# --------------------------------------------------------------------------- #
def _csv_import(y: int, deps: dict) -> None:
    c = C.ctx()
    repo = c.repo
    depot_label = st.selectbox("Depot", list(deps), key="csv_depot")
    depot_id = deps[depot_label]
    up = st.file_uploader("CSV-, TXT- oder Excel-Datei", type=["csv", "txt", "xlsx", "xls"], key="csv_up")
    if not up:
        return
    data = up.getvalue()
    err = _check_upload(up.name, data)
    if err:
        st.error(err)
        return
    existing = repo.find_document_by_hash(sha256_bytes(data))
    if existing:
        st.warning(f"Diese Datei wurde bereits am {existing['imported_at']} importiert (Dokument #{existing['id']}). "
                   "Buchungen werden als Dubletten erkannt.")
    try:
        df, meta = read_table(data, up.name)
    except ImportError_ as exc:
        st.error(str(exc))
        return
    st.write(f"Erkannt: {meta} – {len(df)} Zeilen")
    with st.expander("Rohdaten (erste 20 Zeilen)"):
        st.dataframe(df.head(20), width="stretch")
    profiles = repo.csv_profiles()
    prof_names = ["(automatisch)"] + [p["name"] for p in profiles]
    prof = st.selectbox("Spaltenzuordnungsprofil", prof_names)
    auto = auto_mapping(list(df.columns))
    opts_saved: dict = {}
    if prof != "(automatisch)":
        p = next(p for p in profiles if p["name"] == prof)
        auto = {k: (v if v in df.columns else None) for k, v in p["mapping"].items()}
        opts_saved = p["options"]
    st.subheader("Spaltenzuordnung")
    st.caption("Pflichtfelder: Datum, Buchungsart (oder Standard-Art), Betrag (oder Stück × Kurs).")
    cols = [NONE] + list(df.columns)
    mapping = {}
    grid = st.columns(3)
    for i, (target, (label, req, _)) in enumerate(TARGET_FIELDS.items()):
        cur = auto.get(target)
        mapping[target] = grid[i % 3].selectbox(f"{label}{' *' if req else ''}", cols,
                                                 index=cols.index(cur) if cur in cols else 0, key=f"map_{target}")
    mapping = {k: (None if v == NONE else v) for k, v in mapping.items()}
    st.subheader("Optionen")
    o = st.columns(4)
    dec = o[0].selectbox("Dezimaltrennzeichen", ["auto", ",", "."],
                         index=["auto", ",", "."].index(opts_saved.get("decimal",
                                                                       c.settings.get("import.decimal_separator"))))
    date_fmts = ["automatisch"] + c.settings.get("import.date_formats", [])
    dfmt = o[1].selectbox("Datumsformat", date_fmts)
    amount_is = o[2].selectbox("Betrag ist", ["brutto", "netto"],
                               help="netto: Betrag enthält bereits Gebühren/Steuern; brutto wird zurückgerechnet")
    cur = o[3].selectbox("Standardwährung", c.settings.currencies)
    default_type = st.selectbox("Standard-Buchungsart (falls keine Typspalte)", ["—"] + [t.value for t in TxType])
    type_map: dict[str, str] = dict(opts_saved.get("type_value_map", {}))
    if mapping.get("tx_type"):
        raw_types = sorted({str(v).strip() for v in df[mapping["tx_type"]].tolist() if str(v).strip()})
        unknown = [t for t in raw_types if parse_tx_type(t) is None and t not in type_map]
        if unknown:
            st.warning(f"{len(unknown)} unbekannte Buchungsart(en) – bitte zuordnen oder Zeilen werden als Fehler "
                       "markiert.")
            ed = st.data_editor(pd.DataFrame({"Wert in Datei": unknown, "Buchungsart": [None] * len(unknown)}),
                                column_config={"Buchungsart": st.column_config.SelectboxColumn(
                                    options=[t.value for t in TxType])}, hide_index=True, key="typemap")
            for _, r in ed.iterrows():
                if r["Buchungsart"]:
                    type_map[r["Wert in Datei"]] = r["Buchungsart"]
    options = ImportOptions(decimal=dec, date_format=None if dfmt == "automatisch" else dfmt,
                            date_candidates=c.settings.get("import.date_formats"), default_currency=cur,
                            default_tx_type=None if default_type == "—" else default_type, amount_is=amount_is,
                            type_value_map=type_map)
    try:
        rows = build_preview(df, mapping, options, depot_id, repo,
                             fuzzy_days=int(c.settings.get("import.fuzzy_duplicate_days", 3)))
    except ImportError_ as exc:
        st.error(str(exc))
        return
    frame = preview_frame(rows)
    st.subheader("Vorschau und Dublettenprüfung")
    n_err = sum(1 for r in rows if r.errors)
    n_dup = sum(1 for r in rows if r.duplicate != "neu")
    st.write(f"{len(rows)} Zeilen · {n_err} fehlerhaft · {n_dup} mögliche/sichere Dubletten. "
             "Entscheidung je Zeile: **uebernehmen**, **ignorieren** oder **pruefen** (übernehmen mit Prüfkennzeichen).")
    edited = st.data_editor(frame, hide_index=True, width="stretch", disabled=[c_ for c_ in frame.columns
                                                                               if c_ != "Entscheidung"],
                            column_config={"Entscheidung": st.column_config.SelectboxColumn(
                                options=["uebernehmen", "ignorieren", "pruefen"])}, key="csv_preview")
    doc_year = st.number_input("Steuerjahr für die Ablage der Datei", 2000, 2100, value=y)
    save_prof = st.text_input("Zuordnung als Profil speichern (Name, optional)")
    if st.button("Import bestätigen", type="primary"):
        decisions = {int(r["Zeile"]): r["Entscheidung"] for _, r in edited.iterrows()}
        doc, new = repo.add_document(data, up.name, doc_type="Transaktionsexport (Excel)" if up.name.lower().endswith(
            ("xlsx", "xls")) else "Transaktionsexport (CSV)", source=_source_for_depot(depot_id),
            tax_year=int(doc_year), import_method="csv-import", broker_id=repo.depot(depot_id)["broker_id"])
        res = commit_preview(repo, rows, decisions, import_type="CSV/Excel", depot_id=depot_id,
                             document_id=doc["id"])
        if save_prof.strip():
            repo.save_csv_profile(save_prof.strip(), mapping, {"decimal": dec, "type_value_map": type_map})
        C.invalidate_results()
        st.success(f"Importlauf #{res['run_id']}: {res['rows_imported']} übernommen, {res['rows_skipped']} ignoriert, "
                   f"{res['rows_errors']} fehlerhaft, {res['rows_duplicates']} Dublettenverdacht.")
        C.auto_fill_fx()


# --------------------------------------------------------------------------- #
def pdf_review_form(doc: dict, extraction: dict, depot_id: int | None, key: str,
                    transaction: dict | None = None) -> None:
    """Edit the booking beside its original, including previously missing parser fields."""
    from ..document_review import save_review
    from ..processing import resolve_depot
    from ..importers.pdf_importer import FIELD_LABELS
    repo = C.ctx().repo
    fields = extraction.get('fields', {})

    def value(name, default=None):
        if transaction is not None:
            return transaction.get(name, default)
        return fields.get(name, {}).get('value', default)

    def day(name):
        raw = value(name)
        return date.fromisoformat(raw) if isinstance(raw, str) and raw else raw

    with st.expander('Erkennung und Prüfhinweise', expanded=False):
        from .guide import show_check_report
        show_check_report(extraction.get('checks', []))
        C.df([{'Angabe': FIELD_LABELS.get(name, name), 'Wert': str(field.get('value', '')),
               'Quelle': field.get('source', ''), 'Sicherheit': f"{field.get('confidence', 0):.0%}"}
              for name, field in fields.items()])
        if extraction.get('text_excerpt'):
            st.text(extraction['text_excerpt'])
    if not extraction.get('creates_transaction', True) and transaction is None:
        st.info(f"Erkannt: {extraction.get('doc_type', 'Unbekannt')}. Keine bestätigte Einzelabrechnung.")
        if not st.checkbox('Im Original liegt doch eine einzelne Buchung vor – manuell erfassen', key=f'{key}_override'):
            return
    deps = C.depot_options()
    if not deps:
        st.warning('Für die Übernahme zuerst ein Depot anlegen.')
        return
    broker = extraction.get('broker')
    if broker not in ('TradeRepublic', 'ScalableCapital'):
        broker = doc.get('source')
    selected = transaction.get('depot_id') if transaction else resolve_depot(repo, doc, broker, depot_id)
    if selected is None and len(deps) == 1 and broker not in ('TradeRepublic', 'ScalableCapital') and not doc.get('broker_id'):
        selected = next(iter(deps.values()))
    labels = ['— Depot zuordnen —'] + list(deps)
    index = next((i for i, name in enumerate(labels) if deps.get(name) == selected), 0)
    # Widget keys preserve the draft even when another control reruns the page.
    with st.container():
        a, b = st.columns(2)
        dep = a.selectbox('Depot', labels, index=index, key=f'{key}_depot')
        types = ['— Buchungsart bestimmen —'] + [t.value for t in TxType]
        current_type = transaction['tx_type'] if transaction else extraction.get('tx_type')
        typ = b.selectbox('Buchungsart', types, index=types.index(current_type) if current_type in types else 0,
                         key=f'{key}_type')
        a, b = st.columns(2)
        trade_day = a.date_input('Buchungsdatum', value=day('trade_date'), format='DD.MM.YYYY', key=f'{key}_date')
        isin = b.text_input('ISIN', value=value('isin', '') or '', key=f'{key}_isin')
        name = st.text_input('Wertpapiername', value=value('security_name', '') or '', key=f'{key}_name')
        a, b, c = st.columns(3)
        qty = a.number_input('Stückzahl', min_value=0.0, value=value('quantity'), format='%.6f', key=f'{key}_quantity')
        gross = b.number_input('Bruttobetrag', min_value=0.0, value=value('amount'), format='%.2f', key=f'{key}_amount')
        currencies = list(dict.fromkeys(C.ctx().settings.currencies + ([value('currency')] if value('currency') else [])))
        currency_options = ['— Währung —'] + currencies
        currency = c.selectbox('Währung', currency_options,
            index=currency_options.index(value('currency')) if value('currency') in currencies else 0, key=f'{key}_currency')
        a, b = st.columns(2)
        wht = a.number_input('Quellensteuer', min_value=0.0, value=float(value('withholding_tax', 0) or 0), format='%.2f', key=f'{key}_wht')
        country = b.text_input('Quellenstaat', value=value('withholding_country', '') or '', max_chars=2, key=f'{key}_country')
        # Always visible: foreign-currency corrections need no extra view or rerun.
        a, b = st.columns(2)
        fx = a.number_input('Devisenkurs (Währung je EUR)', min_value=0.0, value=value('fx_rate'), format='%.6f', key=f'{key}_fx')
        fees = b.number_input('Gebühren', min_value=0.0, value=float(value('fees', 0) or 0), format='%.2f', key=f'{key}_fees')
        with st.expander('Weitere Angaben'):
            a, b = st.columns(2)
            price = a.number_input('Stückkurs', min_value=0.0, value=value('price'), format='%.6f', key=f'{key}_price')
            kest = b.number_input('Österreichische KESt (EUR)', min_value=0.0, value=float(value('kest_at_eur', 0) or 0), format='%.2f', key=f'{key}_kest')
            a, b = st.columns(2)
            valuta = a.date_input('Valuta', value=day('value_date'), format='DD.MM.YYYY', key=f'{key}_valuta')
            ratio = b.number_input('Split-Verhältnis neu/alt', min_value=0.0, value=value('ratio'), format='%.6f', key=f'{key}_ratio')
            order = st.number_input('Reihenfolge am Tag', min_value=1, value=value('execution_order'), step=1, key=f'{key}_order')
            separate = st.checkbox('Mögliche Dubletten verglichen: dies ist eine eigenständige Buchung', key=f'{key}_duplicate')
        reason = st.text_input('Prüfnotiz' + (' / Änderungsgrund (Pflicht)' if transaction else ' (optional)'), key=f'{key}_reason')
        checked = st.checkbox('Ich habe die Werte mit dem Original abgeglichen', key=f'{key}_confirmed')
        save = st.button('Änderungen speichern' if transaction else 'Geprüfte Buchung speichern',
                         key=f'{key}_save', type='primary', use_container_width=True)
    if save:
        try:
            if dep not in deps or typ not in [t.value for t in TxType] or currency not in currencies or trade_day is None:
                raise ValueError('Depot, Buchungsart, Datum und Währung bitte vollständig zuordnen.')
            values = dict(transaction or {})
            values.update(depot_id=deps[dep], tx_type=typ, trade_date=trade_day, isin=isin or None,
                security_name=name or None, quantity=qty, amount=gross, currency=currency, price=price,
                fees=fees, fx_rate=fx or None, fx_source=value('fx_source') if fx == value('fx_rate') else 'manuell geprüft',
                withholding_tax=wht, withholding_country=country or None, kest_at_eur=kest,
                value_date=valuta, ratio=ratio or None, execution_order=order)
            tid = save_review(repo, doc['id'], values, confirmed=checked,
                transaction_id=transaction['id'] if transaction else None, reason=reason,
                duplicate_confirmed=separate)
            C.invalidate_results()
            st.session_state['document_review_saved'] = f"Buchung #{tid} gespeichert und geprüft."
            st.rerun()
        except (ValueError, OSError) as exc:
            C.form_error(exc)


def _store_pdf(data: bytes, name: str, y: int, depot_id: int | None, method: str) -> tuple[dict, dict, bool]:
    from ..processing import store_pdf
    try:
        return store_pdf(C.ctx().repo, data, name, y, method, _source_for_depot(depot_id),
                         C.ctx().settings.get("pdf.engine", "auto"))
    except PdfError as exc:
        st.error(f"„{name}“ ist keine lesbare PDF-Datei ({exc}).")
        raise


def _pdf_import(y: int, deps: dict) -> None:
    """Import only after a deliberate click; rerendering the page never reimports PDFs."""
    from ..processing import extraction_for

    repo = C.ctx().repo
    depot_label = st.selectbox("Depot (falls nicht eindeutig über den Broker bestimmbar)",
                               ["automatisch"] + list(deps), key="pdf_depot")
    default_depot = deps.get(depot_label)
    auto = st.checkbox("Vollständig erkannte Abrechnungen automatisch als Buchung übernehmen", value=True,
                       help="Nur Dokumente ohne Widersprüche. Dublettenverdacht wird zur Prüfung zurückgestellt.")
    ups = st.file_uploader("PDF-Abrechnungen", type=["pdf"], accept_multiple_files=True, key="pdf_up")
    st.caption("Die Texterkennung läuft lokal (pdfplumber/PyMuPDF). Gescannte PDFs ohne Textebene können nicht "
               "ausgelesen werden – Werte dann manuell eintragen. Keine Übertragung an externe Dienste.")

    if ups and st.button(f"{len(ups)} PDF(s) importieren und prüfen", type="primary",
                         key="pdf_import_confirm"):
        ids, errors = [], []
        for up in ups:
            data = up.getvalue()
            err = _check_upload(up.name, data)
            if err:
                errors.append((up.name, err))
                continue
            try:
                doc, _, _ = _store_pdf(data, up.name, y, default_depot, "pdf-upload")
                ids.append(doc["id"])
            except (PdfError, OSError, ValueError) as exc:
                errors.append((up.name, str(exc)))
        st.session_state["pdf_import_ids"] = list(dict.fromkeys(ids))
        st.session_state["pdf_import_errors"] = errors
        st.session_state["pdf_import_results"] = (
            C.process_documents(repo, ids, default_depot) if auto and ids else []
        )
        if auto and ids:
            C.invalidate_results()

    for name, error in st.session_state.get("pdf_import_errors", []):
        st.error(f"„{name}“: {error}")
    results = st.session_state.get("pdf_import_results", [])
    if results:
        C.show_process_results(results, inline=False)
    ids = st.session_state.get("pdf_import_ids", [])
    from .document_review import document_cards, OPEN
    docs = [repo.document(did) for did in ids]
    docs = [d for d in docs if d and d['status'] in OPEN]
    if docs:
        document_cards(repo, docs, key='pdf_import_direct')


def _doc_only_import(y: int) -> None:
    repo = C.ctx().repo
    ups = st.file_uploader("Belege (PDF/CSV/Excel)", type=["pdf", "csv", "xlsx", "txt"], accept_multiple_files=True)
    cols = st.columns(3)
    source = cols[0].selectbox("Quelle", DOC_SOURCES)
    from ..models import DOC_TYPES
    dtype = cols[1].selectbox("Dokumenttyp", DOC_TYPES, index=DOC_TYPES.index("Jahressteuerbescheinigung"))
    doc_year = cols[2].number_input("Steuerjahr", 2000, 2100, value=y)
    if ups and st.button("Ablegen"):
        for up in ups:
            data = up.getvalue()
            err = _check_upload(up.name, data)
            if err:
                st.error(f"{up.name}: {err}")
                continue
            doc, new = repo.add_document(data, up.name, doc_type=dtype, source=source, tax_year=int(doc_year),
                                         import_method="beleg-upload", status="pruefen")
            st.write(f"{'✅ abgelegt' if new else 'ℹ️ bereits vorhanden'}: {up.name} → `{doc['stored_path']}`")
        st.info("Werte aus Jahressteuerbescheinigungen bitte manuell abgleichen; die Bescheinigung kann auf der Seite "
                "Dokumente Buchungen als Beleg zugeordnet werden.")


# --------------------------------------------------------------------------- #
def _oekb_csv(y: int) -> None:
    repo = C.ctx().repo
    p = get_provider(C.ctx().settings.get("oekb.automatic_provider"))
    st.info(f"Automatischer Abruf: **nicht verfügbar**. {p.reason}")
    up = st.file_uploader("OeKB-Datenexport bzw. Fondsdaten als CSV/Excel", type=["csv", "txt", "xlsx"], key="oekb_up")
    if not up:
        with st.expander("Erwartetes Format (Beispiel)"):
            from ..demo import SAMPLE_OEKB_CSV
            st.code(SAMPLE_OEKB_CSV)
        return
    data = up.getvalue()
    err = _check_upload(up.name, data)
    if err:
        st.error(err)
        return
    df, auto = read_fund_table(data, up.name)
    cols = [NONE] + list(df.columns)
    mapping = {}
    grid = st.columns(3)
    for i, (k, (label, req, _)) in enumerate(FUND_FIELDS.items()):
        cur = auto.get(k)
        mapping[k] = grid[i % 3].selectbox(f"{label}{' *' if req else ''}", cols,
                                           index=cols.index(cur) if cur in cols else 0, key=f"fmap_{k}")
    mapping = {k: (None if v == NONE else v) for k, v in mapping.items()}
    try:
        prev = preview_fund_table(df, mapping)
    except ValueError as exc:
        st.error(str(exc))
        return
    C.df([{"Zeile": p.row_no, "ISIN": p.report.isin if p.report else "", "Meldedatum": p.report.report_date
           if p.report else "", "AgE je Anteil": p.report.age_per_unit if p.report else None,
           "AK-Korrektur": p.report.ak_correction_per_unit if p.report else None,
           "Meldungen": "; ".join(p.errors + p.warnings)} for p in prev])
    if st.button("Fondsdaten importieren", type="primary"):
        doc, _ = repo.add_document(data, up.name, doc_type="OeKB-Fondsmeldung", source="OeKB", tax_year=y,
                                   import_method="oekb-csv")
        res = commit_fund_previews(repo, preview_fund_table(df, mapping, document_id=doc["id"]), doc["id"])
        repo.update_document(doc["id"], status="verarbeitet" if not res["fehler"] else "teilweise")
        C.invalidate_results()
        st.success(f"Neu: {res['neu']}, identisch (übersprungen): {res['identisch']}, Konflikte: {res['konflikt']}, "
                   f"Fehler: {res['fehler']}. Konflikte bitte unter **Fonds & OeKB** entscheiden.")


def _oekb_pdf(y: int) -> None:
    repo = C.ctx().repo
    up = st.file_uploader("OeKB-Fondsmeldung (PDF)", type=["pdf"], key="oekb_pdf")
    if not up:
        return
    data = up.getvalue()
    err = _check_upload(up.name, data)
    if err:
        st.error(err)
        return
    found = extract_fund_pdf(data)
    for w in found["warnings"]:
        st.warning(w)
    if found["missing"]:
        st.error("Nicht gefunden: " + ", ".join(found["missing"]))
    v = found["values"]
    with st.form("oekb_pdf_form"):
        cols = st.columns(3)
        isin = cols[0].text_input("ISIN", v.get("isin", ""))
        rdate = cols[1].date_input("Meldedatum", value=date.fromisoformat(v["report_date"]) if v.get("report_date")
                                   else date(y, 12, 31), format="DD.MM.YYYY")
        fye = cols[2].date_input("Geschäftsjahresende", value=date.fromisoformat(v["fiscal_year_end"])
                                 if v.get("fiscal_year_end") else None, format="DD.MM.YYYY")
        cols = st.columns(5)
        dist = cols[0].number_input("Ausschüttung je Anteil", value=float(v.get("distribution_per_unit") or 0),
                                    format="%.6f")
        age = cols[1].number_input("AgE je Anteil", value=float(v.get("age_per_unit") or 0), format="%.6f")
        cred = cols[2].number_input("Anrechenbare Steuer je Anteil", value=float(v.get("creditable_tax_per_unit") or 0),
                                    format="%.6f")
        akk = cols[3].number_input("AK-Korrektur je Anteil", value=float(v.get("ak_correction_per_unit") or 0),
                                   format="%.6f")
        cur = cols[4].text_input("Währung", v.get("currency", "EUR"))
        fx = st.number_input("Devisenkurs (Währung je EUR, nur bei Fremdwährung)", value=0.0, format="%.6f")
        ok = st.form_submit_button("Meldung speichern (Status: ungeprüft)")
    if ok:
        try:
            rep = FundReportIn(isin=isin, report_date=rdate, fiscal_year_end=fye, distribution_per_unit=dist or None,
                               age_per_unit=age, creditable_tax_per_unit=cred or None, ak_correction_per_unit=akk,
                               currency=cur, fx_rate=fx or None, source="import_pdf")
        except ValidationError as exc:
            C.form_error(exc)
            return
        doc, _ = repo.add_document(data, up.name, doc_type="OeKB-Fondsmeldung", source="OeKB", tax_year=rdate.year,
                                   import_method="oekb-pdf")
        res = repo.add_fund_report(rep.model_copy(update={"document_id": doc["id"]}))
        repo.update_document(doc["id"], status="verarbeitet" if res["status"] != "konflikt" else "pruefen")
        C.invalidate_results()
        st.success(f"Ergebnis: {res['status']} (Meldung #{res['id']})")


# --------------------------------------------------------------------------- #
def _folder_import(y: int, deps: dict) -> None:
    """Explicit, opt-in server-side folder import using the validated upload pipeline."""
    from ..processing import expand_upload, store_uploads

    st.caption("Dieser Import liest Dateien vom Server/Proxmox-LXC, nicht vom Windows-PC. "
               "Für lokale Ordner verwenden Sie oben die Upload-Art »Kompletten Ordner«.")
    if os.getenv("KEST_ALLOW_SERVER_FOLDER_IMPORT") != "1":
        st.info("Serverordner-Import ist aus Sicherheitsgründen deaktiviert. "
                "Administratoren können ihn mit KEST_ALLOW_SERVER_FOLDER_IMPORT=1 aktivieren.")
        return
    repo = C.ctx().repo
    folder = st.text_input("Serverordner", placeholder="/data/importe", key="folder_path")
    recursive = st.checkbox("Unterordner einbeziehen", value=True)
    auto = st.checkbox("Eindeutige Abrechnungen automatisch buchen", value=True)
    dflt = st.selectbox("Standarddepot, falls nicht eindeutig", ["automatisch"] + list(deps),
                        key="folder_depot")
    report = st.session_state.pop("server_folder_report", None)
    if report:
        st.success(f"{report['new']} neue Datei(en), {report['duplicates']} Dublette(n), "
                   f"{len(report['skipped'])} übersprungen.")
        if report["skipped"]:
            with st.expander("Übersprungene Dateien und Gründe"):
                for name, reason in report["skipped"][:200]:
                    st.write(f"**{name}:** {reason}")
    if not folder:
        return
    p = Path(folder).expanduser().resolve()
    if not p.is_dir():
        st.error("Serverordner nicht gefunden.")
        return
    files = sorted((f for f in (p.rglob("*") if recursive else p.glob("*"))
                    if f.is_file() and not f.is_symlink()
                    and f.suffix.lower() in (".pdf", ".csv", ".xlsx", ".txt", ".zip")))
    st.caption(f"{len(files)} unterstützte Datei(en) gefunden.")
    if len(files) > 2000:
        st.error("Mehr als 2.000 Dateien gefunden. Bitte kleinere Ordner auswählen.")
        return
    if files and st.button("Serverordner jetzt importieren", type="primary", key="server_folder_go"):
        max_bytes = int(C.ctx().settings.get("import.max_upload_mb", 50)) * 1024 * 1024
        new_ids, new_count, duplicates, skipped = [], 0, 0, []
        progress = st.progress(0.0)
        for index, file in enumerate(files, 1):
            try:
                if file.stat().st_size > max_bytes:
                    skipped.append((file.name, "Datei ist größer als das Upload-Limit"))
                    continue
                items = expand_upload(file.name, file.read_bytes())
                if not items:
                    skipped.append((file.name, "Keine unterstützten Dateien enthalten"))
                    continue
                result = store_uploads(repo, items, y, method="ordner-import")
                new_ids.extend(result.pdf_ids)
                new_count += len(result.pdf_ids) + len(result.csv_docs)
                duplicates += result.duplicates
                skipped.extend(result.skipped)
            except (OSError, ValueError) as exc:
                skipped.append((file.name, str(exc)))
            finally:
                progress.progress(index / len(files))
        st.session_state["server_folder_report"] = {
            "new": new_count, "duplicates": duplicates, "skipped": skipped}
        if auto and new_ids:
            C.after_processing(C.process_documents(repo, new_ids, deps.get(dflt)))
        else:
            st.rerun()

