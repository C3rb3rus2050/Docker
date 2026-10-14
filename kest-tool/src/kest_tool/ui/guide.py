"""Geführte Bedienung: Schnellstart, zentraler Upload, Datenprüfung mit Links zur Behebung."""

from __future__ import annotations

import streamlit as st

from ..processing import expand_upload, process_documents, store_uploads
from . import common as C

RESULT_ICON = {"ok": "✅", "info": "ℹ️", "warn": "⚠️", "error": "❌"}


def quickstart() -> bool:
    """Zeigt den Schnellstart, solange noch keine Depots existieren. Rückgabe: True, wenn angezeigt."""
    c = C.ctx()
    if c.repo.depots(active_only=True):
        return False
    with st.container(border=True):
        st.subheader("👋 Schnellstart")
        st.markdown("**Schritt 1 – Broker auswählen.** Für jeden gewählten Broker wird ein Depot angelegt. "
                    "Tipp: Laden Sie einfach Abrechnungen hoch – erkannte Broker werden dann automatisch angelegt.")
        with st.form("quickstart"):
            cols = st.columns(3)
            tr = cols[0].checkbox("Trade Republic", value=True)
            sc = cols[1].checkbox("Scalable Capital")
            other = cols[2].text_input("Anderer Broker (Name)")
            if st.form_submit_button("Depots anlegen", type="primary"):
                created = []
                for flag, name, key in ((tr, "Trade Republic", "TradeRepublic"),
                                        (sc, "Scalable Capital", "ScalableCapital"),
                                        (bool(other.strip()), other.strip(), "Other")):
                    if flag:
                        bid = c.repo.add_broker(name, key)
                        c.repo.add_depot(bid, f"{name} Depot")
                        created.append(name)
                if created:
                    st.success("Angelegt: " + ", ".join(created))
                    st.rerun()
                else:
                    st.warning("Bitte mindestens einen Broker auswählen oder einen Namen eingeben.")
        st.markdown("**Schritt 2 – Dokumente hochladen** (unten). **Schritt 3 – Status prüfen** und Excel exportieren.")
    return True


def upload_box(y: int, key: str, expanded: bool = True) -> None:
    """Ein Upload-Feld für alles: PDF-Abrechnungen, ZIP-Archive (z. B. vom Collector) und CSV/Excel."""
    c = C.ctx()
    with st.expander("📥 Dokumente hinzufügen (PDF, ZIP, CSV)", expanded=expanded):
        st.caption("PDF-Abrechnungen werden gelesen, geprüft und – wenn alle Werte sicher erkannt und stimmig sind – "
                   "automatisch als Buchung übernommen. Alles andere erscheint mit Grund und „Was tun?“ zur Prüfung. "
                   "ZIP-Archive (z. B. aus dem Broker Document Collector) werden entpackt.")
        files = st.file_uploader("Dateien auswählen oder hierher ziehen", type=["pdf", "zip", "csv", "txt", "xlsx"],
                                 accept_multiple_files=True, key=f"upl_{key}")
        deps = C.depot_options()
        dflt = st.selectbox("Depot, falls es nicht automatisch erkannt wird", ["automatisch"] + list(deps),
                            key=f"upl_depot_{key}",
                            help="Trade Republic und Scalable Capital werden aus dem Dokument erkannt. Bei mehreren "
                                 "Depots desselben Brokers hier das richtige wählen.")
        if files and st.button("Hochladen und verarbeiten", type="primary", key=f"upl_go_{key}"):
            items, problems = [], []
            max_mb = int(c.settings.get("import.max_upload_mb", 50))
            for up in files:
                data = up.getvalue()
                if len(data) > max_mb * 1024 * 1024 and not up.name.lower().endswith(".zip"):
                    problems.append((up.name, f"größer als {max_mb} MB"))
                    continue
                try:
                    items += expand_upload(up.name, data)
                except ValueError as exc:
                    problems.append((up.name, str(exc)))
            with st.spinner(f"{len(items)} Datei(en) werden abgelegt und geprüft …"):
                res = store_uploads(c.repo, items, y, c.settings.get("pdf.engine", "auto"))
                results = process_documents(c.repo, res.pdf_ids, deps.get(dflt)) if res.pdf_ids else []
            st.session_state["upload_notes"] = {
                "skipped": problems + res.skipped,
                "csv": [(d["original_filename"], oekb) for d, oekb in res.csv_docs],
                "duplicates": res.duplicates}
            C.after_processing(results) if results else st.rerun()
    if "last_process_results" in st.session_state:
        C.show_process_results(st.session_state.pop("last_process_results"))
    notes = st.session_state.pop("upload_notes", None)
    if notes:
        if notes["duplicates"]:
            st.info(f"{notes['duplicates']} Datei(en) waren bereits vorhanden (gleicher Inhalt) und wurden nicht "
                    "doppelt abgelegt.")
        for name, why in notes["skipped"]:
            st.error(f"„{name}“ wurde nicht übernommen: {why}")
        for name, oekb in notes["csv"]:
            st.warning(f"„{name}“ wurde abgelegt. CSV-Dateien brauchen eine Spaltenzuordnung → **Import → "
                       f"{'OeKB – Fondsdaten' if oekb else 'CSV/Excel – Transaktionen'}** (dieselbe Datei dort erneut "
                       "auswählen).")
            C.link("import", "Zur Import-Seite")


