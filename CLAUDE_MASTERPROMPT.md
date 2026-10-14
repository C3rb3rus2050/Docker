# Claude Code – Masterprompt: Broker Document Collector & österreichisches KESt-Tool

> **Arbeitsauftrag:** Analysiere, repariere, integriere, teste und dokumentiere die beiden bestehenden Anwendungen im Repository. Arbeite eigenständig ohne unnötige Rückfragen. Implementiere tatsächlich ausführbaren Code statt nur Konzepte. Frage ausschließlich bei zwingend notwendigen externen Freigaben, echten Broker-Logins oder 2FA nach.

## Repository und Ausgangslage

- Repository: https://github.com/C3rb3rus2050/Docker
- Hauptbranch: `main`
- Bereits gemergter PR: https://github.com/C3rb3rus2050/Docker/pull/1
- Merge-Commit: `f5fae5d62d07415e4481b8a4d7933a0bcde9c434`
- Anwendungen: `broker-document-collector/` und `kest-tool/`
- Vorhandene Grundlagen: `compose.yaml`, Dockerfiles, `DOCKER-LXC.md`, Playwright, Xvfb, Fluxbox, x11vnc, noVNC, persistente Datenverzeichnisse, erste KESt-Collector-Verknüpfung, GitHub Actions.
- **Wichtig:** Der Docker-Build, die tatsächliche Browser-Anmeldung und die Broker-Downloads wurden noch nicht nachweislich erfolgreich im LXC getestet. Vorhandene Behauptungen in README-Dateien kritisch prüfen.

## Deine Rolle und Grundsätze

Handle als Senior Python-/Docker-/Playwright-/Finanzdaten-Entwickler mit Kenntnissen der österreichischen Kapitalertragsteuer. Verwende Python 3.12+, Docker Compose, SQLite, pytest und vorhandene Bibliotheken. Behalte bestehende Funktionen bei und vermeide unnötige Neuimplementierungen. Arbeite auf einem neuen Feature-Branch mit kleinen, nachvollziehbaren Commits und Pull Request. Niemals echte Finanzdokumente, Passwörter, Cookies, Tokens, Browserprofile oder Datenbanken committen. Keine Daten löschen. Ungetestete Funktionen ausdrücklich als ungetestet kennzeichnen. Implementiere, teste und korrigiere eigenständig.

## Zielarchitektur

Betrieb in einem **bereits vorhandenen Proxmox-LXC mit Docker Compose**, keine zusätzliche VM. Ein Compose-Stack für:

1. Eine zentrale deutschsprachige Weboberfläche mit Dashboard, Broker, Dokumenten, Import, Wertpapieren, Steuer, Exporten und Einstellungen.
2. Broker Document Collector für Trade Republic und Scalable Capital.
3. Österreichisches KESt-Tool für mehrere Broker.
4. Persistente Dokumente, Datenbanken, Logs, Exporte, Browserprofile und Backups.

Nutze die bestehende Streamlit-Oberfläche, sofern sie geeignet ist. Vermeide eine doppelte Steuerberechnungs- oder Importlogik. Implementiere Healthchecks, Restart-Policies, saubere Shutdowns, Konfiguration und Datenmigrationen. Halte Weboberflächen und VNC standardmäßig auf localhost; Remotezugriff über SSH-Tunnel oder authentifizierten HTTPS-Reverse-Proxy.

## Phase 1 – Bestandsaufnahme

Untersuche alle relevanten Dateien, Tests, Dockerfiles und Workflows. Prüfe, was funktioniert, was fehlt, welche Fehler und Sicherheitslücken bestehen. Führe bestehende Tests aus. Dokumentiere Ausgangslage und konkrete Prioritäten. Erfinde keine Broker-APIs oder getesteten Funktionen.

## Phase 2 – Docker und Browser-Anmeldung stabilisieren

