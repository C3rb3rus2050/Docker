"""Seiten: Wertpapiere, Fonds & OeKB, Transaktionen, Dokumente."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ..importers.oekb_importer import get_provider
from ..models import (
    DOC_SOURCES,
    DOC_STATUS,
    DOC_TYPES,
    TAX_CLASS_LABELS,
    FundReportIn,
    FundStatus,
    IncomeCategory,
    ReviewStatus,
    SecurityIn,
    SecurityType,
    TaxClass,
    TransactionIn,
    TxType,
)
from . import common as C
from .record_tables import record_grid, document_grid, document_preview


# --------------------------------------------------------------------------- #
TC_LABEL = {TaxClass.KAPITALGESELLSCHAFT.value: "Aktie/Kapitalgesellschaft", TaxClass.INVESTMENTFONDS.value:
            "Investmentfonds", TaxClass.IMMOBILIENFONDS.value: "Immobilienfonds (manuell)",
            TaxClass.FORDERUNGSWERTPAPIER.value: "Anleihe", TaxClass.DERIVAT.value: "Derivat/Zertifikat (manuell)",
            TaxClass.SONSTIGE.value: "Sonstige (manuell)", TaxClass.UNGEKLAERT.value: "ungeklärt"}
FS_LABEL = {FundStatus.NO_FUND.value: "kein Fonds", FundStatus.MELDEFONDS.value: "Meldefonds",
            FundStatus.NICHTMELDEFONDS.value: "Nichtmeldefonds", FundStatus.UNKNOWN.value: "unbekannt"}
TC_VALUE = {v: k for k, v in TC_LABEL.items()}
FS_VALUE = {v: k for k, v in FS_LABEL.items()}


def _suggest_type(name: str | None) -> str:
    """Nur ein Vorschlag für die Wertpapierart (nicht für die steuerliche Einstufung)."""
    n = (name or "").lower()
    if any(k in n for k in ("etf", "ucits", "ishares", "xtrackers", "vanguard", "amundi", "lyxor", "spdr")):
        return SecurityType.ETF_ACC.value if any(k in n for k in ("acc", "thes")) else SecurityType.ETF_DIST.value \
            if any(k in n for k in ("dist", "aussch")) else SecurityType.ETF_ACC.value
    if "reit" in n or "realty" in n:
        return SecurityType.REIT.value
    return SecurityType.STOCK.value


def _bulk_classify(repo) -> None:
    open_secs = repo.db.query(
        "SELECT * FROM securities WHERE isin IS NOT NULL AND (tax_class_verified=0 OR security_type='Sonstige' OR "
        "(security_type IN ('ETF ausschüttend','ETF thesaurierend','Investmentfonds (AT)','Investmentfonds (Ausland)')"
        " AND fund_status IN ('unbekannt','kein_fonds'))) ORDER BY name")
    if not open_secs:
        st.success("Alle Wertpapiere sind vollständig eingestuft.")
        return
    with st.container(border=True):
        st.subheader(f"Offene Wertpapiere ergänzen ({len(open_secs)})")
        st.caption("Vorschläge (Art aus dem Namen, Sitzstaat aus dem ISIN-Länderkürzel) sind nur Hilfen. Eine Zeile "
                   "gilt erst als **geprüft**, wenn Sie eine **Quelle** eintragen (z. B. „Factsheet“, „my.oekb.at "
                   "Abfrage 03/2025“, „Jahressteuerbescheinigung“). REITs/BDCs werden nie automatisch eingestuft.")
        rows = []
        for sec in open_secs:
            stype = sec["security_type"] if sec["security_type"] != "Sonstige" else _suggest_type(sec["name"])
            is_fund = stype in [t.value for t in (SecurityType.ETF_ACC, SecurityType.ETF_DIST, SecurityType.FUND_AT,
                                                  SecurityType.FUND_FOREIGN)]
            tc = sec["tax_class"]
            if tc == TaxClass.UNGEKLAERT.value and stype != SecurityType.REIT.value and stype != SecurityType.BDC.value:
                tc = TaxClass.INVESTMENTFONDS.value if is_fund else TaxClass.KAPITALGESELLSCHAFT.value
            fs = sec["fund_status"]
            if is_fund and fs == FundStatus.NO_FUND.value:
                fs = FundStatus.UNKNOWN.value
            rows.append({"ISIN": sec["isin"], "Name": sec["name"] or "", "Wertpapierart": stype,
                         "Steuerliche Einstufung": TC_LABEL[tc], "Meldefondsstatus": FS_LABEL[fs],
                         "Sitzstaat": sec["country"] or sec["isin"][:2], "Quelle (Pflicht für „geprüft“)":
                             sec["tax_class_source"] or ""})
        edited = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch", key="bulk_sec",
                                column_config={
                                    "ISIN": st.column_config.TextColumn(disabled=True),
                                    "Wertpapierart": st.column_config.SelectboxColumn(
                                        options=[t.value for t in SecurityType], required=True),
                                    "Steuerliche Einstufung": st.column_config.SelectboxColumn(
                                        options=list(TC_LABEL.values()), required=True),
                                    "Meldefondsstatus": st.column_config.SelectboxColumn(
                                        options=list(FS_LABEL.values()), required=True),
                                    "Sitzstaat": st.column_config.TextColumn(max_chars=2),
                                })
        if st.button("Alle Änderungen speichern", type="primary"):
            saved, problems = 0, []
            for _, r in edited.iterrows():
                src = str(r["Quelle (Pflicht für „geprüft“)"] or "").strip()
                try:
                    repo.upsert_security(SecurityIn(
                        isin=r["ISIN"], name=r["Name"] or None, country=(r["Sitzstaat"] or "").upper() or None,
                        security_type=SecurityType(r["Wertpapierart"]),
                        tax_class=TaxClass(TC_VALUE[r["Steuerliche Einstufung"]]),
                        tax_class_source=src or None, tax_class_verified=bool(src),
                        fund_status=FundStatus(FS_VALUE[r["Meldefondsstatus"]]), fund_status_source=src or None,
                        fund_status_verified=bool(src) and FS_VALUE[r["Meldefondsstatus"]] != FundStatus.UNKNOWN.value),
                        reason="Tabelle „Offene Wertpapiere ergänzen“")
                    saved += 1
                except ValidationError as exc:
                    problems.append((r["ISIN"], exc))
            C.invalidate_results()
            st.success(f"{saved} Wertpapier(e) gespeichert. Ohne Quelle bleiben sie als „ungeprüft“ markiert.")
            for isin, exc in problems:
                st.markdown(f"**{isin}:**")
                C.form_error(exc)


def securities() -> None:
    repo = C.ctx().repo
    C.year_selector()
    st.title("Wertpapiere")
    st.caption("Wertpapierart und steuerliche Einstufung sind getrennte Felder. Eine Einstufung gilt nur als geprüft, "
               "wenn eine belastbare Quelle angegeben ist (z. B. Emittentenangabe, OeKB-Meldung, Steuerbescheinigung). "
               "Die Einstufung wird nie aus Ticker, Name oder der Bezeichnung REIT/BDC abgeleitet.")
    _bulk_classify(repo)
    st.subheader("Alle Wertpapiere")
    q = st.text_input("Suche (ISIN, Name, Ticker, WKN)")
    rows = repo.securities(q or None)
    C.df([{"ISIN": s["isin"], "Name": s["name"] or "", "Art": s["security_type"],
           "Steuerliche Einstufung": TC_LABEL.get(s["tax_class"], s["tax_class"]),
           "Einstufung geprüft": "✅" if s["tax_class_verified"] else "–",
           "Meldefondsstatus": FS_LABEL.get(s["fund_status"], s["fund_status"]),
           "Quelle": s["tax_class_source"] or "", "Sitzstaat": s["country"] or "",
           "Ticker": s["ticker"] or ""} for s in rows])
    isins = ["(neues Wertpapier)"] + [s["isin"] for s in rows]
    sel = st.selectbox("Bearbeiten", isins)
    cur = repo.security_by_isin(sel) if sel != "(neues Wertpapier)" else {}
    cur = cur or {}
    with st.form("sec_form"):
        cols = st.columns(4)
        isin = cols[0].text_input("ISIN", cur.get("isin", ""), disabled=bool(cur))
        name = cols[1].text_input("Name", cur.get("name") or "")
        ticker = cols[2].text_input("Ticker", cur.get("ticker") or "")
        wkn = cols[3].text_input("WKN", cur.get("wkn") or "")
        cols = st.columns(3)
        stypes = [t.value for t in SecurityType]
        stype = cols[0].selectbox("Wertpapierart", stypes, index=stypes.index(cur.get("security_type", "Sonstige")))
        country = cols[1].text_input("Sitzstaat Emittent (ISO-2, für Quellensteuer)", cur.get("country") or "",
                                     max_chars=2)
        currency = cols[2].text_input("Handelswährung", cur.get("currency") or "")
        st.markdown("**Steuerliche Einstufung**")
        cols = st.columns(3)
        tcs = [t.value for t in TaxClass]
        tc = cols[0].selectbox("Einstufung", tcs, index=tcs.index(cur.get("tax_class", "ungeklaert")),
                               format_func=lambda v: TAX_CLASS_LABELS[TaxClass(v)])
        tc_src = cols[1].text_input("Quelle der Einstufung", cur.get("tax_class_source") or "")
        tc_ver = cols[2].checkbox("Einstufung geprüft", bool(cur.get("tax_class_verified")))
        cols = st.columns(3)
        fss = [f.value for f in FundStatus]
        fs = cols[0].selectbox("Meldefondsstatus", fss, index=fss.index(cur.get("fund_status", "kein_fonds")),
                               format_func=lambda v: FS_LABEL.get(v, v))
        fs_src = cols[1].text_input("Quelle Meldefondsstatus (z. B. OeKB-Suche vom …)", cur.get("fund_status_source")
                                    or "")
        fs_ver = cols[2].checkbox("Status geprüft", bool(cur.get("fund_status_verified")))
        psym = st.text_input("Kurssymbol beim Kursdienst (leer = automatisch per ISIN, z. B. EUNL.XETRA)",
                             cur.get("price_symbol") or "")
        notes = st.text_area("Notizen", cur.get("notes") or "")
        review = st.selectbox("Prüfstatus", ["ungeprueft", "geprueft", "pruefen"],
                              index=["ungeprueft", "geprueft", "pruefen"].index(cur.get("review_status", "ungeprueft")))
        if st.form_submit_button("Speichern"):
            try:
                sec = SecurityIn(isin=cur.get("isin") or isin, name=name or None, ticker=ticker or None,
                                 wkn=wkn or None, currency=currency or None, country=country.upper() or None,
                                 security_type=SecurityType(stype), tax_class=TaxClass(tc),
                                 tax_class_source=tc_src or None, tax_class_verified=tc_ver,
                                 fund_status=FundStatus(fs), fund_status_source=fs_src or None,
                                 fund_status_verified=fs_ver, notes=notes or None)
                repo.upsert_security(sec, reason="manuelle Pflege")
                if (psym or None) != cur.get("price_symbol"):
                    repo.db.execute("UPDATE securities SET price_symbol=? WHERE isin=?", (psym.strip() or None, sec.isin))
                    repo.audit("security", sec.isin, "Kurssymbol gesetzt", {"symbol": psym.strip() or None})
                repo.set_security_review(sec.isin, review)
                C.invalidate_results()
                st.success("Gespeichert")
                st.rerun()
            except ValidationError as exc:
                C.form_error(exc)
    if cur:
        with st.expander("Änderungshistorie"):
            C.df([a for a in repo.audit_entries() if a["entity"] == "security" and a["entity_id"] == cur["isin"]])


# --------------------------------------------------------------------------- #
def funds() -> None:
    repo = C.ctx().repo
    y = C.year_selector()
    st.title("Fonds & OeKB")
    p = get_provider(C.ctx().settings.get("oekb.automatic_provider"))
    with st.expander('Hinweis zum Online-Abruf'):
        st.info(p.reason)
    st.caption("OeKB-Dateien werden im gemeinsamen Upload automatisch erkannt. Hier können Sie Meldungen direkt bearbeiten. Abweichende "
               "Werte erzeugen einen Konflikt – nichts wird stillschweigend überschrieben.")
    tabs = st.tabs(["Meldungen", "Konflikte", "Meldung erfassen", f"Nichtmeldefonds-Kurse {y}"])
    with tabs[0]:
        reps = repo.fund_reports()
        query = st.text_input("Fondsmeldungen durchsuchen", key="fund_search")
        active = st.checkbox("Nur aktive Meldungen", value=True, key="fund_active")
        visible = [r for r in reps if (not active or r['active']) and
                   (not query or query.lower() in str(r.get('fund_name', '')).lower() or query.upper() in r['isin'])]
        record_grid(repo, visible, 'fund', 'fund_grid')
    with tabs[1]:
        open_c = repo.conflicts("offen")
        C.df(open_c)
        fr = [c for c in open_c if c["entity"] == "fund_report"]
        pairs = sorted({(int(c["existing_ref"].split(":")[1].split()[0]), int(c["new_ref"].split(":")[1].split()[0]))
                        for c in fr})
        for ex_id, new_id in pairs:
            with st.form(f"conf_{ex_id}_{new_id}"):
                st.write(f"Meldung #{ex_id} (bestehend) ↔ #{new_id} (neu)")
                C.df([{k: v for k, v in c.items() if k in ("field", "existing_value", "new_value")} for c in fr
                      if c["existing_ref"].startswith(f"fund_reports:{ex_id} ") and
                      c["new_ref"].startswith(f"fund_reports:{new_id} ")])
                dec = st.radio("Entscheidung", ["bestehend_behalten", "neu_uebernommen"], horizontal=True)
                note = st.text_input("Begründung (Pflicht)")
                if st.form_submit_button("Entscheiden"):
                    try:
                        repo.resolve_fund_report_conflict(ex_id, new_id, dec, note)
                        C.invalidate_results()
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        for c in [c for c in open_c if c["entity"] == "nmf_price"]:
            with st.form(f"nmfc_{c['id']}"):
                st.write(f"Kursdaten {c['entity_key']} Feld {c['field']}: {c['existing_value']} ↔ {c['new_value']}")
                take = st.radio("Wert", ["bestehend behalten", "neu übernehmen"], horizontal=True)
                note = st.text_input("Begründung (Pflicht)")
                if st.form_submit_button("Entscheiden"):
                    try:
                        repo.resolve_nmf_conflict(c["id"], take == "neu übernehmen", note)
                        C.invalidate_results()
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    with tabs[2]:
        with st.form("fr_manual"):
            cols = st.columns(4)
            isin = cols[0].text_input("ISIN")
            rtype = cols[1].selectbox("Meldungsart", ["Jahresmeldung", "Ausschuettungsmeldung"])
            rdate = cols[2].date_input("Meldedatum", value=date(y, 6, 30), format="DD.MM.YYYY")
            fye = cols[3].date_input("Geschäftsjahresende", value=None, format="DD.MM.YYYY")
            cols = st.columns(6)
            dist = cols[0].number_input("Ausschüttung/Anteil", value=0.0, format="%.6f")
            ddate = cols[1].date_input("Ex-Tag", value=None, format="DD.MM.YYYY")
            taxable = cols[2].number_input("steuerpfl. Ausschüttung/Anteil", value=0.0, format="%.6f")
            age = cols[3].number_input("AgE/Anteil", value=0.0, format="%.6f")
            akk = cols[4].number_input("AK-Korrektur/Anteil", value=0.0, format="%.6f")
            cred = cols[5].number_input("anrechenb. Steuer/Anteil", value=0.0, format="%.6f")
            cols = st.columns(3)
            cur = cols[0].text_input("Währung", "EUR")
            fx = cols[1].number_input("Devisenkurs (Währung je EUR)", value=0.0, format="%.6f")
            src_note = cols[2].text_input("Quelle (z. B. my.oekb.at Abfrage vom …)")
            if st.form_submit_button("Speichern"):
                try:
                    rep = FundReportIn(isin=isin, report_type=rtype, report_date=rdate, fiscal_year_end=fye,
                                       distribution_date=ddate, distribution_per_unit=dist or None,
                                       taxable_distribution_per_unit=taxable if dist else None, age_per_unit=age,
                                       ak_correction_per_unit=akk, creditable_tax_per_unit=cred or None, currency=cur,
                                       fx_rate=fx or None, source="manuell", notes=src_note or None)
                    res = repo.add_fund_report(rep)
                    C.invalidate_results()
                    st.success(f"Ergebnis: {res['status']} (Meldung #{res['id']})")
                except ValidationError as exc:
                    C.form_error(exc)
    with tabs[3]:
        st.caption("Für die Pauschalbesteuerung von Nichtmeldefonds: erster und letzter Rücknahmepreis des "
                   "Kalenderjahres. Ob die Regel für das Jahr verifiziert ist, zeigt die Steuerberechnung.")
        C.df(repo.nmf_prices(y))
        if st.button(f"Rücknahmepreise/Kurse {y} automatisch laden"):
            C.fill_prices(y)
        with st.form("nmf_form"):
            cols = st.columns(4)
            isin = cols[0].text_input("ISIN")
            fp = cols[1].number_input("Erster Rücknahmepreis", value=0.0, format="%.4f")
            fd = cols[2].date_input("Datum erster Preis", value=date(y, 1, 2), format="DD.MM.YYYY")
            cur = cols[3].text_input("Währung", "EUR")
            cols = st.columns(4)
            lp = cols[0].number_input("Letzter Rücknahmepreis", value=0.0, format="%.4f")
            ld = cols[1].date_input("Datum letzter Preis", value=date(y, 12, 31), format="DD.MM.YYYY")
            fx = cols[2].number_input("Devisenkurs 31.12. (Währung je EUR)", value=0.0, format="%.6f")
            src = cols[3].text_input("Quelle")
            if st.form_submit_button("Speichern"):
                from ..models import normalize_isin
                res = repo.upsert_nmf_price(normalize_isin(isin), y, fp or None, fd.isoformat(), lp or None,
                                            ld.isoformat(), cur.upper(), fx or None, src or "manuell")
                C.invalidate_results()
                st.success(f"Ergebnis: {res['status']}")


# --------------------------------------------------------------------------- #
def transactions() -> None:
    c = C.ctx()
    repo = c.repo
    y = C.year_selector()
    st.title("Transaktionen")
    n_fx = C.missing_fx_count()
    if n_fx and st.button(f"Devisenkurse für {n_fx} Fremdwährungsbuchung(en) von der EZB ergänzen"):
        C.fill_fx(None, allow_download=True)
    deps = C.depot_options()
    cols = st.columns(3)
    only_year = cols[0].checkbox(f"Nur {y}", value=True)
    depot_f = cols[1].selectbox("Depot", ["alle"] + list(deps))
    isin_f = cols[2].text_input("ISIN-Filter")
    rows = repo.transactions(y if only_year else None, deps.get(depot_f), isin_f.strip().upper() or None)
    selected_transactions = record_grid(repo, rows, 'transaction', 'tx_grid')
    if not deps:
        st.warning("Kein Depot vorhanden.")
        return
    with st.expander("Buchung manuell hinzufügen", expanded=False):
        st.caption("Pflichtangaben: Depot, Buchungsart, Datum und je nach Buchungsart ISIN, Stückzahl oder Betrag. "
                   "Nicht benötigte Felder können leer bleiben. Alle Änderungen werden protokolliert.")
        with st.form("tx_new"):
            st.markdown("#### 1. Grunddaten")
            cols = st.columns(2)
            depot = cols[0].selectbox("Depot", list(deps))
            t = cols[1].selectbox("Art", [x.value for x in TxType])
            d = st.date_input("Datum", value=date(y, 12, 31), format="DD.MM.YYYY")
            isin = st.text_input("ISIN", placeholder="z. B. AT0000A0E9W5", help="12-stellige internationale Wertpapierkennnummer")
            name = st.text_input("Wertpapiername", placeholder="Name laut Abrechnung")
            st.markdown("#### 2. Betrag und Währung")
            cols = st.columns(3)
            qty = cols[0].number_input("Stück", value=0.0, format="%.6f")
            price = cols[1].number_input("Kurs", value=0.0, format="%.4f")
            amount = cols[2].number_input("Bruttobetrag", value=0.0, format="%.2f")
            fees = cols[0].number_input("Gebühren", value=0.0, format="%.2f")
            cur = cols[1].selectbox("Währung", c.settings.currencies)
            fx = cols[2].number_input("Devisenkurs (je EUR)", value=0.0, format="%.6f")
            st.markdown("#### 3. Steuern und Sonderfälle")
            cols = st.columns(3)
            wht = cols[0].number_input("Quellensteuer", value=0.0, format="%.2f")
            country = cols[1].text_input("Quellenstaat", max_chars=2)
            kest = cols[2].number_input("Österr. KESt EUR", value=0.0, format="%.2f")
            ratio = cols[0].number_input("Split-Verhältnis neu/alt", value=0.0, format="%.4f")
            cats = [x.value for x in IncomeCategory]
            cat = cols[1].selectbox("Ertragsart", cats)
            cat_ver = st.checkbox("Ertragsart ist durch Beleg bestätigt (z. B. Kapitalrückzahlung, REIT-Bestandteile)")
            notes = st.text_area("Begründung/Notiz (Pflicht für manuelle Buchungen)",
                                 placeholder="Quelle und Grund der manuellen Erfassung", height=80)
            if st.form_submit_button("Buchung anlegen", type="primary", use_container_width=True):
                if not notes.strip():
                    st.error("Bitte eine Begründung angeben.")
                else:
                    try:
                        tx = TransactionIn(depot_id=deps[depot], tx_type=TxType(t), trade_date=d, isin=isin.strip().upper() or None,
                                           security_name=name or None, quantity=qty or None, price=price or None,
                                           amount=amount or None, fees=fees, currency=cur, fx_rate=fx or None,
                                           withholding_tax=wht, withholding_country=country.strip().upper() or None, kest_at_eur=kest,
                                           ratio=ratio or None, income_category=IncomeCategory(cat),
                                           income_category_verified=cat_ver, notes=notes, source_type="manuell",
                                           review_status=ReviewStatus.UNCHECKED)
                        dup = repo.find_duplicates(tx)
                        tid = repo.add_transaction(tx)
                        C.invalidate_results()
                        st.success(f"Buchung #{tid} angelegt.")
                        if dup["exact"] or dup["possible"]:
                            st.warning(f"Hinweis: ähnliche Buchungen vorhanden: "
                                       f"{[r['id'] for r in dup['exact'] + dup['possible']]}")
                    except ValidationError as exc:
                        C.form_error(exc)
    with st.expander("Ausgewählte Buchung im Detail bearbeiten", expanded=bool(selected_transactions)):
        rows = [r for r in rows if r['id'] in selected_transactions]
        if not rows:
            st.info("Oben eine Buchung über die Auswahlspalte markieren.")
            return
        if len(selected_transactions) == 1:
            st.session_state['tx_detail_selected'] = selected_transactions[0]
        if st.session_state.get('tx_detail_selected') not in [r['id'] for r in rows]:
            st.session_state.pop('tx_detail_selected', None)
        tid = st.selectbox("Buchung", [r["id"] for r in rows], key='tx_detail_selected',
                           format_func=lambda i: next(f"#{r['id']} {r['trade_date']} {r['tx_type']} {r['isin'] or ''} "
                                                      f"{r['amount']}" for r in rows if r["id"] == i))
        tx = repo.transaction(tid)
        with st.form("tx_edit"):
            cols = st.columns(4)
            amount = cols[0].number_input("Bruttobetrag", value=float(tx["amount"] or 0), format="%.2f")
            fees = cols[1].number_input("Gebühren", value=float(tx["fees"] or 0), format="%.2f")
            fx = cols[2].number_input("Devisenkurs (je EUR)", value=float(tx["fx_rate"] or 0), format="%.6f")
            qty = cols[3].number_input("Stück", value=float(tx["quantity"] or 0), format="%.6f")
            cols = st.columns(4)
            wht = cols[0].number_input("Quellensteuer", value=float(tx["withholding_tax"] or 0), format="%.2f")
            country = cols[1].text_input("Quellenstaat", tx["withholding_country"] or "", max_chars=2)
            cats = [x.value for x in IncomeCategory]
            cat = cols[2].selectbox("Ertragsart", cats, index=cats.index(tx["income_category"]))
            cat_ver = cols[3].checkbox("Ertragsart belegt", bool(tx["income_category_verified"]))
            review = st.selectbox("Prüfstatus", ["ungeprueft", "geprueft", "pruefen"],
                                  index=["ungeprueft", "geprueft", "pruefen"].index(tx["review_status"]))
            reason = st.text_input("Begründung der Änderung (Pflicht)")
            c1, c2 = st.columns(2)
            save = c1.form_submit_button("Änderung speichern")
            delete = c2.form_submit_button("Buchung löschen (logisch)")
        if save or delete:
            try:
                if delete:
                    repo.delete_transaction(tid, reason)
                else:
                    changes = {"amount": amount or None, "fees": fees, "fx_rate": fx or None, "quantity": qty or None,
                               "withholding_tax": wht, "withholding_country": country.upper() or None,
                               "income_category": cat, "income_category_verified": int(cat_ver),
                               "review_status": review}
                    changes = {k: v for k, v in changes.items() if v != tx.get(k)}
                    if changes:
                        repo.update_transaction(tid, changes, reason)
                C.invalidate_results()
                st.success("Gespeichert (protokolliert).")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


# --------------------------------------------------------------------------- #
DOC_STATUS_LABEL = {"neu": "🔵 neu", "verarbeitet": "✅ verarbeitet", "teilweise": "🟡 teilweise",
                    "pruefen": "🟡 zu prüfen", "fehlgeschlagen": "🔴 nicht lesbar", "ignoriert": "⚪ ignoriert"}


def _open_documents(repo) -> list[dict]:
    """All documents awaiting review, including those with an unconfirmed linked transaction."""
    return repo.db.query(
        "SELECT d.* FROM documents d "
        "WHERE d.status IN ('neu','pruefen','teilweise','fehlgeschlagen') "
        "ORDER BY d.tax_year DESC, d.id")


def _fund_document_review(repo, doc: dict, prefix: str) -> None:
    from ..importers.oekb_layouts import extract_published_reports
    from ..processing import process_fund_pdf, process_tables
    linked = [r for r in repo.fund_reports() if r.get('document_id') == doc['id']]
    if linked:
        st.markdown('**Zugeordnete Fondsmeldungen**')
        record_grid(repo, linked, 'fund', f'{prefix}fund_doc_{doc["id"]}')
    if st.button('OeKB-Datei erneut automatisch prüfen', key=f'{prefix}fund_retry_{doc["id"]}'):
        results = [process_fund_pdf(repo, doc, **C.document_analysis_options())] if doc['file_type'] == 'pdf' else \
            process_tables(repo, [(doc, True)], **C.document_analysis_options())
        C.after_processing(results)
    if doc['file_type'] != 'pdf':
        return
    try:
        cache = json.loads(doc.get('extraction_json') or '{}')
        reports = cache.get('fund_reports')
        if reports is None:
            reports = extract_published_reports(repo.document_path(doc).read_bytes())
    except (ValueError, OSError) as exc:
        st.error(f'OeKB-Analyse nicht möglich: {exc}')
        return
    if not reports:
        st.info('Kein unterstütztes OeKB-Layout erkannt. Original öffnen und Fondsmeldung unter Fonds & OeKB ergänzen.')
        return
    with st.expander('Erkannte Werte prüfen und ergänzen', expanded=not bool(linked)):
        for report in reports:
            for warning in report['warnings'] + report['missing']:
                st.warning(f"{report['values'].get('isin', 'Ohne ISIN')}: {warning}")
        records = [{'Übernehmen': not bool(r['warnings'] or r['missing']), **r['values']} for r in reports]
        for record in records:
            record.setdefault('fx_rate', None)
        edited = st.data_editor(pd.DataFrame(records), key=f'{prefix}fund_candidates_{doc["id"]}',
                                hide_index=True, width='stretch', num_rows='fixed')
        note = st.text_input('Prüfnotiz / Quelle der Korrektur', key=f'{prefix}fund_note_{doc["id"]}')
        if st.button('Ausgewählte Fondsmeldungen speichern', key=f'{prefix}fund_save_{doc["id"]}'):
            try:
                if not note.strip():
                    raise ValueError('Bitte die Prüfung oder Korrektur kurz begründen')
                candidates = []
                for row in edited.to_dict('records'):
                    if not row.pop('Übernehmen'):
                        continue
                    values = {k: v for k, v in row.items() if v is not None and not pd.isna(v)}
                    candidates.append(FundReportIn(**values, document_id=doc['id'], source='OeKB-PDF / manuell geprüft',
                                                   notes=note))
                if not candidates:
                    raise ValueError('Keine Fondsmeldung ausgewählt')
                results = [repo.add_fund_report(r) for r in candidates]
                repo.document_event(doc['id'], 'Fondsmeldungen manuell übernommen', {'notiz': note, 'meldungen': results})
                C.invalidate_results()
                st.success('Fondsmeldungen gespeichert. Abweichungen bleiben unter Fonds & OeKB als Konflikte sichtbar.')
            except ValueError as exc:
                st.error(str(exc))


def _document_detail(repo, doc: dict, y: int, review_first: bool, prefix: str = "") -> None:
    from ..importers.pdf_importer import PdfError, extract_pdf
    from ..processing import extraction_for
    from .pages_import import pdf_review_form

    did = doc["id"]
    path = repo.document_path(doc)
    document_preview(repo, did, f'{prefix}original_{did}')
    if doc["status"] != "verarbeitet" and st.button("Als erledigt markieren", key=f"{prefix}done_{did}"):
        repo.update_document(did, status="verarbeitet")
        repo.document_event(did, "manuell erledigt")
        st.rerun()
    if doc['doc_type'] == 'OeKB-Fondsmeldung':
        _fund_document_review(repo, doc, prefix)
        return
    if doc["file_type"] == "pdf":
        if st.button("PDF-Analyse aktualisieren", key=f"{prefix}refresh_{did}",
                     help="Liest das Original erneut aus. Bestehende Buchungen bleiben unverändert."):
            try:
                updated = extract_pdf(path.read_bytes(), **C.document_analysis_options()).to_dict()
                repo.update_document(did, extraction_json=json.dumps(updated, ensure_ascii=False, default=str))
                doc = repo.document(did)
                st.success("PDF wurde erneut analysiert. Der Prüfbericht wurde aktualisiert.")
            except (PdfError, OSError, ValueError) as exc:
                st.error(f"Erneute Analyse fehlgeschlagen: {exc}. Die bisherige Analyse bleibt erhalten.")
        try:
            exd = extraction_for(repo, doc)
        except (PdfError, OSError, ValueError) as exc:
            st.error(f"Die Datei kann nicht gelesen werden ({exc}). Werte bei Bedarf manuell unter "
                     "**Transaktionen** erfassen.")
            exd = None
        if exd:
            exd.setdefault("status_text", "")
            classification = exd.get('classification', {})
            if classification:
                st.caption(f"Einordnung: {classification.get('doc_type', 'Unbekannt')} · "
                           f"Methode: {classification.get('method', '')}")
                with st.expander('Erkannte Textmuster zur Einordnung'):
                    for evidence in classification.get('evidence', []):
                        st.text(evidence)
                    if classification.get('confidence', 0) < .8:
                        st.info('Vorläufige Zuordnung. Dokumentart und Original vergleichen.')
            if exd.get('components'):
                st.markdown('**Getrennt erkannte Bestandteile dieser Abrechnung**')
                C.df(exd['components'])
            if repo.transactions_for_document(did):
                st.info("Dieses Dokument ist bereits mit einer Buchung verknüpft. "
                        "Eine weitere automatische Buchung wird hier nicht angeboten.")
                from .guide import show_check_report
                if exd.get("checks"):
                    show_check_report(exd["checks"])
            elif review_first:
                pdf_review_form(doc, exd, None, key=f"{prefix}doc{did}")
            else:
                with st.expander("Prüfbericht und Buchung anlegen"):
                    pdf_review_form(doc, exd, None, key=f"{prefix}doc{did}")
    elif doc["file_type"] in ("csv", "txt", "xlsx"):
        st.info(doc.get('notes') or "Diese Tabelle kann über den gemeinsamen Upload automatisch erneut geprüft werden.")
        if st.button("Tabelle erneut automatisch prüfen", key=f'{prefix}table_retry_{did}'):
            from ..processing import process_tables
            C.after_processing(process_tables(repo, [(doc, False)], **C.document_analysis_options()))
        C.link("import", "Zum Import")
    with st.expander("Ablage, Zuordnung und Verlauf"):
        st.write(f"**Speicherort:** `{path}`  \n**SHA-256:** `{doc['sha256']}`  \n**Importiert:** "
                 f"{doc['imported_at']} ({doc['import_method']})")
        with st.form(f"{prefix}doc_edit_{did}"):
            st.caption("Ändert nur Ablageort und Metadaten – der Dateiinhalt bleibt unverändert.")
            cols = st.columns(4)
            ny = cols[0].number_input("Steuerjahr", 2000, 2100, value=int(doc["tax_year"] or y))
            ns = cols[1].selectbox("Quelle", DOC_SOURCES, index=DOC_SOURCES.index(doc["source"])
                                   if doc["source"] in DOC_SOURCES else 0)
            nt = cols[2].selectbox("Typ", DOC_TYPES, index=DOC_TYPES.index(doc["doc_type"]) if doc["doc_type"]
                                   in DOC_TYPES else DOC_TYPES.index("Unbekannt"))
            nst = cols[3].selectbox("Status", DOC_STATUS, index=DOC_STATUS.index(doc["status"])
                                     if doc["status"] in DOC_STATUS else 0,
                                    format_func=lambda v: DOC_STATUS_LABEL.get(v, v))
            notes = st.text_input("Notiz", doc["notes"] or "")
            if st.form_submit_button("Speichern"):
                try:
                    repo.update_document(did, tax_year=int(ny), source=ns, doc_type=nt, status=nst,
                                         notes=notes or None)
                    st.success("Gespeichert")
                    st.rerun()
                except OSError as exc:
                    st.error(f"Datei konnte nicht verschoben werden: {exc}")
        st.markdown("**Zugeordnete Buchungen**")
        C.df([{"ID": t["id"], "Datum": t["trade_date"], "Art": t["tx_type"], "ISIN": t["isin"],
               "Betrag": t["amount"]} for t in repo.transactions_for_document(did)])
        all_tx = repo.transactions(int(doc["tax_year"]) if doc["tax_year"] else None)
        if all_tx:
            cols = st.columns([3, 1])
            tsel = cols[0].selectbox("Bestehende Buchung als Beleg zuordnen", [t["id"] for t in all_tx],
                                     format_func=lambda i: next(f"#{t['id']} {t['trade_date']} {t['tx_type']} "
                                                                f"{t['isin'] or ''} {t['amount']}" for t in all_tx
                                                                if t["id"] == i), key=f"{prefix}link_{did}")
            if cols[1].button("Zuordnen", key=f"{prefix}linkbtn_{did}"):
                repo.link_document(did, int(tsel))
                repo.update_document(did, status="verarbeitet")
                st.rerun()
        st.markdown("**Verlauf**")
        C.df(repo.document_events(did))


def _bulk_document_editor(repo, docs: list[dict], key: str) -> None:
    """Edit document metadata in bulk; never create tax transactions implicitly."""
    if not docs:
        return
    with st.expander("Dokumente markieren und gemeinsam bearbeiten", expanded=False):
        table = pd.DataFrame([
            {"Markieren": False, "Datei": d["original_filename"], "Typ": d["doc_type"],
             "Status": DOC_STATUS_LABEL.get(d["status"], d["status"]),
             "Jahr": d["tax_year"], "ID": d["id"]}
            for d in docs
        ])
        edited = st.data_editor(
            table, key=f"{key}_selection_table", hide_index=True, height=330,
            disabled=["Datei", "Typ", "Status", "Jahr", "ID"],
            column_config={"Markieren": st.column_config.CheckboxColumn("✓", help="Dokument auswählen"),
                           "ID": st.column_config.NumberColumn("ID", width="small")},
            use_container_width=True,
        )
        allowed_ids = {d["id"] for d in docs}
        selected = [int(row["ID"]) for row in edited.to_dict("records")
                    if row["Markieren"] and row["ID"] in allowed_ids]
        st.caption(f"{len(selected)} von {len(docs)} Dokumenten markiert. "
                   "Nur aktivierte Felder werden geändert.")
        if not selected:
            return
        with st.form(f"{key}_bulk_form"):
            change_year = st.checkbox("Steuerjahr ändern", key=f"{key}_change_year")
            year = st.number_input("Neues Steuerjahr", min_value=2000, max_value=2100,
                                   value=date.today().year, disabled=not change_year, key=f"{key}_year")
            change_type = st.checkbox("Dokumenttyp ändern", key=f"{key}_change_type")
            dtype = st.selectbox("Neuer Dokumenttyp", DOC_TYPES, disabled=not change_type, key=f"{key}_type")
            change_source = st.checkbox("Quelle/Broker ändern", key=f"{key}_change_source")
            source = st.selectbox("Neue Quelle", DOC_SOURCES, disabled=not change_source, key=f"{key}_source")
            change_notes = st.checkbox("Notiz für alle setzen", key=f"{key}_change_notes")
            notes = st.text_area("Neue Notiz", disabled=not change_notes, key=f"{key}_notes")
            st.warning("Diese Aktion ändert nur Dokument-Metadaten, keine Buchungen oder Steuerberechnungen.")
            confirmed = st.checkbox("Änderungen für alle markierten Dokumente bestätigen",
                                    key=f"{key}_confirm")
            submit = st.form_submit_button(f"{len(selected)} Dokument(e) aktualisieren",
                                           type="primary", disabled=not confirmed)
        if submit:
            changes = {}
            if change_year:
                changes["tax_year"] = int(year)
            if change_type:
                changes["doc_type"] = dtype
            if change_source:
                changes["source"] = source
            if change_notes:
                changes["notes"] = notes
            if not changes:
                st.warning("Bitte mindestens ein Feld zur Änderung aktivieren.")
                return
            success, errors = 0, []
            for doc_id in selected:
                try:
                    repo.update_document(doc_id, **changes)
                    success += 1
                except (OSError, ValueError) as exc:
                    errors.append(f"#{doc_id}: {exc}")
            C.invalidate_results()
            if success:
                st.success(f"{success} Dokument(e) aktualisiert.")
            for err in errors:
                st.error(err)


def documents() -> None:
    c = C.ctx()
    repo = c.repo
    y = C.year_selector()
    st.title("Belege & Prüfung")
    if "last_process_results" in st.session_state:
        C.show_process_results(st.session_state.pop("last_process_results"))
    all_docs = repo.documents()
    open_docs = _open_documents(repo)
    counts = st.columns(3)
    counts[0].metric('Belege gesamt', len(all_docs))
    counts[1].metric('Offen / zu prüfen', len(open_docs))
    counts[2].metric('Erledigt', sum(d['status'] in ('verarbeitet', 'ignoriert') for d in all_docs))
    C.link('import', 'Weitere Dateien hinzufügen')
    view = st.segmented_control('Ansicht', ['Zu prüfen', 'Alle Belege', 'Erledigt'],
                default='Zu prüfen' if open_docs else 'Alle Belege', required=True, key='documents_view')
    controls = st.columns([3, 1, 2, 2])
    query = controls[0].text_input('Belege durchsuchen', placeholder='Dateiname, ISIN oder Notiz', key='documents_search')
    years = sorted({int(d['tax_year']) for d in all_docs if d.get('tax_year')}, reverse=True)
    fy = controls[1].selectbox('Jahr', ['alle'] + years, key='documents_year')
    source = controls[2].selectbox('Broker / Quelle', ['alle'] + DOC_SOURCES, key='documents_source',
                    format_func=lambda v: {'TradeRepublic': 'Trade Republic', 'ScalableCapital': 'Scalable Capital',
                                          'Unclassified': 'Nicht erkannt', 'Other': 'Sonstige'}.get(v, v))
    types = sorted({d['doc_type'] for d in all_docs})
    dtype = controls[3].selectbox('Dokumentart', ['alle'] + types, key='documents_type')
    docs = repo.documents(None if fy == 'alle' else int(fy), None if source == 'alle' else source,
                           None if dtype == 'alle' else dtype, query.strip() or None)
    if view == 'Zu prüfen':
        docs = [d for d in docs if d['status'] in ('neu', 'pruefen', 'teilweise', 'fehlgeschlagen')]
    elif view == 'Erledigt':
        docs = [d for d in docs if d['status'] in ('verarbeitet', 'ignoriert')]
    st.caption(f'{len(docs)} Belege in dieser Ansicht. Zeilen markieren, um Original und Prüfbericht zu öffnen.')
    pending = [d for d in docs if d['status'] in ('neu', 'pruefen', 'teilweise', 'fehlgeschlagen')]
    pdf_ids = [d['id'] for d in docs if d['file_type'] == 'pdf']
    if (pdf_ids or pending) and st.button('Erkennung für diese Ansicht aktualisieren', key='documents_recheck',
                            help='PDFs erneut lesen, offene Tabellen prüfen und Abweichungen zu vorhandenen Buchungen markieren.'):
        from ..processing import process_tables
        with st.spinner('Belege werden erneut gelesen …'):
            results = C.process_documents(repo, pdf_ids, reextract=True)
            results.extend(process_tables(repo, [(d, d['doc_type'] == 'OeKB-Fondsmeldung') for d in pending
                        if d['file_type'] in ('csv', 'txt', 'xlsx')], **C.document_analysis_options()))
        C.after_processing(results)
    selected = document_grid(repo, docs, 'document_list')
    if selected:
        did = selected[0] if len(selected) == 1 else st.selectbox('Ausgewählten Beleg öffnen', selected,
                    format_func=lambda did: repo.document(did)['original_filename'], key='document_detail_selected')
        st.divider()
        _document_detail(repo, repo.document(did), y, review_first=True, prefix='document_')
