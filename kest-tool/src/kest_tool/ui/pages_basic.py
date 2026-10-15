"""Seiten: Dashboard, Broker & Depots, Einstellungen."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ..security import is_probably_cloud_synced

from ..context import shutdown_logging
from ..backup import BackupError, create_backup, restore_backup, verify_backup
from ..export.excel import export_excel
from ..models import BROKER_KEYS, TRISTATE
from ..tax.rules import load_rules
from . import common as C


def dashboard() -> None:
    from .guide import quickstart, upload_box

    c = C.ctx()
    y = C.year_selector()
    st.title(f"Übersicht – Steuerjahr {y}")
    st.caption(C.DISCLAIMER)
    first_run = quickstart()
    s = c.repo.stats(y)
    if s["depots"]:
        cols = st.columns(5)
        cols[0].metric("Broker", s["brokers"])
        cols[1].metric("Depots", s["depots"])
        cols[2].metric(f"Dokumente {y}", s["documents"], help=f"insgesamt {s['documents_total']}")
        cols[3].metric(f"Buchungen {y}", s["transactions"])
        cols[4].metric("Offene Konflikte", s["open_conflicts"])
    st.subheader("Ihr nächster Schritt")
    actions = st.columns(3)
    for column, number, title, text, target, label in (
        (actions[0], "01", "Dokumente importieren", "Abrechnungen sammeln und Buchungen übernehmen.", "import", "Zum Import"),
        (actions[1], "02", "Daten prüfen", "Offene Belege und Zuordnungen vervollständigen.", "dokumente", "Dokumente prüfen"),
        (actions[2], "03", "Ergebnisse exportieren", "Auswertungen und die E 1kv-Arbeitshilfe erstellen.", "exporte", "Zu den Exporten"),
    ):
        with column, st.container(border=True, key=f"next_action_{target}"):
            st.caption(f"SCHRITT {number}")
            st.markdown(f"**{title}**")
            st.caption(text)
            C.link(target, label)
    upload_box(y, "dash", expanded=first_run or not s["transactions"])
    if st.button("Neu berechnen", help="Ergebnis nach Änderungen neu berechnen"):
        C.tax_result(y, force=True)
    C.auto_fill_fx(y)
    C.auto_fill_prices(y)
    C.status_panel(y, "dash")
    res = C.tax_result(y)
    if res:
        sm = res.summary
        st.subheader("Erträge und realisierte Ergebnisse (inkl. vorläufiger Positionen)")
        m = st.columns(4)
        m[0].metric("Dividenden", C.eur(sm["Dividenden"]))
        m[1].metric("Fondserträge", C.eur(sm["Fondsausschüttungen (steuerpflichtig)"] +
                                          sm["Ausschüttungsgleiche Erträge"] + sm["Nichtmeldefonds pauschal"]))
        m[2].metric("Realisierte Gewinne", C.eur(sm["Realisierte Gewinne"]))
        m[3].metric("Realisierte Verluste", C.eur(sm["Realisierte Verluste"]))
        m = st.columns(4)
        m[0].metric("Quellensteuer einbehalten", C.eur(sm["Ausländische Quellensteuer einbehalten"]))
        m[1].metric("anrechenbare Steuer (max.)",
                    C.eur(sm["Anrechenbare Quellensteuer (Höchstbetrag vor Verlustausgleich)"]),
                    help="Höchstbetrag vor Verlustausgleich, inkl. anrechenbarer Steuer laut OeKB-Fondsmeldungen")
        m[2].metric("ungeklärt", C.eur(sm["Ungeklärte Quellensteuer"]))
        m[3].metric("Geschätzte Steuer", C.eur(sm["Geschätzte Steuer nach Anrechnung"]),
                    help="Schätzung inkl. vorläufiger Positionen – nicht endgültig")
    runs = c.repo.import_runs(1)
    if runs:
        r = runs[0]
        st.write(f"**Letzter Import:** #{r['id']} {r['import_type']} am {r['started_at']} – Status "
                 f"**{r['status']}** ({r.get('message') or ''})")
    if res and res.lines and st.button("Excel-Export erstellen", type="primary"):
        p = export_excel(c.repo, c.store, res)
        st.success(f"Gespeichert: {p}")
        C.download_button(p, "dash_dl")


def brokers() -> None:
    c = C.ctx()
    repo = c.repo
    y = C.year_selector()
    st.title("Broker und Depots")
    with st.expander("Broker hinzufügen", expanded=not repo.brokers()):
        with st.form("broker_add"):
            name = st.text_input("Name", placeholder="z. B. Trade Republic")
            key = st.selectbox("Typ / Datenquelle", BROKER_KEYS,
                               help="Bestimmt den Ablageordner (TradeRepublic, ScalableCapital, Other)")
            country = st.text_input("Sitzstaat (ISO-2, nur Info)", max_chars=2)
            notes = st.text_input("Notiz")
            if st.form_submit_button("Speichern"):
                try:
                    repo.add_broker(name, key, country.upper() or None, notes or None)
                    st.success("Broker gespeichert")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    if repo.brokers():
        with st.expander("Depot hinzufügen", expanded=not repo.depots()):
            with st.form("depot_add"):
                bmap = {b["name"]: b["id"] for b in repo.brokers()}
                b = st.selectbox("Broker", list(bmap))
                name = st.text_input("Depotname", placeholder="z. B. Hauptdepot")
                ref = st.text_input("Kurzreferenz (optional, z. B. letzte 4 Stellen – keine Zugangsdaten!)")
                cur = st.selectbox("Depotwährung", c.settings.currencies)
                if st.form_submit_button("Speichern"):
                    try:
                        repo.add_depot(bmap[b], name, ref or None, cur)
                        st.success("Depot gespeichert")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    st.subheader("Depots")
    deps = repo.depots()
    C.df([{"ID": d["id"], "Broker": d["broker_name"], "Typ": d["broker_key"], "Depot": d["name"],
           "Referenz": d["account_ref"], "Währung": d["currency"], "aktiv": bool(d["active"])} for d in deps])
    if deps:
        st.subheader(f"Steuerliche Einstellungen je Depot für {y}")
        st.caption("Für jedes Steuerjahr getrennt: Führt der Broker österreichische KESt ab bzw. einen "
                   "Verlustausgleich durch? Diese Angaben verhindern Doppelzählungen und werden nicht auf andere "
                   "Jahre übertragen.")
        st.info("**So finden Sie es heraus:** Steht auf Ihren Abrechnungen bzw. der Jahressteuerbescheinigung eine "
                "Zeile „Kapitalertragsteuer Österreich“/„KESt“, führt der Broker österreichische KESt ab → **ja**. "
                "Fehlt sie (typisch bei ausländischen Brokern ohne österreichische Steuerabwicklung) → **nein**. "
                "Unsicher → **unbekannt** lassen; das Tool rechnet dann wie bei einem ausländischen Depot und zeigt "
                "einen Hinweis.")
        rows = []
        for d in deps:
            s = repo.depot_tax_settings(d["id"], y)
            rows.append({"depot_id": d["id"], "Depot": f"{d['broker_name']} – {d['name']}",
                         "KESt-Abzug durch Broker": s["kest_withheld"],
                         "Verlustausgleich durch Broker": s["loss_offset_by_broker"],
                         "Quelle": s.get("source") or ""})
        edited = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch",
                                column_config={
                                    "depot_id": st.column_config.NumberColumn("ID", disabled=True),
                                    "Depot": st.column_config.TextColumn(disabled=True),
                                    "KESt-Abzug durch Broker": st.column_config.SelectboxColumn(options=TRISTATE),
                                    "Verlustausgleich durch Broker": st.column_config.SelectboxColumn(options=TRISTATE),
                                }, key=f"dts_{y}")
        if st.button("Einstellungen speichern"):
            for _, r in edited.iterrows():
                repo.set_depot_tax_settings(int(r["depot_id"]), y, r["KESt-Abzug durch Broker"],
                                            r["Verlustausgleich durch Broker"], r["Quelle"] or None)
            C.invalidate_results()
            st.success("Gespeichert")
        with st.expander("Depot deaktivieren/aktivieren"):
            dm = {f"{d['broker_name']} – {d['name']}": d for d in deps}
            sel = st.selectbox("Depot", list(dm), key="deact")
            if st.button("Status umschalten"):
                repo.update_depot(dm[sel]["id"], active=0 if dm[sel]["active"] else 1)
                st.rerun()
    st.subheader("Datenquellen und Importhistorie")
    C.df([{"Lauf": r["id"], "Start": r["started_at"], "Typ": r["import_type"], "Depot-ID": r["depot_id"],
           "Datei": r.get("original_filename"), "Status": r["status"], "Importiert": r["rows_imported"],
           "Dubletten": r["rows_duplicates"], "Fehler": r["rows_errors"], "Meldung": r["message"]}
          for r in repo.import_runs()])


def settings_page() -> None:
    c = C.ctx()
    st.title("Einstellungen")
    from ..diagnostics import event_count, export_report
    with st.expander("🩺 Diagnose und Fehlerbericht", expanded=False):
        st.write(f"Erfasste Anwendungsfehler: **{event_count()}**")
        st.caption("Der Bericht enthält nur Fehlerkennungen, Zeitpunkte, betroffene Bereiche, "
                   "Fehlertypen und technische Versionsangaben. Keine Dokumente, Buchungen, "
                   "Zugangsdaten oder vollständigen Serverlogs.")
        st.download_button("Diagnosebericht als ZIP herunterladen", data=export_report(),
                           file_name="kest-diagnose.zip", mime="application/zip",
                           use_container_width=True)
        st.info("Browserseitige Darstellungsprobleme ohne Python-Fehler werden nicht automatisch erkannt.")
    st.subheader("Ablageordner")
    st.write(f"Aktuell: `{c.store.base}`")
    if is_probably_cloud_synced(c.store.base):
        st.warning("Der Ablageordner liegt vermutlich in einem Cloud-Sync-Ordner (z. B. OneDrive). Finanzdokumente "
                   "würden dann in die Cloud übertragen. Empfehlung: lokalen Ordner wählen.")
    import os
    managed_home = bool(os.environ.get("KEST_TOOL_HOME"))
    if managed_home:
        st.info("Der Ablageordner wird durch die Installation festgelegt. Einstellungen bleiben hier dauerhaft gespeichert.")
    with st.form("basedir"):
        new = st.text_input("Neuer Ablageordner", value=str(c.store.base),
                            help="Umgebungsvariablen wie %USERPROFILE% sind erlaubt. Bestehende Daten werden nicht "
                                 "verschoben – dazu Backup erstellen und im neuen Ordner wiederherstellen.", disabled=managed_home)
        if st.form_submit_button("Speichern", disabled=managed_home):
            try:
                from ..config import expand_path
                p = expand_path(new)
                p.mkdir(parents=True, exist_ok=True)
                test = p / ".schreibtest"
                test.write_text("ok")
                test.unlink()
                c.settings.save_local({"base_dir": new})
                C.reset_context()
                st.success(f"Ablageordner gesetzt: {p}")
                st.rerun()
            except OSError as exc:
                st.error(f"Ordner nicht nutzbar: {exc}")
    st.subheader("Steuerjahr, Währungen und Importoptionen")
    with st.form("prefs"):
        years = st.multiselect("Verfügbare Steuerjahre", list(range(2016, 2031)), default=c.settings.tax_years,
                               help="Berechnet werden nur Jahre, für die in tax_rules.yaml Regeln hinterlegt sind.")
        default_year = st.selectbox("Standard-Steuerjahr", c.settings.tax_years,
                                    index=c.settings.tax_years.index(c.settings.default_tax_year)
                                    if c.settings.default_tax_year in c.settings.tax_years else 0)
        currencies = st.multiselect("Währungen", ["EUR", "USD", "CHF", "GBP", "CAD", "JPY", "DKK", "SEK", "NOK",
                                                  "AUD", "HKD", "SGD"], default=c.settings.currencies)
        dec = st.selectbox("Dezimaltrennzeichen (Standard für Importe)", ["auto", ",", "."],
                           index=["auto", ",", "."].index(c.settings.get("import.decimal_separator", "auto")))
        fuzzy = st.number_input("Dublettenverdacht: Datumsabstand (Tage)", 0, 14,
                                int(c.settings.get("import.fuzzy_duplicate_days", 3)))
        if st.form_submit_button("Speichern"):
            c.settings.save_local({"tax_years": sorted(years), "default_tax_year": int(default_year),
                                   "currencies": currencies,
                                   "import": {"decimal_separator": dec, "fuzzy_duplicate_days": int(fuzzy)}})
            C.reset_context()
            st.success("Gespeichert")
            st.rerun()
    st.subheader("Devisenkurse (EZB-Referenzkurse)")
    from ..fx import ECB_URL, FxError, FxService
    fxs = FxService(c.store.base)
    info = fxs.cache_info()
    if info["vorhanden"]:
        st.write(f"Lokaler Kursbestand bis **{info['stand']}**, {info['waehrungen']} Währungen, geladen am "
                 f"{info['geladen']}.")
    else:
        st.write("Noch keine Kurse geladen.")
    st.caption(f"Quelle: {ECB_URL} (öffentlich; es werden keine eigenen Daten übertragen). Kurse aus Belegen haben "
               "Vorrang und werden nie überschrieben. Ob der EZB-Referenzkurs steuerlich maßgeblich ist, ist nicht "
               "verifiziert – betroffene Positionen bleiben „vorläufig“.")
    auto = st.checkbox("Fehlende Kurse automatisch von der EZB laden", value=bool(c.settings.get("fx.auto_fetch", True)))
    if auto != bool(c.settings.get("fx.auto_fetch", True)):
        c.settings.save_local({"fx": {"auto_fetch": auto}})
        st.rerun()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Kurse jetzt von der EZB aktualisieren"):
            try:
                r = fxs.download()
                st.success(f"Geladen: Stand {r.last_date}, {len(r.currencies)} Währungen")
            except FxError as exc:
                st.error(str(exc))
        if st.button("Fehlende Kurse in allen Buchungen ergänzen"):
            C.fill_fx(None, allow_download=auto)
    with col2:
        up_fx = st.file_uploader("Kursdatei manuell importieren (eurofxref-hist.zip oder .csv)", type=["zip", "csv"],
                                 key="fx_up")
        if up_fx and st.button("Kursdatei übernehmen"):
            try:
                r = fxs.import_bytes(up_fx.getvalue())
                st.success(f"Importiert: Stand {r.last_date}, {len(r.currencies)} Währungen")
            except (FxError, ValueError) as exc:
                st.error(f"Datei nicht verwendbar: {exc}")
    st.subheader("Wertpapierkurse")
    from ..config import save_env_var
    from ..prices import ENV_KEY, PriceError, import_price_csv, price_csv_template
    svc = C.price_service()
    st.write("Kursdienst: **EODHD** (https://eodhd.com, Suche per ISIN). "
             + ("API-Schlüssel ist **hinterlegt**." if svc.provider.available else "**Kein API-Schlüssel hinterlegt.**"))
    st.caption("Verwendung: erster/letzter Kurs des Jahres für Nichtmeldefonds und Bewertung der Bestände zum 31.12. "
               "Übertragen werden nur ISIN bzw. Börsenkürzel und Zeitraum. Der kostenlose Zugang ist laut Anbieter auf "
               "20 Abrufe pro Tag und Kurse des letzten Jahres beschränkt.")
    st.markdown("**Rücknahmepreise (Nichtmeldefonds):** Reihenfolge 1) importierte Rücknahmepreise (z. B. CSV der "
                "Fondsgesellschaft), 2) EODHD „EUFUND“ (Rücknahmepreise/NAV europäischer Fonds, laut Anbieter erst ab "
                "Paket „All World Extended“), 3) ersatzweise Börsenschlusskurse mit Hinweis „kein Rücknahmepreis“. "
                "Fremdwährungen werden mit dem EZB-Kurs zum letzten Preisdatum umgerechnet. Alle geladenen Werte "
                "bleiben „ungeprüft“.")
    fb = st.checkbox("Ohne Rücknahmepreise ersatzweise Börsenschlusskurse verwenden",
                     value=bool(c.settings.get("prices.nmf_exchange_fallback", True)))
    if fb != bool(c.settings.get("prices.nmf_exchange_fallback", True)):
        c.settings.save_local({"prices": {"nmf_exchange_fallback": fb}})
        st.rerun()
    with st.form("px_key"):
        key_in = st.text_input(f"API-Schlüssel ({ENV_KEY}, wird nur lokal in .env gespeichert)", type="password")
        c1, c2 = st.columns(2)
        if c1.form_submit_button("Schlüssel speichern") and key_in.strip():
            save_env_var(ENV_KEY, key_in.strip())
            st.success("Gespeichert.")
            st.rerun()
        if c2.form_submit_button("Schlüssel entfernen"):
            save_env_var(ENV_KEY, "")
            st.rerun()
    px_auto = st.checkbox("Fehlende Kurse automatisch laden (beim Öffnen des Dashboards)",
                          value=bool(c.settings.get("prices.auto_fetch", True)))
    if px_auto != bool(c.settings.get("prices.auto_fetch", True)):
        c.settings.save_local({"prices": {"auto_fetch": px_auto}})
        st.rerun()
    sel_year = st.session_state.get("tax_year", c.settings.default_tax_year)
    py = st.selectbox("Steuerjahr für den Kursabruf", c.settings.tax_years,
                      index=c.settings.tax_years.index(sel_year) if sel_year in c.settings.tax_years
                      else len(c.settings.tax_years) - 1, key="px_year")
    if st.button("Kurse jetzt laden"):
        C.fill_prices(int(py))
    up_px = st.file_uploader("Kurse als CSV importieren (Spalten ISIN;Datum;Kurs;Währung)", type=["csv", "txt", "xlsx"],
                             key="px_up")
    px_nav = st.checkbox("Die Datei enthält Rücknahmepreise (NAV) – z. B. von der Fondsgesellschaft", key="px_nav")
    st.download_button("CSV-Vorlage für Kurse", price_csv_template(), file_name="Kurse_Vorlage.csv")
    if up_px and st.button("Kurs-CSV übernehmen"):
        try:
            n = import_price_csv(c.repo, svc, up_px.getvalue(), up_px.name, redemption=px_nav)
            C.invalidate_results()
            st.success(f"{n} Kurse importiert. Für Nichtmeldefonds danach „Kurse jetzt laden“ bzw. Fonds & OeKB → "
                       "Nichtmeldefonds-Kurse nutzen.")
        except (PriceError, ValueError) as exc:
            st.error(str(exc))
    st.subheader("Datenschutz")
    st.write("Es werden keine Dokumente oder Finanzdaten an externe KI-, OCR- oder Cloud-Dienste übertragen. Internetzugriffe "
             "(beide abschaltbar, siehe oben): Download der öffentlichen EZB-Kursdatei und – nur mit API-Schlüssel – "
             "Wertpapierkurse von EODHD (übertragen werden nur ISIN/Kürzel und Zeitraum). Keine Broker-Zugangsdaten werden gespeichert. Streamlit-Telemetrie ist in "
             "`.streamlit/config.toml` abgeschaltet, der Zugriff wird durch die lokale Installation bzw. die Docker-Portfreigabe begrenzt.")
    st.subheader("Backup und Wiederherstellung")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Vollständiges Backup erstellen"):
            try:
                p = create_backup(c.db, c.store)
                st.success(f"Backup gespeichert: {p}")
                C.download_button(p, "bk_dl", "Backup herunterladen")
            except OSError as exc:
                st.error(f"Backup fehlgeschlagen: {exc}")
        backups = sorted((c.store.base / "backups").glob("*.zip"), reverse=True)
        if backups:
            st.caption("Vorhandene Backups")
            C.df([{"Datei": b.name, "Größe KB": round(b.stat().st_size / 1024, 1)} for b in backups])
    with col2:
        up = st.file_uploader("Backup wiederherstellen (.zip)", type=["zip"])
        move = st.checkbox("Bestehende Daten vorher in einen Sicherungsordner verschieben (erforderlich, wenn der "
                           "Ablageordner nicht leer ist)")
        if up and st.button("Wiederherstellen"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as upload:
                upload.write(up.getvalue())
                tmp = Path(upload.name)
            try:
                manifest = verify_backup(tmp)
                base = c.store.base
                c.close()
                shutdown_logging()
                C.reset_context()
                info = restore_backup(tmp, base, move_existing=move)
                st.success(f"{info['files']} Dateien wiederhergestellt (Backup vom {manifest['created_at']}). "
                           f"Vorherige Daten: {info['moved_existing_to'] or '-'}")
            except (BackupError, OSError) as exc:
                st.error(f"Wiederherstellung abgebrochen: {exc}")
                C.reset_context()
            finally:
                tmp.unlink(missing_ok=True)
    st.subheader("Protokolle")
    tabs = st.tabs(["Importläufe", "Änderungsprotokoll", "Anwendungslog", "Steuerregeln"])
    with tabs[0]:
        runs = c.repo.import_runs()
        C.df(runs)
        if runs:
            rid = st.selectbox("Importlauf anzeigen", [r["id"] for r in runs])
            C.df(c.repo.import_log(rid))
    with tabs[1]:
        C.df(c.repo.audit_entries(1000))
    with tabs[2]:
        logf = c.store.base / "logs" / "kest_tool.log"
        if logf.exists():
            st.code("\n".join(logf.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]))
        else:
            st.info("Noch kein Log vorhanden.")
    with tabs[3]:
        rules = load_rules()
        st.caption(f"Regelstand: {rules.last_review}. Datei: src/kest_tool/data/tax_rules.yaml")
        C.df(rules.catalog())
