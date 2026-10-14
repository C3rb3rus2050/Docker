# Broker Document Collector

Lokale Windows‑11‑Anwendung, die **alle im eigenen Konto angezeigten Dokumente** bei
**Trade Republic** und **Scalable Capital** automatisch findet, herunterlädt, kategorisiert,
per SHA‑256 auf Duplikate prüft und einen **Vollständigkeitsbericht** erstellt.

Sie melden sich nur **selbst im sichtbaren Browser** an (inkl. 2FA/Passkey). Danach sucht das
Programm die Dokumentenbereiche selbst, blättert durch die Historie, lädt die Dokumente herunter
und **gleicht mehrere Quellen gegeneinander ab** (Weboberfläche ↔ Trade-Republic-Schnittstelle
↔ Webapp-Datenantworten).

> **Stand der Verifikation:** Alle Funktionen sind implementiert und mit Mockseiten,
> künstlichen PDFs und einem gemockten Trade‑Republic‑WebSocket automatisiert getestet.
> **Gegen die echten Broker-Konten konnte ohne Zugangsdaten nicht getestet werden.**
> Siehe [Offene Punkte](#offene-punkte--nicht-verifizierte-funktionen).

---

## Inhalt

1. [Installation](#installation)
2. [Bedienung](#bedienung)
3. [So arbeitet der Scan](#so-arbeitet-der-scan)
4. [Zwei Wege & Abgleich](#zwei-wege--abgleich-der-quellen)
5. [API‑Verfügbarkeit (Recherche)](#api-verfügbarkeit-recherche)
6. [Dateistruktur](#dateistruktur)
7. [Sicherheit & Datenschutz](#sicherheit--datenschutz)
8. [Regelmäßige Synchronisierung](#regelmäßige-synchronisierung)
9. [Architektur](#architektur)
10. [Tests](#tests)
11. [Offene Punkte / nicht verifizierte Funktionen](#offene-punkte--nicht-verifizierte-funktionen)
12. [Fehlerbehebung](#fehlerbehebung)

---

## Installation

Voraussetzungen: Windows 11 (64 Bit), Python **3.12** (3.11–3.13 funktionieren), Internet für die
einmalige Installation. **Keine Administratorrechte nötig.**

1. Python installieren: <https://www.python.org/downloads/windows/> → „Install for current user“
   und „Add python.exe to PATH“ aktivieren.
2. Projektordner entpacken/klonen, darin **`install.bat`** doppelklicken. Das Skript
   - prüft die Python-Version,
   - erstellt die virtuelle Umgebung `.venv`,
   - installiert die Abhängigkeiten (`playwright`, `pypdf`, `pytest`),
   - installiert Playwright‑Chromium,
   - legt `config.toml` sowie Ausgabe‑ und Profilordner an,
   - führt einen schnellen Selbsttest aus.
3. **`start.bat`** startet die Anwendung. Die Oberfläche öffnet sich im Standardbrowser unter
   `http://127.0.0.1:8765/` (nur lokal erreichbar).

Manuelle Installation (alternativ):

```bat
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy config.example.toml config.toml
.venv\Scripts\python app.py
```

Optionale lokale OCR für gescannte PDFs: Tesseract‑OCR für Windows installieren,
`pip install pytesseract pypdfium2`, in den Einstellungen „Lokale OCR“ aktivieren und ggf. den
Pfad zu `tesseract.exe` angeben. OCR läuft vollständig lokal und ist standardmäßig aus.

## Bedienung

| Schritt | Aktion |
|---|---|
| 1 | **Anmelden & Dokumente holen** (je Broker) – es öffnet sich ein Chromium‑Fenster mit der offiziellen Seite. Selbst anmelden, 2FA bestätigen. Sobald die Anmeldung erkannt ist, **startet der Scan automatisch**. Wird sie nicht erkannt, nach dem Login auf **„Ich bin angemeldet – weiter“** klicken. |
| 2 | Alternativ (wenn bereits angemeldet): Broker auswählen, Modus wählen, **Automatischen Scan starten**. Beide Broker werden nacheinander gescannt. |
| 3 | Fortschritt, Bereiche, Downloads, Duplikate und Fehler live verfolgen. **Pausieren / Fortsetzen / Abbrechen** jederzeit möglich. |
| 4 | **Bericht exportieren** (HTML, Markdown, JSON im Ordner `reports`). |

Modi:

- **Synchronisieren** (Standard): bekannte Dokumente werden übersprungen, fehlgeschlagene erneut versucht.
- **Gesamtscan**: alles erneut prüfen (identische Inhalte werden per SHA‑256 als Duplikat erkannt, nicht neu gespeichert).
- **Fortsetzen**: wie Synchronisieren, zusätzlich werden Bereiche übersprungen, die im unterbrochenen Lauf bereits vollständig untersucht wurden.

Erscheint während des Scans eine Sicherheitsabfrage (Sitzung abgelaufen, 2FA, Captcha,
erneute Bestätigung), **hält der Scan an** und die Oberfläche zeigt „wartet auf Ihre Aktion im
Browser“. Nach Ihrer Bestätigung im Browser läuft er automatisch weiter. Es wird nichts umgangen.

Kommandozeile (`start.bat --help`):

```text
start.bat                       Oberfläche
start.bat --sync                Inkrementeller Sync beider Broker (für den Aufgabenplaner)
start.bat --scan tr --mode full Scan ohne Oberfläche (tr | sc | all)
start.bat --report 12           Bericht für Lauf 12 erzeugen
start.bat --delete-profile tr   Browserprofil löschen (Neuanmeldung nötig)
start.bat --delete-database     Datenbank löschen
start.bat --delete-downloads    Heruntergeladene Dateien löschen
start.bat --schedule-create 07:30 / --schedule-delete
```

## So arbeitet der Scan

1. **Bereiche finden:** Auf der angemeldeten Startseite werden Links, Menüs, Tabs und
   Schaltflächen anhand ihres zugänglichen Namens erkannt (Dokumente, Postfach, Steuern,
   Auszüge, Abrechnungen, Aktivität, Transaktionen, Profil …). Gefundene Bereiche werden besucht,
   dort werden Unterbereiche (Tabs/Untermenüs) ebenfalls erfasst.
2. **Zeiträume:** Jahresfilter (Auswahllisten oder Jahres‑Tabs) werden erkannt und **jedes
   Jahr einzeln** geprüft.
3. **Historie:** „Mehr laden“/„Ältere anzeigen“, Seitenwechsel („Nächste Seite“, Pfeile in
   Paginierungsleisten) und Infinite Scroll werden durchlaufen, bis keine neuen Einträge mehr
   erscheinen (zweimal ohne neue Einträge = Ende; harte Limits gegen Endlosschleifen).
4. **Dokumente:** direkte PDF/CSV/ZIP‑Links, eindeutige Download‑Schaltflächen („PDF
   herunterladen“ – Titel kommt dann aus dem Listeneintrag), Blob‑Downloads, PDF‑Viewer in
   Dialogen/Popups. Bei Trade Republic werden Transaktions‑/Aktivitätseinträge geöffnet, um die
   Dokumente der Detailansicht zu erreichen.
5. **Nur manuell anforderbare Dokumente** („… anfordern/beantragen“) werden **nicht** angeklickt,
   sondern im Bericht als „manuelle Freigabe erforderlich“ aufgeführt.
6. **Download‑Prüfung:** HTTP‑Status, Größenlimit, Dateisignatur (`%PDF-` … `%%EOF`, ZIP,
   CSV), HTML‑Fehler-/Loginseiten werden verworfen, nie als PDF gespeichert. Temporäre Fehler
   (Timeout, 429, 5xx) werden mit exponentiellem Backoff wiederholt.
7. **Speichern:** atomar, ohne Überschreiben (bei Namensgleichheit mit anderem Inhalt Suffix
   „(2)“), Original-Bytes unverändert. Gleicher SHA‑256 → kein zweites Speichern, die weitere
   Fundstelle wird als Metadatum gespeichert.
8. **Fortschritt** wird laufend in SQLite gesichert; abgebrochene Läufe lassen sich fortsetzen.

### Schutz vor Kontoaktionen

Jeder Klick wird vorher anhand der Bedeutung geprüft. **Blockiert** werden u. a.: Kaufen,
Verkaufen, Handeln, Order aufgeben/stornieren, Überweisen, Ein-/Auszahlen, Sparplan
anlegen/ändern, Löschen, Kündigen, Bestätigen, Senden, Speichern, Aktivieren, Abmelden,
Einstellungen, PIN/Passwort, Karte sperren, Anfordern/Beantragen (sowie englische
Entsprechungen). Elemente in Formularen mit Eingabefeldern werden nie angeklickt. „Weiter“
wird nur innerhalb erkannter Paginierungsleisten genutzt. Navigation ist auf die Hosts des
jeweiligen Brokers beschränkt. Die Integrationstests enthalten Fallen‑Schaltflächen
(„Jetzt kaufen“, „Verkaufen“, „Erneut kaufen“, „Abmelden“, „… anfordern“), deren Auslösung den
Test fehlschlagen ließe.

## Zwei Wege & Abgleich der Quellen

| Broker | Quelle 1 | Quelle 2 | Quelle 3 |
|---|---|---|---|
| Trade Republic | Weboberfläche (`app.traderepublic.com`) | **inoffizielle WebSocket‑Schnittstelle** (Timeline + Detail, nur lesend, im angemeldeten Browser) | Webapp‑Datenantworten (passiv) |
| Scalable Capital | Weboberfläche | Webapp‑Datenantworten (passiv mitgelesene Dokumentlisten) | – |

**Trade Republic – WebSocket:** Die Webapp nutzt `wss://api.traderepublic.com`. Das Protokoll ist
nicht offiziell dokumentiert, aber durch das Open‑Source‑Projekt *pytr* öffentlich beschrieben.
Der Collector öffnet diesen WebSocket **innerhalb der von Ihnen angemeldeten Seite**; der Browser
authentifiziert ihn mit seinen eigenen Cookies. Das Tool liest keine Cookies aus, fragt keine
Telefonnummer/PIN ab und nutzt per Whitelist **nur lesende Abonnements** (`timelineTransactions`,
`timelineActivityLog`, `timelineDetailV2`). Die Dokumente werden über die dort enthaltenen
Download‑Links geladen. Abschaltbar in den Einstellungen.

**Scalable Capital – Webapp‑Daten:** Für Scalable ist keine Dokumenten‑API bekannt (siehe
Recherche). Statt Endpunkte zu erfinden, werden die JSON‑Antworten, die die Webapp **selbst**
beim Navigieren lädt, lokal mitgelesen und auf Dokumenteinträge (Titel, Datum, Kennung,
Download‑Link) untersucht. Es werden keine eigenen Anfragen an interne Endpunkte gestellt.

**Abgleich:** Nach dem Scan werden alle Funde zusammengeführt – nach SHA‑256 (identischer
Inhalt), URL‑Basis (ohne Signatur), Brokerkennung und zuletzt Titel+Datum. Der Bericht zeigt:
Dokumente in allen Quellen, **nur in einer Quelle** (→ Hinweis auf Lücken der anderen) und die
Anzahl je Quelle. Dokumente, die nur eine Quelle kennt, werden trotzdem heruntergeladen.

## API‑Verfügbarkeit (Recherche)

Stand der Recherche: Oktober 2026. Unterschieden nach Zugriffsart:

| Zugriffsart | Trade Republic | Scalable Capital |
|---|---|---|
| Offiziell dokumentierte API für **Dokumente** | **Keine.** Die Open‑Banking‑/PSD2‑Schnittstelle richtet sich an lizenzierte Drittanbieter (Konto-/Zahlungsdaten) und ist **keine** Dokumenten‑Download‑API – sie wird nicht verwendet. | **Keine.** Die offizielle *Scalable CLI* (`sc`, Beta, OAuth‑Device‑Flow) bietet laut README Depot, Transaktionen, Sparpläne und Handel, aber **keine Dokumenten/Postfach‑Befehle** und keine Windows‑Binärdatei → nicht genutzt (insbesondere keine Handelsbefehle). |
| Normale Browsernavigation | Ja – Hauptquelle | Ja – Hauptquelle |
| Im Browser angebotene Downloadlinks | Ja (Detailansichten, Dokumente) | Ja (Postfach/Dokumente) |
| Dynamische Dokumentenlisten | Ja (SPA, Nachladen) | Ja (SPA, Nachladen) |
| Nicht öffentlich dokumentierte interne Endpunkte | WebSocket der Webapp (durch *pytr* beschrieben) – **zweite Quelle**, nur lesend, nur im angemeldeten Browser, keine Umgehung von Zugriffskontrollen | Keine bekannt – **nicht verwendet**; nur passives Mitlesen der Antworten, die die Webapp selbst lädt |
| Nur manuell exportierbar/anforderbar | wird erkannt und im Bericht gemeldet | wird erkannt und im Bericht gemeldet; Dokumente früherer Kontomodelle/Bankpartner nur, soweit im aktuellen Konto angezeigt |

Quellen: [pytr (GitHub)](https://github.com/pytr-org/pytr), [Scalable CLI (GitHub)](https://github.com/ScalableCapital/scalable-cli).
Die offiziellen Hilfeseiten der Broker sollten bei Änderungen erneut geprüft werden.

## Dateistruktur

Standard‑Ausgabeordner: `%USERPROFILE%\Documents\BrokerDocumentCollector\` (konfigurierbar)

```
BrokerDocumentCollector/
├── TradeRepublic/
│   ├── Steuer/2023/2024-02-15_Jahressteuerbescheinigung.pdf
│   ├── Kontoauszuege/2024/
│   ├── Depotauszuege/
│   ├── Wertpapierabrechnungen/2024/
│   ├── Dividenden/  Zinsen/  Gebuehren/  Ein-Auszahlungen/  Vertraege/
│   ├── Zu_pruefen/          (unsichere Klassifizierung)
│   └── Sonstige/            (unbekannt)
├── ScalableCapital/ …       (gleiche Struktur, dynamisch angelegt)
├── database/collector.sqlite3
├── logs/collector.log       (rotierend, 5 × 5 MB, redigiert)
└── reports/bericht_<broker>_lauf<N>_<zeit>.html|.md|.json
```

Dateinamen: `<Dokumentdatum>_<Originalname>` – das Datum wird nur vorangestellt, wenn es aus der
Dokumentliste, dem Titel/Dateinamen oder einem beschrifteten Datum im PDF stammt (nie erfunden).
Der Inhalt bleibt byte‑identisch; Originalname, Quelle und alle Fundstellen stehen in der Datenbank.

**Browserprofile** liegen bewusst getrennt unter `%LOCALAPPDATA%\BrokerDocumentCollector\browser-profile\<broker>`
(nicht im häufig OneDrive‑synchronisierten Dokumente‑Ordner).

Datenbanktabellen: `documents`, `document_locations` (alternative Fundstellen), `scan_runs`,
`scan_items` (dauerhafter Status je Dokumentkennung), `run_results` (Ergebnis je Lauf), `areas`
(Bereichsstatus je Lauf), `source_records` (Quellenabgleich), `markers` (bereits ausgewertete
Timeline‑Ereignisse).

## Sicherheit & Datenschutz

- **Keine Passwortabfrage, keine Speicherung von Zugangsdaten.** Die Konfiguration lehnt Schlüssel
  wie `password`, `pin`, `token`, `cookie`, `session` ab.
- **Keine Cookies/Tokens in Logs, Datenbank oder Berichten:** Alle Log‑Meldungen, Fehlermeldungen
  und gespeicherten URLs werden redigiert (Query‑Parameter wie Signaturen/Tokens, Cookie‑ und
  Authorization‑Header, JWTs, Telefonnummern). Vorab signierte Links werden nur ohne Signatur
  gespeichert. Tests prüfen das auf Byte‑Ebene in der SQLite‑Datei.
- **Cookies verlassen den Browser nicht.** Downloads laufen über die Sitzung des Browsers; an
  fremde Hosts (z. B. Speicherlinks) werden keine Cookies mitgesendet.
- **Keine Cloud, keine Telemetrie, keine externen KI‑Dienste, keine CDNs.** Die Oberfläche ist
  nur unter 127.0.0.1 erreichbar, POST‑Anfragen brauchen ein Zufallstoken je Programmstart,
  der Host‑Header wird geprüft (Schutz gegen fremde Webseiten/DNS‑Rebinding).
- **OneDrive‑Warnung:** Liegt der Ausgabeordner in einem Cloud‑Sync‑Ordner, zeigt die Oberfläche
  eine Warnung.
- **Dateisicherheit:** Directory‑Traversal‑Schutz (`safe_join`, Bereinigung von Dateinamen inkl.
  reservierter Windows‑Namen), Größenlimit, Signaturprüfung, Inhalte werden nie ausgeführt
  (PDF‑Text wird nur mit `pypdf` gelesen).
- **Nur erlaubte Hosts:** Navigation/Downloads nur über HTTPS auf den Domains des Brokers (bei Trade
  Republic zusätzlich TR‑eigene Speicher‑Hosts); keine IP‑Adressen, kein localhost, keine
  eingebetteten Zugangsdaten.

### Browserprofil = Zugangsschlüssel

Das Profil enthält die Sitzungscookies. Wer es kopiert, kann – solange die Sitzung gilt –
auf Ihr Konto zugreifen. Empfehlungen:

- Windows‑Konto mit Passwort/Windows Hello, Bildschirmsperre bei Abwesenheit.
- **BitLocker** aktivieren: *Einstellungen → Datenschutz und Sicherheit → Geräteverschlüsselung*
  (Windows 11 Home) bzw. *Systemsteuerung → BitLocker‑Laufwerksverschlüsselung* (Pro/Enterprise).
  Den Wiederherstellungsschlüssel sicher (offline) aufbewahren. Das schützt Profil, Datenbank und
  Dokumente bei Diebstahl des Geräts.
- Profil nicht in Cloud‑Ordner verschieben oder sichern.
- **Löschen** (getrennt möglich): Oberfläche „Daten löschen“ oder
  `start.bat --delete-profile [tr|sc]`, `--delete-database`, `--delete-downloads [tr|sc]`.
  Zusätzlich empfiehlt es sich, sich in der Broker‑App von allen Web‑Sitzungen abzumelden.

## Regelmäßige Synchronisierung

Oberfläche → „Täglicher Sync … Aufgabe anlegen“ oder `start.bat --schedule-create 07:30`.
Es wird eine Aufgabe „BrokerDocumentCollector Sync“ im Windows‑Aufgabenplaner angelegt (nur
bei angemeldetem Benutzer, ohne Adminrechte). Der Sync

1. erkennt bekannte Dokumente an stabilen Kennungen und Hashes,
2. lädt nur neue bzw. zuvor fehlgeschlagene Dokumente,
3. fragt bei Trade Republic bereits ausgewertete Timeline‑Einträge nicht erneut ab
   (Einstellung „Ältere Einträge erneut prüfen“ erzwingt das),
4. erstellt einen neuen Bericht.

Ist die Sitzung abgelaufen, öffnet sich das Browserfenster und der Sync **wartet** (Standard
10 Minuten) auf Ihre Anmeldung; danach bricht er mit Status „Anmeldung erforderlich“ ab.

## Architektur

```
app.py → cli.py ──► ui.py (lokaler HTTP-Server, deutsch)      ──┐
                └─► scanner.py: ScanManager (1 Worker-Thread) ──┤
                                Collector (Ablauf, Fortsetzen)  │
   broker_adapter.py  Interface BrokerAdapter + Datenmodelle    │
   web_adapter.py     generische Webapp-Logik  ◄────────────────┘
     ├─ trade_republic.py   TradeRepublicAdapter  (+ tr_api.py: WebSocket-Protokoll)
     └─ scalable_capital.py ScalableCapitalAdapter
   discovery.py        sichere DOM-Erkennung: Bereiche, Paginierung, Zeiträume, Dokumente
   network_capture.py  passive Auswertung von Webapp-JSON
   browser_manager.py  Playwright, persistente Profile, Downloads in der Sitzung
   downloader.py       Signaturprüfung, Retry, atomare Speicherung
   deduplication.py    SHA-256
   classifier.py       Heuristik (+ optionale lokale OCR)
   reconciliation.py   Quellenabgleich
   reporting.py        Prüfberichte (HTML/MD/JSON)
   database.py         SQLite
   security.py         Dateinamen, Pfade, URL-Richtlinien, Redaktion
   maintenance.py / scheduler.py / logging_setup.py / config.py
```

Das Interface `BrokerAdapter` definiert `connect()`, `check_session()`,
`discover_document_areas()`, `discover_documents()`, `download_document()`,
`paginate_history()`, `get_scan_status()`, `close()`. Selektoren/Hosts/Muster sind im jeweiligen
Adapter gekapselt; die Erkennung bevorzugt Rollen und zugängliche Namen statt CSS‑Klassen.

## Tests

```bat
.venv\Scripts\python -m pytest -q                 REM alle automatisierten Tests
.venv\Scripts\python -m pytest -q -m integration  REM nur Browser-Integrationstests (Mockseiten)
```

Abgedeckt: SHA‑256‑Duplikate, Dateinamenbereinigung, Signaturprüfung, SQLite‑Persistenz,
Fortsetzung unterbrochener Scans, Pause/Abbruch, Retry‑Logik, Fehlerprotokollierung inkl.
Redaktion, URL‑Validierung, Directory Traversal, Klassifizierung, Downloadstatus,
Berichtserstellung, Quellenabgleich, WebSocket‑Protokoll (Delta, Paginierung, Fehler),
Netzwerk‑Extraktion, Oberfläche (Token, Host‑Prüfung), Löschfunktionen, Aufgabenplaner‑Befehl.

Integrationstests (headless Chromium, Mockseiten über HTTPS‑Routing): Bereichserkennung,
„Mehr laden“, Jahresfilter, Blob‑Download, PDF‑Viewer im Dialog, Detailansichten,
HTML‑statt‑PDF, Duplikate über Quellen, Fallen gegen Kontoaktionen, Sync‑Wiederholungslauf,
Trade‑Republic‑WebSocket im Browser (gemockter Server) inkl. inkrementellem Lauf.

**Echte Broker‑Livetests** (`tests/test_live_brokers.py`) sind als `live` markiert und laufen nur
manuell mit `BDC_LIVE=1` und eigener Anmeldung.

Hinweis für Umgebungen mit vorinstalliertem Chromium: `BDC_BROWSER_EXECUTABLE` auf die
Chromium‑Datei setzen.

## Offene Punkte / nicht verifizierte Funktionen

Ehrliche Liste dessen, was **ohne Zugang zu echten Konten nicht live geprüft** werden konnte:

1. **Trade‑Republic‑Weboberfläche:** Die generische Erkennung (Namen von Menüs, Listen,
   Detailansichten) ist gegen Mockseiten getestet, nicht gegen `app.traderepublic.com`. Ob alle
   Dokumentbereiche gefunden werden, muss ein erster Livelauf zeigen (Bericht prüfen).
2. **Trade‑Republic‑WebSocket:** Protokoll laut *pytr*; nicht offiziell, kann sich ändern. Annahmen:
   der Browser authentifiziert den WebSocket mit den Sitzungscookies; Dokumentlinks liegen auf
   TR‑eigenen Hosts (`*traderepublic*.amazonaws.com`/`*.traderepublic.com`). Weicht der Host ab,
   wird der Download mit „Host nicht erlaubt“ protokolliert – dann den offiziellen Host unter
   `extra_document_hosts` eintragen. Fällt die Quelle aus, läuft der UI‑Scan unverändert weiter.
3. **Scalable‑Capital‑Oberfläche:** Start‑URL `https://de.scalable.capital/`; Login‑/Postfach‑Pfade
   werden heuristisch erkannt, nicht live verifiziert. Ob die Webapp Dokumentlisten als JSON lädt
   (zweite Quelle), ist unbekannt – ansonsten meldet der Bericht „nur eine Quelle“.
4. **Sitzungserkennung** (angemeldet/abgelaufen/2FA/Captcha) ist heuristisch (Passwort-/Code‑Felder,
   Captcha‑Frames, Abmelden‑Element). Im Zweifel wartet das Tool lieber auf den Benutzer.
5. **Windows‑spezifisch nicht ausgeführt:** `install.bat`, `start.bat`, Aufgabenplaner (`schtasks`)
   und „Ordner öffnen“ wurden in einer Linux‑Umgebung entwickelt; die Python‑Teile sind
   plattformunabhängig getestet, die Batch‑Dateien nicht unter Windows gelaufen.
6. **OCR** ist implementiert, aber ohne installiertes Tesseract nicht getestet.
7. **Vollständigkeit** kann grundsätzlich nicht garantiert werden; der Bericht weist
   teilweise/nicht untersuchte Bereiche, Fehler, manuelle Fälle, Jahreslücken und
   Quellenabweichungen aus.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| „Chromium konnte nicht gestartet werden“ | Ein anderes Fenster nutzt dasselbe Profil → „Browserfenster schließen“ oder Programm neu starten. |
| Nach dem Login passiert nichts / Status bleibt „Anmeldung läuft“ | Auf **„Ich bin angemeldet – weiter“** klicken. Bleibt die Meldung, ist im Browser noch ein Anmeldefeld (Telefon/PIN/Code) sichtbar – Anmeldung abschließen. Die Zeile „Sitzungsprüfung …“ in `logs\collector.log` zeigt, was erkannt wurde (nur Pfad und Zähler, keine Daten). |
| „Host nicht erlaubt“ bei Downloads | Offiziellen Speicher‑Host des Brokers in `extra_document_hosts` eintragen. |
| Viele „Zu prüfen“ | Klassifizierung unsicher – Dateien liegen sicher in `Zu_pruefen`, Originale unverändert. |
| Bereich „teilweise untersucht“ | Limits in `config.toml` erhöhen (`max_pages_per_area`, `max_load_more_clicks`) und „Fortsetzen“. |
| Logs | `<Ausgabeordner>\logs\collector.log` (redigiert). |