- Verifiziere Playwright-Version gegen Container-Image und installierten Browser.
- Starte Chromium sichtbar über Xvfb/Fluxbox; prüfe noVNC und x11vnc.
- Prüfe die VNC-Passwortdatei: keine Passwörter in Prozessargumenten, Logs oder Repository. Keine ungeschützten Ports.
- Prüfe Host-Header, CSRF, Authentifizierung und Zugriffsrechte der Collector-Weboberfläche.
- Stelle sicher, dass beide Webdienste im Container erreichbar sind und die Ports korrekt veröffentlicht werden.
- Verwende persistente, brokergetrennte Browserprofile; sichere Berechtigungen und kein versehentliches Backup in öffentliche Speicher.
- Benutzer meldet sich **selbst** auf offiziellen Broker-Webseiten an und bestätigt 2FA/Captcha manuell. Keine Speicherung von Klartextpasswörtern, keine Umgehung von Schutzmechanismen.
- Erkenne gültige/abgelaufene Sitzungen; ermögliche erneute Anmeldung und Wiederverwendung vorhandener Sitzungen.
- Teste Neustarts, Healthchecks, Container-Logs, Datenbankzugriffe und persistente Volumes.
- Erstelle eine verständliche Installationsanleitung für den bestehenden Proxmox-LXC.

## Phase 3 – Broker Document Collector funktionsfähig machen

Unterstütze Trade Republic und Scalable Capital. Sammle alle für das angemeldete Konto **tatsächlich verfügbaren** Dokumente: Kauf-/Verkaufsabrechnungen, Dividenden, Zinsen, Gebühren, Steuer- und Jahresbescheinigungen, Konto-/Depotauszüge, Kapitalmaßnahmen, Kapitalrückzahlungen, ETF-/Fonds-/REIT-/BDC-Belege und historische Unterlagen.

Implementiere robuste, brokergetrennte Adapter mit semantischen Playwright-Selektoren. Durchsuche Dokumentenbereiche, Jahresfilter, Pagination, Infinite Scroll, Detailansichten und Downloads. Nur lesende, autorisierte Interaktionen; niemals Kauf, Verkauf, Überweisung, Änderung von Sparplänen oder andere Kontoaktionen auslösen. Nutze interne Schnittstellen nur, wenn deren Existenz, Berechtigung und lesender Charakter überprüft sind; keine erfundenen APIs.

Synchronisierungsmodi: inkrementell, Vollscan, Fortsetzen, manuell und optional geplant. Bei erforderlicher Anmeldung/2FA sicher pausieren und Benutzer informieren. HTTP 429, 403, 5xx, Timeouts, ungültige PDFs, Browserabstürze und Unterbrechungen robust behandeln. Retry mit begrenztem Backoff. Niemals Vollständigkeit behaupten, wenn sie nicht verifiziert werden kann.

## Phase 4 – Dokumente und Datenintegrität

Originaldateien unverändert speichern, atomare Writes, SHA-256-Duplikaterkennung, sichere Dateinamen, Größen- und Dateisignaturprüfung, Schutz vor Path Traversal. Metadaten: Broker, Dokumenttyp, Datum, Downloadzeitpunkt, Originalname, Speicherpfad, Größe, SHA-256, Quellenkennung/-URL ohne Geheimnisse, Status und Verarbeitungshistorie. Trenne sensible Browserprofile von Dokumenten.

Beispielstruktur:

```text
data/
  collector/
    TradeRepublic/
    ScalableCapital/
    database/
    logs/
    reports/
  browser-profiles/
  kest/
    database/
    documents/
    imports/
    exports/
    backups/
```

SQLite-Transaktionen, Datenbankmigrationen, konsistente Schreibzugriffe, Backups und Restore implementieren.

## Phase 5 – Zentrale Weboberfläche

Eine verständliche deutschsprachige Navigation:

