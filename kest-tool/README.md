# KESt-Tool – Österreichische Kapitalertragsteuer für Wertpapierdepots

Lokale Python-Webanwendung (Streamlit, SQLite) für Windows 11. Sie konsolidiert die steuerlich relevanten Daten
mehrerer Depots (Trade Republic, Scalable Capital, weitere Broker), berechnet sie nachvollziehbar nach
österreichischen Regeln und bereitet sie als **Arbeitshilfe** für die Einkommensteuererklärung (Beilage E 1kv) auf.

> **Wichtig:** Das Programm ist eine Vorbereitungshilfe und ersetzt keine Steuerberatung. Es übermittelt nichts an
> FinanzOnline. Steuerregeln, die nicht belastbar verifiziert werden konnten, werden **nicht** berechnet, sondern als
> „manuell steuerlich zu prüfen“ ausgewiesen. Siehe [Steuerregeln](docs/STEUERREGELN.md) und
> [Einschränkungen](#einschränkungen).

PDFs, ZIP-Archive, CSV- und Excel-Dateien werden manuell heruntergeladen und direkt im Browser über **Dokumente hinzufügen** oder **Import** eingelesen. Ein automatischer Broker-Download ist nicht Bestandteil des Projekts.

Unbekannte PDF-Layouts können optional mit einer **lokalen KI (Ollama)** untersucht werden.
Belegbare Vorschläge lassen sich direkt neben dem Original prüfen und ins Formular übernehmen;
sie werden nie automatisch gebucht. [Einrichtung und Grenzen](docs/LOKALE-KI.md).

Der gemeinsame Upload startet direkt nach dem Hinzufügen der Dateien. Importtyp, erkannte Spalten und
eindeutige Broker/Depots werden automatisch zugeordnet. CSV-Vorspann, wiederholte Tabellenabschnitte,
mehrere Excel-Blätter und OeKB-Tabellen werden berücksichtigt. Eindeutige Bruttobuchungen werden übernommen;
unklare Brutto-/Nettobeträge, fehlende Währungen, beschädigte Tabellen und mehrdeutige Depotzuordnungen bleiben
mit Begründung zur Prüfung erhalten. Bereits vorhandene offene Tabellen können erneut hochgeladen werden;
erkannte Dubletten werden nicht erneut gebucht. Manuelle Sonderimporte sind optional eingeklappt.

**Neu in 1.2.0: direkt am Beleg bearbeiten.** Upload-Ergebnisse und **Belege & Prüfung** zeigen das Original
links und bearbeitbare Werte rechts. Keine Belegauswahl und kein Fensterwechsel nötig. Fehlende Angaben bleiben
leer; manuell ergänzte Werte lassen sich nach Originalabgleich abschließen. Vorhandene Buchungen werden an
derselben Stelle korrigiert. [Bedienung und öffentliche Layouttests](docs/DIREKTE-BELEGPRUEFUNG.md).

---

Quellenstand und Änderungen vom 16.10.2026: [Verifikationsbericht](docs/VERIFIKATION-2026-10-16.md).

## Inhalt

1. [Installation unter Windows 11](#installation-unter-windows-11)
2. [Start](#start)
3. [Ablageordner](#ablageordner)
4. [Bedienung](#bedienung)
5. [Excel-Export](#excel-export)
6. [Importformate](#importformate)
7. [Steuerberechnung](#steuerberechnung)
8. [OeKB-Daten](#oekb-daten)
9. [Datenschutz und Sicherheit](#datenschutz-und-sicherheit)
10. [Architektur](#architektur)
11. [Tests](#tests)
12. [Einschränkungen](#einschränkungen)

---

## Installation unter Windows 11

Voraussetzungen: Windows 11, **Python 3.12** (3.13 funktioniert ebenfalls), Internet für die einmalige Installation.
Administratorrechte sind nicht nötig.

1. Python von <https://www.python.org/downloads/windows/> installieren und dabei „Add python.exe to PATH“ aktivieren.
2. Das Repository klonen bzw. entpacken und in den Ordner `kest-tool` wechseln.
3. **`install.bat`** doppelklicken. Das Skript
   - sucht Python 3.12/3.13 und legt die virtuelle Umgebung `.venv` an,
   - installiert die Abhängigkeiten aus `requirements.txt`,
   - legt den Ablageordner samt Datenbank an,
   - führt einen schnellen Selbsttest aus.

Manuelle Installation:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

## Start

**`start.bat`** doppelklicken. Die Oberfläche öffnet sich im Browser unter <http://localhost:8501>. Sie ist nur lokal
erreichbar (`127.0.0.1`). Zum Beenden das Konsolenfenster schließen.

Die Datenbank wird beim ersten Start automatisch angelegt.

Demo ohne echte Daten: `.venv\Scripts\python -m kest_tool.demo C:\Temp\KESt-Demo` (vorher `set PYTHONPATH=src`)
erzeugt eine eigene Demo-Ablage. Danach mit `set KEST_TOOL_HOME=C:\Temp\KESt-Demo` und `start.bat` öffnen.
Musterdateien zum Ausprobieren der Importe liegen in [`sample_data/`](sample_data).

## Ablageordner

Standard: `%USERPROFILE%\Documents\KESt-Tool`. Ändern lässt er sich unter **Einstellungen → Ablageordner**
(gespeichert in `config.local.yaml`) oder über die Umgebungsvariable `KEST_TOOL_HOME`.

```
KESt-Tool/
├── database/kest_tool.db          SQLite-Datenbank
├── config/config.yaml             Kopie der wirksamen Konfiguration
├── documents/<Jahr>/{TradeRepublic,ScalableCapital,OeKB,Other,Unclassified}/
├── imports/<Jahr>/{original,processed,import_logs}/
├── exports/<Jahr>/{excel,pdf,csv,e1kv}/
├── reports/<Jahr>/                PDF-Jahresberichte
├── backups/                       vollständige Backups (ZIP)
└── logs/kest_tool.log             rotierend, redigiert
```

Regeln der Ablage:

- Originaldateien werden byte-identisch kopiert und nie verändert.
- Duplikate werden per SHA-256 erkannt; ein erneuter Import legt keine zweite Datei an.
- Bei Namensgleichheit mit anderem Inhalt wird ein Suffix „(2)“ angehängt. Es wird nie überschrieben.
- Dateinamen werden für Windows bereinigt (ungültige Zeichen, `CON`/`NUL` …). Alle Pfade werden gegen den
  Ablageordner geprüft (Schutz vor Pfadmanipulation).
- Umkategorisieren (Jahr, Quelle, Typ) verschiebt nur die Datei. Der Inhalt bleibt gleich, der Vorgang wird
  protokolliert.
- Liegt der Ablageordner in OneDrive, warnt die Oberfläche.

## Bedienung

**In drei Schritten:**

1. **Schnellstart** auf der Übersicht: Broker anhaken (Trade Republic, Scalable Capital, anderer) → Depots werden
   angelegt. Das geht auch automatisch: Lädt man Abrechnungen hoch, legt das Tool erkannte Broker samt Depot selbst an.
2. **Dokumente hinzufügen** (Übersicht): PDFs, ZIP-Archive (z. B. vom manuellen Broker-Downloads) und CSV-Dateien in
   *ein* Feld ziehen. Jedes PDF wird gelesen und geprüft. Ist alles sicher erkannt und stimmig, entsteht automatisch
   eine Buchung. Alles andere landet unter **Dokumente → Zu prüfen**, mit Prüfbericht und „Was tun?“.
3. **Status und Datenprüfung** auf der Übersicht abarbeiten (jeweils mit „Beheben“-Link), dann **Excel-Export**.

Die Navigation folgt diesen Schritten: *Daten erfassen* (Import, Dokumente, Transaktionen) → *Daten ergänzen*
(Wertpapiere, Fonds & OeKB, Broker & Depots) → *Ergebnis* (Steuerberechnung, Exporte).

**Prüfbericht je Dokument:** Jedes PDF wird mehrfach geprüft. Jede Prüfung zeigt ✅/ℹ️/⚠️/❌ und bei Problemen einen
konkreten Hinweis „Was tun?“. Fehler und Warnungen verhindern die automatische Buchung. Geprüft wird:

- Pflichtfelder je Buchungsart, mit Konfidenz
- eindeutige ISIN mit gültiger Prüfziffer
- Datum plausibel (nicht in der Zukunft)
- Stück × Kurs = Kurswert
- Endbetrag = Kurswert ± Gebühren und Steuern, bei Dividenden einschließlich Devisenkurs
- Quellensteuersatz plausibel und Quellenstaat vorhanden
- Gebühren nicht ungewöhnlich hoch

Sonderfälle werden erkannt und nie automatisch gebucht:

- **Storno** – die ursprüngliche Buchung muss korrigiert werden
- **Kapitalmaßnahmen** (Split, Abspaltung, Umtausch …)
- **Steuerkorrekturen**
- **deutsche Abzugsteuern** (Kapitalertragsteuer/Solidaritätszuschlag/Kirchensteuer): Sie werden *nicht* als
  österreichische KESt übernommen, das Tool weist auf eine mögliche Erstattung hin

Reine Informationsdokumente (Kosteninformation, Depot-/Kontoauszug, deutsche Vorabpauschale) werden als Beleg
abgelegt.

**Datenprüfung:** Die Übersicht listet Lücken, die das Ergebnis verfälschen können:

- fehlende Depot-Steuereinstellungen für das Jahr
- ungeprüfte Wertpapier-Einstufungen
- Fonds ohne Meldefondsstatus
- Quellensteuer ohne Quellenstaat
- Buchungen mit Prüfkennzeichen
- offene Konflikte
- Verkäufe ohne Kaufhistorie

**Wertpapiere ergänzen:** Eine Tabelle zeigt alle offenen Wertpapiere zum gemeinsamen Ausfüllen. Vorschläge (Art aus
dem Namen, Sitzstaat aus dem ISIN-Länderkürzel) sind nur Hilfen. Als geprüft gilt eine Zeile erst mit Quellenangabe.

**Verständliche Meldungen:** Prüfhinweise der Steuerberechnung haben eine Spalte „Was tun?“ und Links zur
richtigen Seite, auch im Excel-Prüfprotokoll. Eingabefehler werden je Feld auf Deutsch angezeigt. Unerwartete
Fehler zeigen eine verständliche Seite mit Hinweis statt eines technischen Tracebacks; die Details stehen im
Anwendungslog.

| Seite | Funktionen |
|---|---|
| **Übersicht** | Schnellstart, Dokumente hinzufügen, Status und Datenprüfung mit „Beheben“-Links, Kennzahlen, Excel-Export |
| **Import (erweitert)** | CSV/Excel mit Spaltenzuordnung und Vorschau, OeKB-CSV/PDF, Belege, Ordnerimport |
| **Dokumente** | Reiter „Zu prüfen“ (alle Jahre) mit Prüfbericht und Formular; „Alle Dokumente“ mit Filtern, Original öffnen, Zuordnen, Verschieben |
| **Transaktionen** | Filter, manuelle Buchungen und Korrekturen (Begründung Pflicht), Ertragsart bestätigen, Devisenkurse ergänzen |
| **Wertpapiere** | Offene Wertpapiere tabellarisch ergänzen, Einzelbearbeitung, Kurssymbol |
| **Fonds & OeKB** | Fondsmeldungen, Konflikte, manuelle Erfassung, Rücknahmepreise für Nichtmeldefonds |
| **Broker & Depots** | Depots, Steuereinstellungen je Jahr (mit Erklärung), Importhistorie |
| **Steuerberechnung** | Ergebnisse nach Kategorie, Rechenschritte, Verlustausgleich, E 1kv, Prüfhinweise mit „Was tun?“ |
| **Exporte** | Excel, CSV, PDF-Jahresbericht, E 1kv-Arbeitshilfe, Exporthistorie |
| **Einstellungen** | Ablageordner, Jahre, Devisen- und Wertpapierkurse, Backup, Protokolle, Regelkatalog |

**Status:** Dashboard und Steuerberechnung zeigen einen Statusblock, der Folgendes ausweist:

- ob Depots angelegt sind
- wie viele Buchungen das gewählte Jahr hat und in welchen Jahren es Daten gibt
- wie viele Dokumente noch ohne Buchung sind
- wie viele Steuerpositionen berechnet (🟢), vorläufig (🟡) bzw. manuell zu prüfen (🔴) sind

Wird nichts berechnet, steht dort der Grund und der nächste Schritt. Das Steuerjahr steht beim Start auf dem
jüngsten Jahr mit Buchungen.

**Automatische Verarbeitung von PDFs:** Vollständig erkannte Abrechnungen (alle Pflichtwerte sicher, keine
Widersprüche) werden beim PDF- und Ordnerimport automatisch zu Buchungen. Bereits abgelegte Dokumente lassen sich
über „offene PDFs automatisch verarbeiten“ (Dashboard/Dokumente) nachträglich verarbeiten; dabei wird neu
ausgelesen. Das Depot ergibt sich aus dem erkannten Broker, wenn dieser genau ein Depot hat, sonst gilt das gewählte
Standarddepot. Unvollständige Dokumente bleiben mit Grund im Status „pruefen“.

**Devisenkurse:** Fehlen bei Fremdwährungsbuchungen die Kurse, ergänzt das Tool sie automatisch mit den
**Euro-Referenzkursen der EZB** (<https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip>). Das passiert beim
Öffnen des Dashboards, nach Importen und auf Knopfdruck (Dashboard, Transaktionen, Einstellungen).

- Ist für das Buchungsdatum kein Kurs veröffentlicht (Wochenende, Feiertag), gilt der letzte Bankarbeitstag davor,
  höchstens 7 Tage zurück.
- Kurse aus dem Beleg haben immer Vorrang und werden nie überschrieben.
- Jeder ergänzte Kurs wird mit Quelle und Kursdatum gespeichert, im Änderungsprotokoll vermerkt und im Excel-Export
  in der Spalte „Kursquelle“ ausgewiesen.
- Heruntergeladen wird nur die öffentliche Kursdatei. Es werden keine eigenen Daten übertragen.
- Abschaltbar ist das unter **Einstellungen → Devisenkurse** oder in `config.yaml` (`fx.auto_fetch: false`). Die
  Datei lässt sich dort auch manuell importieren.
- Ob der EZB-Referenzkurs steuerlich der maßgebliche Kurs ist, ist nicht verifiziert (Regel `FX_CONVERSION`).
  Positionen in Fremdwährung bleiben deshalb „vorläufig“.

**Wertpapierkurse:** Für Nichtmeldefonds (erster und letzter Kurs des Kalenderjahres) und für die Bewertung der
Bestände zum 31.12. lädt das Tool Kurse automatisch über den Kursdienst **EODHD** (<https://eodhd.com>). Er findet
Wertpapiere direkt über die ISIN; das Tool bevorzugt dabei Euro-Notierungen (XETRA, Frankfurt, Wien …).

- **Voraussetzung:** ein persönlicher API-Schlüssel, unter **Einstellungen → Wertpapierkurse** eingetragen. Er wird
  nur lokal in `.env` gespeichert.
- **Kostenloser Zugang:** laut Anbieter 20 Abrufe pro Tag und Kurse des letzten Jahres. Ältere Jahre brauchen einen
  bezahlten Zugang oder den CSV-Import (Vorlage in den Einstellungen).
- **Übertragen** werden nur ISIN bzw. Börsenkürzel und der Zeitraum, keine Bestände oder Beträge.
- **Kurssymbol:** Das Tool wählt es automatisch und protokolliert die Zuordnung. Unter **Wertpapiere** lässt es sich
  überschreiben (z. B. `EUNL.XETRA`).
- **Keine Überschreibungen:** Bereits erfasste Kurse für Nichtmeldefonds werden nie überschrieben; abweichende
  Werte erscheinen als Konflikt zur Entscheidung.
- **Rücknahmepreise für Nichtmeldefonds:** Die Pauschalregel verlangt Rücknahmepreise. Das Tool nimmt diese
  Reihenfolge:
  1. bereits importierte Rücknahmepreise, z. B. eine CSV der Fondsgesellschaft (beim Import „Rücknahmepreise (NAV)“
     anhaken)
  2. Rücknahmepreise (NAV) über EODHD „EUFUND“ (Ticker = ISIN.EUFUND); laut Anbieter erst ab dem kostenpflichtigen
     Paket „All World Extended“
  3. ersatzweise Börsenschlusskurse, gekennzeichnet mit „kein Rücknahmepreis“; abschaltbar in den Einstellungen

  Fremdwährungspreise erhalten automatisch den EZB-Kurs zum letzten Preisdatum. Alle geladenen Werte bleiben
  „ungeprüft“.
- **Bewertung zum 31.12.:** Kurs, Wert in EUR und unrealisiertes Ergebnis stehen in der Bestandsübersicht. Sie dienen
  nur zur Information und sind nicht steuerrelevant.
- **Inoffizielle Kursquellen** (z. B. Yahoo Finance) werden wegen ihrer Nutzungsbedingungen nicht verwendet.

Empfohlener Ablauf: Broker und Depots anlegen → Depot-Steuereinstellungen für das Jahr setzen → Transaktionen
importieren (am besten die **gesamte Historie**, damit die Anschaffungskosten stimmen) → Wertpapiere einstufen →
OeKB-Meldungen erfassen → Steuerberechnung prüfen → Excel-Export.

## Excel-Export

**Exporte → Excel-Datei erstellen** (oder die Schaltfläche im Dashboard). Die Datei
`KESt_Auswertung_<Steuerjahr>_<Exportdatum>.xlsx` wird unter `exports/<Jahr>/excel` dauerhaft gespeichert und in der
Exporthistorie mit SHA-256 erfasst. Bestehende Dateien werden nie überschrieben.

Tabellenblätter: Steuerübersicht · Alle Transaktionen · Dividenden und Ausschüttungen · Fonds und OeKB ·
Nichtmeldefonds · REITs und BDCs · Verlustausgleich · Steuerberechnung · E1kv - FinanzOnline (Excel erlaubt kein
„/“ im Blattnamen) · Prüfprotokoll · Dokumentenverzeichnis.

Gestaltung:

- Kopfzeilen sind formatiert und fixiert, Autofilter ist aktiv, Spaltenbreiten sind gesetzt.
- Datums-, Euro- und Prozentformate werden verwendet, negative Beträge erscheinen rot.
- Summenzeilen nutzen `=SUBTOTAL(9; …)`, damit sie Filter berücksichtigen und nachvollziehbar bleiben.
- Statusfarben: grün = belegt und geprüft, gelb = vorläufig/ungeprüft, rot = fehlt bzw. manuell zu prüfen.
- Fehlende Werte stehen als „FEHLT“, ungeprüfte als „UNGEPRÜFT“ in der Zelle.
- Die Übersicht zeigt „Gesamt (inkl. vorläufig)“ und „davon gesichert“ getrennt.

## Importformate

| Format | Status |
|---|---|
| CSV (`;` `,` Tab `\|`, UTF-8/UTF-16/Windows-1252, deutsche und englische Zahlen- und Datumsformate) | getestet mit synthetischen Dateien |
| Excel `.xlsx` | getestet |
| PDF-Abrechnungen (Kauf, Verkauf, Dividende, Ausschüttung, Zinsen, Kapitalrückzahlung) | getestet mit synthetischen Muster-PDFs, nachgebildeten Layouts und unveränderten öffentlichen Broker-Textauszügen (Trade-Republic-Positionszeile, Baader/Scalable „STK“ und „EUR 126,30“, Quellensteuer „für US-Emittent“, Devisenkurs „EUR/USD“) – Original-PDF-Extraktion echter Kundendokumente weiterhin offen |
| Jahressteuerbescheinigungen, sonstige Belege | werden abgelegt und als „prüfen“ markiert, aber nicht automatisch in Buchungen zerlegt |
| OeKB-Fondsdaten CSV/Excel | getestet mit eigenem Beispielformat ([sample_data](sample_data)); Spalten frei zuordenbar |
| OeKB-PDF | heuristische Extraktion mit Bestätigungsformular, getestet nur mit Muster-PDF |

CSV: Spalten werden über Synonyme automatisch erkannt und lassen sich manuell zuordnen. Zuordnungen können als Profil
gespeichert werden. Unbekannte Buchungsarten ordnen Sie in einer Tabelle zu. Beträge lassen sich als brutto oder
netto interpretieren. Fremdwährungen ohne Devisenkurs werden gemeldet.

PDF: Jedes Feld erhält eine Konfidenz. Fehlende Pflichtwerte, Widersprüche (z. B. Stück × Kurs ≠ Kurswert) und
gescannte PDFs ohne Text führen zur manuellen Prüfung. Eine Buchung entsteht erst nach Bestätigung im Formular, und
der Dokumentstatus wird nur bei vollständiger und abgeglichener Extraktion „verarbeitet“.

Dubletten werden auf drei Ebenen erkannt:

- Datei: SHA-256.
- Buchung, exakt: Fingerabdruck aus Depot, Art, Datum, ISIN, Stück, Betrag und Währung.
- Buchung, möglich: gleiches Depot, gleiche Art und ISIN, ±3 Tage, Betragsabweichung höchstens 0,5 %.

Je Zeile entscheiden Sie: übernehmen, ignorieren oder prüfen. Jede Buchung verweist auf ihr Ursprungsdokument und
ihre Zeile.

## Steuerberechnung

Modular in `src/kest_tool/tax/engine.py`, versionierte Regeln in
[`src/kest_tool/data/tax_rules.yaml`](src/kest_tool/data/tax_rules.yaml), Dokumentation in
[docs/STEUERREGELN.md](docs/STEUERREGELN.md) (erzeugt mit `python scripts/generate_rules_doc.py`).

Jede Rechenposition enthält:

- Ausgangsdaten und Herkunft (Buchung, Datei, Zeile)
- angewendete Regeln mit Status und Quellen
- Steuersatz und Rechenschritte
- Ergebnis und Steuerjahr
- Status: **berechnet** (Regel offiziell belegt, Daten geprüft), **vorläufig** oder **manuell prüfen** (kein Betrag)

Umgesetzt:

- **Aktien:** Anschaffungskosten nach gleitendem Durchschnittspreis je Depot und Wertpapier. Gebühren werden nicht
  abgezogen (§ 27a Abs 4 Z 2, § 20 Abs 2 EStG), sondern nur ausgewiesen. Realisierte Gewinne und Verluste,
  Dividenden brutto, Splits.
- **Quellensteuer:** getrennt gespeichert. Anrechenbar ist höchstens der DBA-Satz und höchstens die österreichische
  Steuer. Nicht anrechenbare und ungeklärte Beträge werden getrennt ausgewiesen. Für gewöhnliche Dividenden natürlicher Personen sind die DBA-Höchstsätze für
  **USA, Deutschland, Schweiz, Niederlande und Kanada** mit amtlichen Quellen hinterlegt. Andere Länder und
  Sonderfälle bleiben zur Prüfung offen. Dividendensätze gelten nicht automatisch für Zinsen.
- **Inländische KESt:** Depots mit KESt-Abzug durch den Broker gelten als „inländisch“. Die einbehaltene KESt wird
  ausgewiesen (KZ 899) und nicht doppelt besteuert.
- **Meldefonds:** ausschüttungsgleiche Erträge, steuerpflichtiger Teil der Ausschüttung, anrechenbare Steuer und
  AK-Korrektur laut OeKB-Meldung, jeweils für den Bestand zum Meldedatum. Ausschüttungen ohne Meldung werden voll,
  aber vorläufig angesetzt. Eine manuell gebuchte AgE neben einer Meldung wird nicht doppelt gezählt.
- **Nichtmeldefonds:** Pauschale (90 % der Differenz, mindestens 10 % des letzten Rücknahmepreises) **für 2022–2026**; die Fassung ab 2024 wurde anhand des RIS-Volltexts bestätigt.
  Fehlende Kurse oder Devisenkurse verhindern die Berechnung. Selbstnachweise und unterjährige Sonderfälle
  bleiben manuell zu prüfen.
- **REITs/BDCs:** keine Einstufung über den Namen. Ohne je Buchung bestätigte Ertragsart wird der Betrag „ungeklärt“
  und nicht berechnet.
- **Kapitalrückzahlungen:** Mit bestätigtem Beleg mindern sie die Anschaffungskosten, ein Überschuss gilt als
  Gewinn. Ohne Beleg werden sie „ungeklärt“ ausgewiesen.
- **Verlustausgleich:** nur innerhalb der 27,5-%-Gruppe desselben Jahres. Kein Ausgleich mit 25-%-Bankzinsen, kein
  Verlustvortrag. Führt ein Broker selbst einen Verlustausgleich durch, wird zuerst depotintern verrechnet. Zu jeder
  Verrechnung werden ursprünglicher, verrechneter und verfallener Betrag sowie die Begründung ausgewiesen.
- **Steuerjahre:** Jede Regel hat einen Status je Jahr. Für nicht hinterlegte Jahre (z. B. 2019) lehnt das Tool die
  Berechnung ab.
- **E 1kv:** Kennzahlen 2022–2024 aus Auszügen der amtlichen Formulare (862/863, 897/898, 936/937, 981/994, 891/892,
  899). KZ 998 sowie 860/861 sind nur sekundär belegt. Für **2025 wurden Kennzahlen und Spalten am amtlichen Originalformular verifiziert**, einschließlich
  der getrennten Quellensteuer-Kennzahlen 984/998 und der Derivate-Kennzahlen. Für **2026 fehlt ein abrufbares
  amtliches Formular**; Kennzahlen 2025 erscheinen ausschließlich als unverifizierte Planungshinweise „(863?)“.

## OeKB-Daten

- **Automatischer Weg:** Eine öffentlich dokumentierte, frei nutzbare OeKB-Schnittstelle für steuerliche
  Fondsmeldungen konnte **nicht verifiziert** werden. Die OeKB bietet Fondsdaten über my.oekb.at bzw. vertragliche
  Datenlieferungen (Fondsdaten-Portal mit Nutzungsbedingungen, „Fondsdaten Plus“) an. Die Schnittstelle
  `AutomaticProvider` ist vorbereitet, aber ohne Anbieter. Die Oberfläche zeigt das transparent an, und es wird
  keine API vorgetäuscht.
- **Manueller Weg:** Import von CSV/Excel oder PDF sowie manuelle Erfassung, jeweils mit ISIN, Meldedatum
  (= Steuerjahr), Quelle, Importdatum, Version und Prüfstatus.
- **Konflikte:** Eine abweichende neue Meldung wird nicht aktiv geschaltet, sondern als Konflikt angelegt. Die
  Entscheidung (bestehend behalten oder neu übernehmen) braucht eine Begründung und wird protokolliert. Die nicht
  gewählte Version bleibt erhalten.

## Datenschutz und Sicherheit

- Alles läuft lokal (Streamlit auf `127.0.0.1`, Telemetrie aus in `.streamlit/config.toml`).
- Es werden keine Broker-Passwörter gespeichert und es gibt kein automatisches Einloggen. Das KESt-Tool fragt keine
  Zugangsdaten ab.
- Es werden keine Daten an externe Dienste, KI oder OCR übertragen; die PDF-Texterkennung läuft lokal. Einziger
  Internetzugriffe sind der Download der öffentlichen EZB-Kursdatei und – nur mit eigenem API-Schlüssel – der
  Wertpapierkursabruf bei EODHD (nur ISIN/Kürzel und Zeitraum); beides ist abschaltbar.
- Die Konfiguration lehnt Schlüssel wie `password`, `token` oder `api_key` ab. Optionale Variablen stehen in `.env`
  (siehe `.env.example`).
- Logs werden redigiert (Tokens, Cookies, signierte URLs, Telefonnummern); das KESt-Tool schreibt keine Buchungsdetails ins Log.
- Uploads werden validiert: erlaubte Endungen, Größenlimit, PDF/XLSX-Signatur. Dateiinhalte werden nie ausgeführt;
  PDFs werden nur als Text gelesen.
- Backups sind ZIP-Dateien mit SHA-256-Manifest, die Wiederherstellung prüft jede Datei, mit Zip-Slip-Schutz.
  Eine nicht leere Ablage wird nur nach ausdrücklicher Bestätigung vollständig in einen Sicherungsordner verschoben,
  es wird nichts gelöscht.
- Empfehlung: BitLocker aktivieren und den Ablageordner nicht in einem Cloud-Sync-Ordner führen.

## Architektur

```
app.py                         Streamlit-Einstieg, Navigation
src/kest_tool/
  config.py                    config.yaml + config.local.yaml + KEST_TOOL_HOME
  db.py / repository.py        SQLite-Schema, Repository, Audit-Log, Konflikte
  models.py                    Enums + pydantic-Modelle (Validierung)
  fx.py                        EZB-Referenzkurse (Download, Cache, Import, Ergänzen fehlender Kurse)
  prices.py                    Wertpapierkurse (EODHD per ISIN, CSV-Import, Nichtmeldefonds, Bewertung 31.12.)
  processing.py                Upload (PDF/ZIP/CSV), Stapelverarbeitung, automatische Depots, „Was tun?“
  ui/guide.py                  Schnellstart, zentraler Upload, Datenprüfung, Prüfbericht
  storage.py                   Dokumentenablage (SHA-256, kein Überschreiben, Pfadschutz)
  security.py                  Dateinamen-/Pfadschutz, Log-Redaktion
  importers/                   parsing, csv_importer, pdf_importer, oekb_importer
  tax/rules.py, data/tax_rules.yaml   versionierte Regeln, Quellen, E 1kv-Kennzahlen
  tax/engine.py                CostBasisTracker, IncomeClassifier, FundProcessor, LossOffset, Summary, E 1kv
  export/excel.py, reports.py  Excel (11 Blätter), CSV, PDF-Bericht, E 1kv-Hilfe
  backup.py                    Backup/Wiederherstellung
  demo.py                      synthetische Beispieldaten
  ui/                          Streamlit-Seiten
```

Datenbanktabellen:

- `brokers`, `depots`, `depot_tax_settings` (je Jahr), `securities`
- `transactions`, `documents`, `document_links`, `document_events`
- `import_runs`, `import_log`
- `fund_reports`, `nmf_prices`, `conflicts`
- `audit_log`, `csv_profiles`, `exports`

## Tests

```bat
.venv\Scripts\python -m pytest -q
```

`tests/` enthält automatisierte Regressionen; die aktuelle Anzahl zeigt `python -m pytest -q`.
Zusätzlich prüft `python scripts/validate_broker_corpus.py tests/public_layout_manifest.json --public`
fünf unveränderte öffentliche Broker-Textauszüge anhand festgelegter Quellen und Prüfsummen. Sie decken unter anderem ab:

- CSV mit deutschem Dezimalkomma und erneuten Import
- Brokerzuordnung, Dubletten und Gebühren
- Verkauf mit bekannten Anschaffungskosten und Dividende mit Quellensteuer
- Meldefonds und Nichtmeldefonds, AgE und Schutz vor Doppelzählung von Fondserträgen
- Kapitalrückzahlung und eingeschränkten Verlustausgleich
- fehlende Daten, verweigerte Steuerjahre und nicht verifizierte Regeln (Warnung statt Betrag)
- alle Excel-Blätter und Abgleich der Excel-Summen mit der Datenbank
- Ablage, Backup und Wiederherstellung sowie einen UI-Rauchtest aller Seiten

## Einschränkungen

- **Verifikation:** E 1kv 2025, die Nichtmeldefonds-Regel ab 2024 und zusätzliche DBA-Sätze wurden am
  16.10.2026 im amtlichen Volltext geprüft. Der Quellenstatus anderer Regeln bleibt unverändert.
  Details und verbleibende Grenzen: [Verifikationsbericht](docs/VERIFIKATION-2026-10-16.md).
- **E 1kv 2026:** amtliches Formular nicht abrufbar; keine bestätigten Kennzahlen. 2025 ist verifiziert.
- **Nichtmeldefonds:** jährliche Pauschale auch 2024–2026; Sonderfälle und fehlende Daten bleiben prüfpflichtig.
- **DBA-Sätze:** USA, DE, CH, NL und CA für gewöhnliche Privatdividenden; übrige Länder/Sonderfälle offen.
- **Nicht implementiert:**
  - Regelbesteuerungsoption, unverbriefte Derivate/Shorts, Kryptowährungen, Anleihen-Stückzinsen,
    vollständige Berechnung gemischter Alt-/Neubestände
  - pauschale Anschaffungskosten (§ 93 Abs 4), Wegzug/Schenkung, Kapitalmaßnahmen außer Split
    (werden als Prüfhinweis gemeldet)
  - Immobilienfonds, Betriebsvermögen
- **Reihenfolge des Verlustausgleichs:** Annahme zugunsten der Quellensteueranrechnung; die angezeigte anrechenbare
  Quellensteuer nach Verlustausgleich ist eine Schätzung, maßgeblich ist der Bescheid.
- **Wertpapierkurse:** Der EODHD-Abruf wurde nur gegen simulierte Antworten im dokumentierten Format getestet, weil
  der Dienst aus der Entwicklungsumgebung nicht erreichbar war. Das gilt auch für die Rücknahmepreise über „EUFUND“
  (kostenpflichtiges Paket). Ohne diesen Zugang bleiben der CSV-Import von Rücknahmepreisen oder der gekennzeichnete
  Ersatz durch Börsenkurse.
- **Fremdwährungen:** Kurs aus Beleg, Eingabe oder automatisch als EZB-Referenzkurs. Der Download wurde nur gegen eine
  Datei im EZB-Format getestet, weil die EZB aus der Entwicklungsumgebung nicht erreichbar war.
- **PDF-Erkennung:** synthetische PDF-Tests und reproduzierbarer Abgleich unveränderter öffentlicher
  Broker-Textauszüge. Original-PDF-Extraktion/OCR mit echten Kundendokumenten ist weiterhin nicht verifiziert.
  Der lokale Korpus-Runner erlaubt den Abgleich eigener anonymisierter PDFs ohne Dokumentupload.
- **Windows:** `start.bat`/`install.bat` wurden in einer Linux-Umgebung erstellt und nicht unter Windows ausgeführt.
  Python-Tests werden jetzt auch unter Windows ausgeführt; CI prüft Linux und Windows mit Python 3.12.
  Die Batch-Installation selbst bleibt separat zu testen.


## Ergänzungen vom 16.10.2026

- Öffentlich begebene verbriefte Derivate: Long-Verkäufe/Rückzahlungen nach explizit geprüfter Einstufung mit Emittentenquelle, eigene E-1kv-Kennzahlen für 2025. Unverbriefte Derivate bleiben manuell.
- Historische Erwerbe und ungeklärte Kapitalmaßnahmen sperren abhängige Verkaufsberechnungen. Keine automatische Annahme einer Steuerbefreiung.
- Bei Käufen/Verkäufen am selben Tag unter **Buchungen → Weitere Spalten anzeigen → Reihenfolge am Tag** die tatsächliche Ausführungsreihenfolge je Depot/ISIN eintragen. Ohne eindeutige Reihenfolge wird kein Verkaufsgewinn geraten.
- Fehlende historische Fondskorrekturen und ungeprüfte AK-Quellen bleiben in Verkäufen und Beständen sichtbar.
- Formelzeichen aus importierten Texten bleiben in Excel Text; CSV-Exporte neutralisieren entsprechende Präfixe.
