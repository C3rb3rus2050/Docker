# Lokale KI für unbekannte Belege (ab 1.3.0)

Die bisherigen Brokerregeln und OCR bleiben die automatische Erkennung. Zusätzlich kann ein lokal
betriebenes Ollama-Modell Text aus einer einzelnen Abrechnung untersuchen. Die KI ist standardmäßig
deaktiviert, läuft nur auf ausdrücklichen Klick pro Beleg und erzeugt ausschließlich Vorschläge.
Es gibt keinen automatischen KI-Stapelimport und keine steuerliche Einstufung durch das Modell.

## Docker-Installation

Im vorhandenen Repository auf dem Server:

```bash
cd /root/Steuer-Tool
git pull --ff-only origin main
export COMPOSE_PROJECT_NAME=kest
export COMPOSE_FILE=compose.yaml:compose.ai.yaml
bash scripts/update-server.sh
docker compose exec ollama ollama pull qwen2.5:7b
```

Das zusätzliche Compose-File ergänzt den vorhandenen Stack und ändert keine lokalen Portzuordnungen.
Es veröffentlicht keinen Ollama-Port. Modelle liegen im separaten Docker-Volume `ollama-models`;
das bestehende Datensicherungsskript sichert die Anwendung, nicht die erneut herunterladbaren Modelle.
Bei späteren Updates beide Umgebungsvariablen erneut setzen. Die Erstinstallation benötigt Internet
für Image und Modell. CPU-Betrieb ist möglich, kann langsam sein; für dieses 7B-Modell ausreichend
Arbeitsspeicher vorsehen (praktisch mindestens etwa 8 GB verfügbar, abhängig von Kontext und Laufzeit).
Das Overlay konfiguriert keine GPU.

In **Einstellungen → Dokumentenerkennung → Lokale KI für unbekannte Beleglayouts** aktivieren:

- Ollama-Basisadresse: `http://ollama:11434`
- Installiertes Modell: `qwen2.5:7b`

Bei einer Installation ohne Docker muss Ollama separat laufen; Adresse typischerweise
`http://127.0.0.1:11434`. Kein API-Schlüssel notwendig.

## Verwendung

1. In einer Belegkarte **Unbekanntes Layout mit lokaler KI prüfen** öffnen.
2. Übermittlung an den selbst eingerichteten Dienst bestätigen und **KI-Vorschläge ermitteln** klicken.
3. Werte mit Textstellen und Original vergleichen. Gewünschte Felder auswählen und übernehmen.
4. Im selben Formular vervollständigen, mit dem Original abgleichen und speichern.

Nur ausgewählte Felder ersetzen den Formularentwurf. Vorhandene Buchungen werden erst durch den
normalen Speichervorgang mit Begründung geändert. Übernahmen werden mit Modell und Textstellen
protokolliert. Nach Übernahme ist eine erneute Originalbestätigung erforderlich.

## Grenzen und Datenschutz

- Es werden maximal 24.000 Textzeichen untersucht. Ohne lesbaren Text wird lokale OCR versucht
  (höchstens acht Seiten). Keine direkte Bildanalyse durch das Sprachmodell.
- IBAN und E-Mail werden bestmöglich entfernt. Namen, Anschriften und andere persönliche Daten können
  im Text verbleiben. Nur einen selbst kontrollierten Dienst konfigurieren; die Adresse kann auch auf
  einen anderen Rechner zeigen. Keine automatische Übermittlung an OpenAI oder andere KI-Anbieter.
- Die Modellantwort muss gültiges JSON liefern. Jede Quellenstelle muss im übermittelten Text vorkommen,
  jeder vorgeschlagene Rohwert in dieser Stelle. Zahlen, Datumswerte und ISIN werden zusätzlich geprüft.
- Ein vorhandener Textbeleg beweist nicht, dass ein Betrag fachlich richtig zugeordnet ist: Brutto/Netto,
  Gebühren, Quellensteuer, Devisenkursrichtung und mehrere Transaktionen immer selbst vergleichen.
- Einzelne Zahlen mit genau drei Nachkommastellen und nur einem Trennzeichen bleiben wegen möglicher
  Tausendertrennung unübernommen. Fehlende Werte werden nicht durch die Anwendung ausgerechnet.
- Dokumentanweisungen gelten als unzuverlässiger Inhalt. Die KI bekommt keine Werkzeuge und kann
  weder Dateien ändern noch Buchungen speichern. Steuerklassen und Buchungsarten werden nicht übernommen.
- Die Tests prüfen validierte Antworten, Fehlerfälle und den echten Streamlit-Formularablauf mit
  simulierten Antworten. Eine Erkennungsquote des Modells auf privaten Originalbelegen ist nicht belegt.

API-Grundlage: [Ollama-Dokumentation](https://docs.ollama.com/api/generate).