- **Dashboard:** Brokerstatus, letzte Synchronisierung, Dokumentzahlen, Fehler, offene Prüfungen, Steuerjahr, Transaktionen, Steuerstatus, Backupstatus.
- **Broker:** Trade Republic, Scalable Capital, Login/2FA, Verbindung prüfen, Synchronisierung starten/pausieren/fortsetzen/abbrechen.
- **Dokumente:** Alle, neue, fehlgeschlagene, zu prüfende; Suche, Filter, Original öffnen, Metadaten, Importstatus.
- **Import:** Collector-Dokumente automatisch oder auf Knopfdruck ins KESt-Tool übernehmen.
- **Wertpapiere:** Aktien, ETFs, REITs, BDCs, Fonds.
- **Steuer:** Berechnungen, Quellensteuer, Verlustausgleich, E1kv.
- **Exporte:** Excel, CSV, PDF, E1kv-Arbeitsübersicht.
- **Einstellungen:** Broker, Zeitpläne, OeKB, Speicher, Sicherheit, Backups, Logs.

Keine irreführenden Erfolgsmeldungen. Nutzerfreundliche Fehlertexte, responsive Oberfläche, kein unnötiger Wechsel zwischen technischen Teil-Apps.

## Phase 6 – KESt-Integration und PDF-Verarbeitung

Verwende die bestehenden Importfunktionen des KESt-Tools. Datenfluss:

```text
Broker -> Collector -> Original-PDF/CSV -> SHA-256 -> gemeinsamer Speicher
       -> KESt-Importer -> Extraktion -> Plausibilitätsprüfung
       -> sichere Buchung ODER manuelle Prüfung -> Steuerberechnung -> Export
```

Keine doppelten Dokumente oder Buchungen; idempotente Synchronisierung. Jede Buchung muss zum Quelldokument rückverfolgbar sein. Unklare oder widersprüchliche Extraktionen **nicht** automatisch verbuchen. Manuelle Korrekturen mit Audit-Log. Extrahiere soweit verlässlich möglich Broker, Typ, Datum, ISIN, Wertpapier, Stück, Kurse, Gebühren, Dividende, Quellensteuer, Währung, Wechselkurs, Kapitalrückzahlung und Kapitalmaßnahme.

Bevorzuge strukturierte CSV/Excel, PDF-Text, brokerspezifische Parser und Regeln. OCR optional; KI nicht erforderlich und nicht als ungeprüfte Quelle für Steuerbuchungen verwenden.

## Phase 7 – Österreichische Steuerfunktionen

Erhalte und überprüfe Unterstützung für mehrere Broker, Aktien, REITs, BDCs, ETFs, Melde- und Nichtmeldefonds, Dividenden, Zinsen, Verkäufe, Verlustausgleich, Quellensteuer, Kapitalrückzahlungen und Kapitalmaßnahmen.

Berücksichtige gesetzlich zutreffende unterschiedliche Steuersätze und Einkunftsarten; nicht pauschal alles mit 27,5 % behandeln. Verarbeite realisierte Gewinne/Verluste, anrechenbare/nicht anrechenbare ausländische Quellensteuer, Ausschüttungen, ausschüttungsgleiche Erträge, Anschaffungskostenanpassungen, Fremdwährungen, jahresbezogene Regeln und E1kv-Kennzahlen. Kennzeichne unsichere Sonderfälle ausdrücklich als manuell zu prüfen.

**Verifiziere steuerliche Regeln anhand offizieller Quellen:** BMF Österreich, RIS, OeKB, FinanzOnline-Unterlagen. Dokumentiere Quelle, Steuerjahr und Rechenweg. Keine erfundenen Steuerregeln. Das Tool ist eine Arbeitshilfe, keine verbindliche Steuerberatung.

### OeKB

ISIN-basierte Suche, Meldefondsstatus, steuerlich relevante Meldungen, Zuordnung zum Steuerjahr, Ausschüttungen/ausschüttungsgleiche Erträge, Anschaffungskostenkorrekturen und Konflikterkennung. Nutze nur tatsächlich verfügbare und zulässige Datenzugänge; sonst manueller CSV-/PDF-Import. Originalmeldungen archivieren. Bestätigte Werte nicht stillschweigend überschreiben.

