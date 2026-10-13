# KESt-Tool – Österreichische Kapitalertragsteuer für Wertpapierdepots

Lokale Python-Webanwendung (Streamlit, SQLite) für Windows 11. Sie konsolidiert die steuerlich relevanten Daten
mehrerer Depots (Trade Republic, Scalable Capital, weitere Broker), berechnet sie nachvollziehbar nach
österreichischen Regeln und bereitet sie als **Arbeitshilfe** für die Einkommensteuererklärung (Beilage E 1kv) auf.

> **Wichtig:** Das Programm ist eine Vorbereitungshilfe und ersetzt keine Steuerberatung. Es übermittelt nichts an
> FinanzOnline. Steuerregeln, die nicht belastbar verifiziert werden konnten, werden **nicht** berechnet, sondern als
> „manuell steuerlich zu prüfen“ ausgewiesen. Siehe [Steuerregeln](docs/STEUERREGELN.md) und
> [Einschränkungen](#einschränkungen).

Das KESt-Tool ist ein eigenständiges Projekt. Der **Broker Document Collector** im Nachbarordner
[`../broker-document-collector`](../broker-document-collector) ist ein separates Werkzeug zum Herunterladen der
Broker-Dokumente. Es wird nicht benötigt; seinen Ausgabeordner (oder jeden anderen Ordner mit PDFs/CSVs) kann das
KESt-Tool aber über **Import → Ordner einlesen** übernehmen.

---

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

| Seite | Funktionen |
|---|---|
| **Dashboard** | Steuerjahr, Anzahl Broker/Depots/Dokumente/Transaktionen, Erträge, Gewinne/Verluste, Quellensteuer, offene Prüfungen, letzter Import, Excel-Export |
| **Broker & Depots** | Broker und Depots anlegen und deaktivieren. **Je Steuerjahr** festlegen, ob der Broker österreichische KESt abführt bzw. einen Verlustausgleich durchführt (wichtig gegen Doppelzählungen). Importhistorie |
| **Import** | CSV/Excel mit Spaltenzuordnung und Vorschau, PDF-Abrechnungen mit Prüfformular, Belege (z. B. Jahressteuerbescheinigung), OeKB-CSV/PDF, Ordnerimport. Dublettenentscheidung je Zeile, Fehler-/Importprotokoll |
| **Transaktionen** | Filter, manuelle Buchungen und Korrekturen (Begründung ist Pflicht, Audit-Log), Ertragsart bestätigen (z. B. Kapitalrückzahlung, REIT-Bestandteile) |
| **Wertpapiere** | Suche nach ISIN, Name oder Ticker. Wertpapierart, steuerliche Einstufung, Meldefondsstatus, jeweils mit Quelle und Prüfstatus |
| **Fonds & OeKB** | Fondsmeldungen, Prüfstatus, Konfliktentscheidungen, manuelle Erfassung, Kursdaten für Nichtmeldefonds |
| **Dokumente** | Filter nach Jahr, Broker, Typ und Status. Original öffnen oder herunterladen, kategorisieren, Transaktionen zuordnen, PDF-Extraktion prüfen |
| **Steuerberechnung** | Ergebnisse nach Kategorie, Rechenschritte und Quellen je Position, Verlustausgleich, Fonds, E 1kv, Prüfhinweise, Regeln |
| **Exporte** | Excel, CSV, PDF-Jahresbericht, E 1kv-Arbeitshilfe, Exporthistorie, gespeicherte Dateien öffnen |
| **Einstellungen** | Ablageordner, Steuerjahre, Währungen, Importoptionen, Backup/Wiederherstellung, Protokolle, Regelkatalog |

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
| PDF-Abrechnungen (Kauf, Verkauf, Dividende, Ausschüttung, Zinsen, Kapitalrückzahlung) | getestet **nur mit synthetischen Muster-PDFs** und nachgebildeten Layouts (Trade-Republic-Positionszeile, Baader/Scalable „STK“ und „EUR 126,30“, Quellensteuer „für US-Emittent“, Devisenkurs „EUR/USD“) – keine echten Abrechnungen |
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
  Steuer. Nicht anrechenbare und ungeklärte Beträge werden getrennt ausgewiesen. Bisher ist nur der DBA-Satz für
  die **USA** als verifiziert hinterlegt; für andere Länder bleibt die Anrechnung „ungeklärt“, bis Sie den Satz
  geprüft eintragen.
- **Inländische KESt:** Depots mit KESt-Abzug durch den Broker gelten als „inländisch“. Die einbehaltene KESt wird
  ausgewiesen (KZ 899) und nicht doppelt besteuert.
- **Meldefonds:** ausschüttungsgleiche Erträge, steuerpflichtiger Teil der Ausschüttung, anrechenbare Steuer und
  AK-Korrektur laut OeKB-Meldung, jeweils für den Bestand zum Meldedatum. Ausschüttungen ohne Meldung werden voll,
  aber vorläufig angesetzt. Eine manuell gebuchte AgE neben einer Meldung wird nicht doppelt gezählt.
- **Nichtmeldefonds:** Pauschale (90 % der Differenz, mindestens 10 % des letzten Rücknahmepreises) **nur für 2022
  und 2023** (sekundär belegt). Ab 2024 wurde § 186 InvFG geändert und der neue Inhalt nicht verifiziert, deshalb
  erfolgt keine Berechnung, nur eine Prüfposition.
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
  899). KZ 998 sowie 860/861 sind nur sekundär belegt. Für **2025/2026 sind die Kennzahlen nicht verifiziert**: Die
  Beträge erscheinen mit dem Vorjahreswert als „(863?)“ und dem Hinweis, das Formular zu prüfen.

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
- Es werden keine Daten an externe Dienste, KI oder OCR übertragen; die PDF-Texterkennung läuft lokal.
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

