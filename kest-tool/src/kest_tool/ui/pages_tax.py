"""Seiten: Steuerberechnung, Exporte."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..export.excel import export_excel
from ..export.reports import export_csv, export_e1kv_helper, export_pdf_report
from ..tax.engine import MANUAL, PROVISIONAL, STATUS_TEXT
from . import common as C


def tax() -> None:
    y = C.year_selector()
    st.title(f"Steuerberechnung {y}")
    st.caption(C.DISCLAIMER)
    res = C.tax_result(y, force=st.button("Neu berechnen", type="primary"))
    if not res:
        return
    s, sc = res.summary, res.summary_confirmed
    n_prov, n_man = s["Positionen vorläufig"], s["Positionen manuell zu prüfen"]
    if n_prov or n_man:
        st.warning(f"Keine endgültigen Ergebnisse: {n_prov} Positionen vorläufig, {n_man} manuell steuerlich zu prüfen "
                   "(nicht berechnet). „Gesichert“ enthält nur Positionen mit offiziell belegter Regel und geprüften "
                   "Daten.")
    m = st.columns(4)
    m[0].metric("Bemessungsgrundlage 27,5 %", C.eur(s["Bemessungsgrundlage 27,5 %"]),
                help=f"gesichert: {C.eur(sc['Bemessungsgrundlage 27,5 %'])}")
    m[1].metric("Bemessungsgrundlage 25 %", C.eur(s["Bemessungsgrundlage 25 %"]))
    m[2].metric("Anrechenbare QSt (Schätzung)", C.eur(s["Anrechenbare Quellensteuer (nach Verlustausgleich, Schätzung)"]))
    m[3].metric("Geschätzte Steuer", C.eur(s["Geschätzte Steuer nach Anrechnung"]),
                help="Schätzung, inkl. vorläufiger Positionen")
    tabs = st.tabs(["Übersicht", "Positionen", "Berechnungsgrundlagen", "Verlustausgleich", "Fonds/Nichtmeldefonds",
                    "E 1kv", "Prüfhinweise", "Regeln & Quellen", "Bestände"])
    with tabs[0]:
        C.df(pd.DataFrame([{"Kennzahl": k, "Gesamt (inkl. vorläufig)": v, "davon gesichert": sc.get(k)}
                           for k, v in s.items()]),
             column_config={"Gesamt (inkl. vorläufig)": st.column_config.NumberColumn(format="%.2f"),
                            "davon gesichert": st.column_config.NumberColumn(format="%.2f")})
    with tabs[1]:
        cats = sorted({l.category for l in res.lines})
        cols = st.columns(2)
        fc = cols[0].multiselect("Kategorie", cats)
        fs = cols[1].multiselect("Status", list(STATUS_TEXT.values()))
        rows = []
        for l in res.lines:
            if fc and l.category not in fc:
                continue
            if fs and STATUS_TEXT[l.status] not in fs:
                continue
            rows.append({"": C.status_badge(l.status), "Position": l.line_id, "Datum": l.date,
                         "Kategorie": l.category, "Gruppe": l.bucket, "Depot": l.depot, "ISIN": l.isin,
                         "Name": l.name, "Ausgang": l.gross, "Ansatz": l.amount, "Verlustausgleich": -l.offset_amount,
                         "QSt": l.withholding_tax, "anrechenbar": l.creditable_tax_max, "Satz": l.rate,
                         "Status": STATUS_TEXT[l.status], "Hinweise": "; ".join(l.notes)})
        C.df(rows)
    with tabs[2]:
        if res.lines:
            lid = st.selectbox("Position", [l.line_id for l in res.lines],
                               format_func=lambda i: next(f"{l.line_id} – {l.category} {l.isin or ''}"
                                                          for l in res.lines if l.line_id == i))
            l = next(x for x in res.lines if x.line_id == lid)
            st.write(f"**Status:** {C.status_badge(l.status)} {STATUS_TEXT[l.status]} · **Steuerjahr:** {l.tax_year} · "
                     f"**Satz:** {f'{l.rate:.1%}' if l.rate else '–'} · **Ergebnis:** {C.eur(l.amount)}")
            st.markdown("**Rechenschritte**")
            for step in l.steps or ["–"]:
                st.write("• " + step)
            st.markdown("**Ausgangsdaten / Herkunft**")
            for src in l.sources or ["–"]:
                st.write("• " + src)
            st.markdown("**Angewendete Regeln**")
            from ..tax.rules import load_rules
            rules = load_rules()
            for rid in l.rule_ids:
                r = rules.rule(rid, l.tax_year)
                st.write(f"• **{rid}** – {r.title} ({r.legal_basis}) – *{r.status_label}*  \n"
                         f"  Quellen: {rules.source_text(r.sources) or '–'}")
            if l.notes:
                st.markdown("**Hinweise**")
                for n in l.notes:
                    st.write("• " + n)
    with tabs[3]:
        C.df([{"Verlust": r.loss_line, "Kategorie": r.category, "Depot": r.depot, "ISIN": r.isin,
               "Ursprünglicher Verlust": r.original_loss,
               "Zugeordnete Erträge": "; ".join(f"{a} {b}: {c:.2f}" for a, b, c in r.offsets),
               "Verrechnet": r.offset_total, "Nicht verrechenbar": r.remaining, "Begründung": "; ".join(r.reasons),
               "Status": STATUS_TEXT[r.status]} for r in res.loss_offsets])
    with tabs[4]:
        st.markdown("**Meldefonds (OeKB-Meldungen)**")
        C.df(res.fund_rows)
        st.markdown("**Nichtmeldefonds**")
        C.df(res.nmf_rows)
    with tabs[5]:
        st.caption("Übertragungshilfe – Werte manuell in FinanzOnline übernehmen. Kennzahlen mit Status „nicht "
                   "verifiziert“ vor Übernahme im amtlichen Formular prüfen.")
        C.df(res.e1kv)
    with tabs[6]:
        sev = st.multiselect("Schweregrad", ["Fehler", "Warnung", "Hinweis"], default=["Fehler", "Warnung"])
        C.df([i.__dict__ for i in res.issues if i.severity in sev])
    with tabs[7]:
        C.df(res.rules_used)
    with tabs[8]:
        C.df(res.positions)


def exports() -> None:
    c = C.ctx()
    y = C.year_selector()
    st.title(f"Exporte {y}")
    res = C.tax_result(y)
    if not res:
        return
    st.caption(f"Ablage: `{c.store.base / 'exports' / str(y)}`. Dateinamen enthalten Steuerjahr und Exportdatum; "
               "bestehende Dateien werden nie überschrieben.")
    cols = st.columns(4)
    created = None
    if cols[0].button("Excel-Datei erstellen", type="primary"):
        created = [export_excel(c.repo, c.store, C.tax_result(y, force=True))]
    if cols[1].button("CSV-Exporte erstellen"):
        created = export_csv(c.repo, c.store, C.tax_result(y, force=True))
    if cols[2].button("PDF-Jahresbericht erstellen"):
        created = [export_pdf_report(c.repo, c.store, C.tax_result(y, force=True))]
    if cols[3].button("E 1kv-Arbeitshilfe erstellen"):
        created = [export_e1kv_helper(c.repo, c.store, C.tax_result(y, force=True))]
    if created:
        for i, p in enumerate(created):
            st.success(f"Gespeichert: {p}")
            C.download_button(p, f"new_{i}")
    st.subheader("Exporthistorie")
    hist = c.repo.exports(y)
    C.df([{"ID": e["id"], "Zeit": e["ts"], "Art": e["kind"], "Datei": e["stored_path"], "SHA-256": e["sha256"][:16]
           if e["sha256"] else "", "Notiz": e["notes"]} for e in hist])
    if hist:
        eid = st.selectbox("Gespeicherte Datei", [e["id"] for e in hist],
                           format_func=lambda i: next(e["stored_path"] for e in hist if e["id"] == i))
        e = next(x for x in hist if x["id"] == eid)
        try:
            p = c.store.absolute(e["stored_path"])
        except ValueError as exc:
            st.error(str(exc))
            return
        if p.exists():
            b1, b2 = st.columns(2)
            with b1:
                C.open_file_button(p, f"exp_open_{eid}")
            with b2:
                C.download_button(p, f"exp_dl_{eid}")
        else:
            st.warning("Datei nicht mehr vorhanden.")