## Phase 8 – Sicherheit

- Keine Geheimnisse in Git, Logs, URLs, Fehlermeldungen oder Exporten.
- Browserprofile und Datenverzeichnisse restriktiv schützen.
- Keine ungeschützten Admin-, Download- oder VNC-Endpunkte.
- CSRF-, Host-Header-/DNS-Rebinding- und Path-Traversal-Schutz.
- Sichere Datei-Uploads und Downloadvalidierung.
- Keine Handels- oder Kontoänderungsaktionen.
- Keine öffentliche Freigabe ohne zusätzliche Authentifizierung und TLS.
- Geheimnisse nur über geeignete Secret-Dateien/Mechanismen.
- Datenbank-Backups und geprüfte Wiederherstellung.
- Sicherheitsrelevante Änderungen mit Tests absichern.

## Phase 9 – Tests und CI

Erstelle/erweitere pytest-Tests für Konfiguration, Datenbank, Browserstart, Loginzustände, Sessionablauf, Pagination, Dokumentenerkennung, Downloads, HTTP-Fehler, SHA-256, PDF/CSV, Collector-KESt-Integration, Idempotenz, Steuerregeln, OeKB, Verlustausgleich, Quellensteuer, E1kv und Excel.

Nutze Mock-Brokerseiten und synthetische Belege; teste 2FA-Wartezustand, Infinite Scroll, Sessionablauf, kaputte PDFs, Neustart und Wiederaufnahme. Führe soweit verfügbar aus:

```bash
python -m pytest
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs
```

Erweitere GitHub Actions um Tests, Linting und Docker-Builds. Fehlgeschlagene oder nicht ausführbare Tests niemals als erfolgreich darstellen. **Echte Brokerdownloads erst nach erfolgreichem Test mit berechtigtem Konto als validiert markieren.**

## Phase 10 – Dokumentation und Übergabe

Dokumentiere auf Deutsch: Installation im vorhandenen LXC, sicherer Erststart, SSH-Tunnel/Reverse-Proxy, Broker-Login und 2FA, Sync, Dokumentenimport, Steuerberechnung, OeKB, Exporte, Update, Backup/Restore, Logs, Fehlerbehebung und bekannte Grenzen.

Stelle einen möglichst einfachen Setup-Ablauf bereit. Keine unsicheren Standardpasswörter. Erstelle verständliche Hinweise, wenn vor dem Start Secrets oder Dateirechte eingerichtet werden müssen.

## Git-Workflow

1. Repository vollständig analysieren und vorhandene Tests ausführen.
2. Neuen Feature-Branch von `main` erstellen.
3. In kleinen überprüfbaren Schritten implementieren und committen.
4. Docker stabilisieren, dann Collector, Integration, UI, Steuerfunktionen und Tests.
5. Pull Request mit Änderungsübersicht, Testresultaten und offenen Punkten erstellen.
6. Keine ungetesteten sicherheitskritischen Änderungen automatisch produktiv deployen.

## Definition of Done

Erst als fertig bezeichnen, wenn Container zuverlässig starten, die zentrale Oberfläche funktioniert, Browser-Login und Sessionpersistenz nachgewiesen sind, Collector-Dokumente zuverlässig verarbeitet werden, Duplikate verhindert werden, KESt-Import idempotent ist, unklare Steuerdaten zur Prüfung gehen, Berechnungen und E1kv/Excel nachvollziehbar sind, OeKB-Fälle korrekt behandelt werden, Backups/Restore geprüft wurden und relevante Tests erfolgreich sind.

Trenne im Abschlussbericht explizit:
- **Implementiert und getestet**
- **Implementiert, aber nicht live validiert**
- **Noch offen / erfordert Benutzeraktion**

**Beginne jetzt unmittelbar mit der Repository-Analyse und arbeite die Phasen eigenständig ab. Stelle nur Rückfragen, wenn ein echter Broker-Login, eine 2FA-Bestätigung oder eine unverzichtbare externe Freigabe benötigt wird.**