def data_check(y: int) -> list[tuple[str, str, str, str]]:
    """Datenprüfung: (Symbol, Thema, Text, Seite) – zeigt Lücken, die das Ergebnis verfälschen können."""
    c = C.ctx()
    db = c.db
    end = f"{y}-12-31"
    rows: list[tuple[str, str, str, str]] = []

    def n(sql, params=()):
        return db.one(sql, params)["n"]

    unknown_settings = [d["name"] for d in c.repo.depots(active_only=True)
                        if c.repo.depot_tax_settings(d["id"], y).get("_default")
                        and n("SELECT COUNT(*) n FROM transactions WHERE deleted=0 AND depot_id=? AND "
                              "substr(trade_date,1,4)=?", (d["id"], str(y)))]
    if unknown_settings:
        rows.append(("🟡", "Depot-Steuereinstellung",
                     f"Für {', '.join(unknown_settings)} ist für {y} nicht angegeben, ob der Broker österreichische "
                     "KESt abführt – sonst droht Doppel- oder Nichtbesteuerung.", "depots"))
    unclassified = n("SELECT COUNT(DISTINCT s.isin) n FROM securities s JOIN transactions t ON t.isin=s.isin "
                     "WHERE t.deleted=0 AND t.trade_date<=? AND (s.tax_class='ungeklaert' OR s.tax_class_verified=0)",
                     (end,))
    if unclassified:
        rows.append(("🟡", "Wertpapier-Einstufung", f"{unclassified} Wertpapier(e) ohne geprüfte steuerliche "
                     "Einstufung – Ergebnisse bleiben vorläufig.", "wertpapiere"))
    funds = n("SELECT COUNT(DISTINCT s.isin) n FROM securities s JOIN transactions t ON t.isin=s.isin WHERE "
              "t.deleted=0 AND t.trade_date<=? AND s.security_type IN ('ETF ausschüttend','ETF thesaurierend',"
              "'Investmentfonds (AT)','Investmentfonds (Ausland)') AND s.fund_status IN ('unbekannt','kein_fonds')",
              (end,))
    if funds:
        rows.append(("🔴", "Meldefondsstatus", f"{funds} Fonds/ETF ohne Meldefondsstatus – Fondserträge können "
                     "nicht berechnet werden.", "wertpapiere"))
    no_type = n("SELECT COUNT(DISTINCT s.isin) n FROM securities s JOIN transactions t ON t.isin=s.isin WHERE "
                "t.deleted=0 AND t.trade_date<=? AND s.security_type='Sonstige'", (end,))
    if no_type:
        rows.append(("🟡", "Wertpapierart", f"{no_type} Wertpapier(e) ohne Wertpapierart (Aktie, ETF …).",
                     "wertpapiere"))
    no_country = n("SELECT COUNT(*) n FROM transactions t LEFT JOIN securities s ON s.isin=t.isin WHERE "
                   "t.deleted=0 AND substr(t.trade_date,1,4)=? AND t.withholding_tax>0 AND "
                   "t.withholding_country IS NULL AND (s.country IS NULL OR s.country='')", (str(y),))
    if no_country:
        rows.append(("🟡", "Quellenstaat", f"{no_country} Ertrag/Erträge mit Quellensteuer ohne Quellenstaat – "
                     "Anrechnung nicht möglich.", "wertpapiere"))
    to_review = n("SELECT COUNT(*) n FROM transactions WHERE deleted=0 AND review_status='pruefen' AND "
                  "substr(trade_date,1,4)=?", (str(y),))
    if to_review:
        rows.append(("🟡", "Buchungen zu prüfen", f"{to_review} Buchung(en) mit Prüfkennzeichen (z. B. "
                     "Dublettenverdacht).", "transaktionen"))
    conflicts = n("SELECT COUNT(*) n FROM conflicts WHERE status='offen'")
    if conflicts:
        rows.append(("🔴", "Widersprüche", f"{conflicts} offene(r) Datenkonflikt(e) – Entscheidung nötig.", "fonds"))
    res = C.tax_result(y)
    if res:
        gaps = [l for l in res.lines if "Kaufhistorie unvollständig" in " ".join(l.notes)]
        if gaps:
            rows.append(("🔴", "Kaufhistorie", f"{len(gaps)} Verkauf/Verkäufe ohne vollständige Käufe – Gewinn "
                         "kann nicht berechnet werden. Ältere Abrechnungen/Exporte importieren.", "import"))
    return rows


def show_check_report(checks: list[dict]) -> None:
    """Prüfbericht eines Dokuments: Probleme mit „Was tun?“ zuerst, bestandene Prüfungen eingeklappt."""
    if not checks:
        return
    problems = [c for c in checks if c["result"] in ("error", "warn")]
    passed = [c for c in checks if c["result"] not in ("error", "warn")]
    if problems:
        st.markdown(f"**Prüfbericht: {sum(1 for c in problems if c['result'] == 'error')} Fehler, "
                    f"{sum(1 for c in problems if c['result'] == 'warn')} Warnung(en)**")
        for c in problems:
            text = f"{RESULT_ICON[c['result']]} **{c['name']}:** {c['detail']}"
            if c.get("action"):
                text += f"  \n  → **Was tun?** {c['action']}"
            st.markdown(text)
    else:
        st.markdown("✅ **Alle Prüfungen bestanden** – Werte trotzdem kurz mit dem Original vergleichen.")
    if passed:
        with st.expander(f"Bestandene Prüfungen und Hinweise ({len(passed)})"):
            for c in passed:
                st.markdown(f"{RESULT_ICON.get(c['result'], '')} **{c['name']}:** {c['detail']}"
                            + (f" – {c['action']}" if c.get("action") else ""))
