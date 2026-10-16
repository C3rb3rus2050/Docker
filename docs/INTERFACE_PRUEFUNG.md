# Funktions- und Darstellungsprüfung 2.0.2

Die Prüfung erfolgt ausschließlich mit synthetischen MUSTER-Daten in einer eigenen Ablage.
Keine echten Buchungen, Belege oder Zugangsdaten sind erforderlich.

## Prüfumfang

| Bereich | Prüfung |
| --- | --- |
| Navigation | Alle zehn Menüseiten, Startseitenaktionen, konkreten Beleg öffnen, Steuerjahr wechseln, mobile Navigation |
| Import | Mehrfach-PDF-Upload, automatische Erkennung, fehlende Angaben, Originalanzeige, Tabellen-/ZIP-Import und Dubletten über API-Tests |
| Dokumente | Filter, Suche, Vor/Zurück, Liste, Neuanalyse, Metadaten speichern, Buchungs-/Fondsmeldungsprüfung über API-Tests, KI ohne Zustimmung gesperrt |
| Buchungen | Anlegen, suchen, öffnen, begründet korrigieren, verwerfen, Kursaktion mit Ergebnis, Revisionen/Dubletten/ungültige Eingaben über API-Tests |
| Wertpapiere | Filter, Suche, Quellenprüfung, Anlegen/Bearbeiten und Validierung über API-Tests |
| Fonds | Aktive Meldung öffnen und korrigieren, neue Meldungen, Preisangaben und Konflikte über API-Tests |
| Broker/Depots | Anlegen, Brokername in Auswahl, jahresspezifische Steuerangaben speichern |
| Berechnung | Alle neun Reiter, Rechenpositionen und Hinweise, keine wirkungslosen Öffnen-Schaltflächen bei reinen Informationen |
| Export | Excel, CSV, PDF und E-1kv erstellen, Exporthistorie, schnelle aufeinanderfolgende Aktionen, Downloads über API-Tests |
| Einstellungen | Speichern, Tabwechsel mit ungespeicherten Eingaben, beschriftetes Passwortfeld, wiederholbarer Referenzimport |
| Sicherung | ZIP erstellen, Prüfsummen und Datenbank über API-Tests, Wiederherstellung in der Testablage, bisheriger Stand bleibt gesichert |
| Fehlerfälle | Abgebrochene/veraltete Abfragen, ungültige Antworten, Formularfehler erhalten Eingaben, auffangbare Darstellungsfehler mit Neu-laden-Aktion |

Externe Ollama-/EODHD-Dienste sind in der Testablage nicht produktiv konfiguriert.
Zustimmung, Konfigurationsvalidierung und Fehlerbehandlung werden lokal geprüft;
Erreichbarkeit und Ergebnisse einer konkreten Serverinstallation erfordern deren Konfiguration.

## Reproduzierbare Prüfungen

```bash
python -m pytest -q
cd frontend
npm ci
npm test
npm run build
```

Für manuelle Browserprüfungen eine neue Demo-Ablage mit `python -m kest_tool.demo <Testordner>`
erstellen und den API-Server mit `KEST_TOOL_HOME=<Testordner>` starten. Import-, Bearbeitungs-
und Wiederherstellungstests ausschließlich in dieser Ablage ausführen.

Layout auf Desktop und bei 768, 390 und 320 Pixeln prüfen: Menü öffnen/schließen,
Tabellen separat scrollen, Formulare bedienen, Exportnamen umbrechen lassen und Hell-/Dunkelmodus wechseln.