`tests/` enthält 66 Tests. Sie decken unter anderem ab:

- CSV mit deutschem Dezimalkomma und erneuten Import
- Brokerzuordnung, Dubletten und Gebühren
- Verkauf mit bekannten Anschaffungskosten und Dividende mit Quellensteuer
- Meldefonds und Nichtmeldefonds, AgE und Schutz vor Doppelzählung von Fondserträgen
- Kapitalrückzahlung und eingeschränkten Verlustausgleich
- fehlende Daten, verweigerte Steuerjahre und nicht verifizierte Regeln (Warnung statt Betrag)
- alle Excel-Blätter und Abgleich der Excel-Summen mit der Datenbank
- Ablage, Backup und Wiederherstellung sowie einen UI-Rauchtest aller Seiten

## Einschränkungen

- **Verifikation:** BMF, RIS, Findok und OeKB waren aus der Entwicklungsumgebung nicht direkt abrufbar. Regeln wurden
  über Suchauszüge offizieller Dokumente bzw. Sekundärquellen belegt und entsprechend gekennzeichnet. Vor der
  Verwendung bitte die Quellen in [docs/STEUERREGELN.md](docs/STEUERREGELN.md) selbst prüfen.
- **E 1kv 2025/2026:** Kennzahlen nicht verifiziert.
- **Nichtmeldefonds ab 2024:** keine Berechnung.
- **DBA-Sätze:** nur USA verifiziert.
- **Nicht implementiert:**
  - Regelbesteuerungsoption, Derivate, Kryptowährungen, Anleihen-Stückzinsen, Altbestand vor 1.4.2012
  - pauschale Anschaffungskosten (§ 93 Abs 4), Wegzug/Schenkung, Kapitalmaßnahmen außer Split
    (werden als Prüfhinweis gemeldet)
  - Immobilienfonds, Betriebsvermögen
- **Reihenfolge des Verlustausgleichs:** Annahme zugunsten der Quellensteueranrechnung; die angezeigte anrechenbare
  Quellensteuer nach Verlustausgleich ist eine Schätzung, maßgeblich ist der Bescheid.
- **Fremdwährungen:** nur mit Kurs aus Beleg oder Eingabe, keine automatische Kursbeschaffung.
- **PDF-Erkennung:** nur mit synthetischen PDFs getestet. Echte Abrechnungen von Trade Republic und Scalable Capital
  können anders aufgebaut sein; dann erscheinen fehlende Felder im Prüfformular.
- **Windows:** `start.bat`/`install.bat` wurden in einer Linux-Umgebung erstellt und nicht unter Windows ausgeführt.
  Die Python-Teile sind plattformunabhängig getestet (Python 3.12 und 3.13).
