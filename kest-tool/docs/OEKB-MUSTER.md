# Erkannte OeKB-Muster

Recherche und Prüfung: 15. Oktober 2026.

## Primärquellen

- [OeKB: Meldungen von Steuerdaten und aktuelle Feldlisten](https://www.oekb.at/kapitalmarkt-services/meldungen-und-hinterlegungen-von-dokumenten/meldungen-zu-investmentfonds/meldungen-von-steuerdaten.html)
- [OeKB: Veröffentlichung und Bezug von Steuerdaten](https://www.oekb.at/kapitalmarkt-services/unser-datenangebot/fonds/steuerdaten.html)
- [Prima Capital: veröffentlichtes OeKB-Privatanleger-PDF mit vier Anteilsgattungen](https://www.primacapitalfund.com/wp-content/uploads/Prima-Capital-Fund-Austrian-Fund-Status.pdf)
- [Security KAG: Schelhammer Capital Aktien, OeKB-Meldungen 2025](https://www.securitykag.at/content/uploads/f/SB-Schelhammer-Capital-Aktien-2025.pdf)

Die zwei öffentlichen PDFs wurden lokal vollständig ausgelesen und ausgewählte Seiten visuell geprüft.
Prima enthält vier Meldungen in USD, CHF, EUR und GBP mit einem AIF-Hinweis. Security enthält zwei
EUR-Meldungen mit negativen Anschaffungskostenkorrekturen. Fremde Dokumente werden nicht im Repository
mitgeliefert. Die Regressionstests verwenden selbst erstellte Muster mit anderen Beispielwerten.

## Unterstützte Struktur

- PDF: Basisinformationen pro ISIN, Meldedatum, Geschäftsjahres-Ende, Meldungswährung und Jahres-/Ausschüttungsmeldung.
- Kennzahlen für Privatanleger: Ausschüttungen, ausschüttungsgleiche Erträge, anrechenbare Steuer und AK-Korrektur.
- Die Spalte **Privatanleger ohne Option** beziehungsweise **PV ohne Option** wird verwendet. Andere Anlegergruppen
  werden nicht als Ersatz herangezogen. Kennzahlen, Zeilennummern und Prozentangaben sind keine Beträge.
- Mehrere ISINs/Meldungen in einem PDF werden getrennt verarbeitet und mit derselben Originaldatei verknüpft.
  Erkennbare OeKB-Sammelberichte dürfen bis zu 250 Seiten enthalten; die Größenbegrenzung bleibt 50 MB.
- CSV/Excel: breite Tabellen mit benannten Spalten sowie Tabellen aus Metadaten und den Spalten
  `Bezeichnung`, `Privatanleger mit Option`, `Privatanleger ohne Option`.
- Fremdwährungen benötigen einen Belegkurs oder einen historischen EZB-Kurs zum Meldedatum beziehungsweise
  dem vorherigen verfügbaren Bankarbeitstag. Die Herkunft ergänzter Kurse wird protokolliert.

Die institutionellen START/STB/ENDE-Meldeformate aus der OeKB-Schnittstellenbeschreibung sind damit nicht
vollständig implementiert. Das Programm lädt keine Kontoinhalte oder kostenpflichtigen Datenlieferungen ab.

Fehlende Kennzahlen, unbekannte Spalten, widersprüchliche Werte, besondere AIF-Einkünfte und nicht gemeldete
unterjährige Ausschüttungen bleiben zur Prüfung offen. Ein Rohbetrag für Ausschüttungen wird nicht aus dem
steuerpflichtigen Teil geschätzt. Neue Fondsmeldungen bleiben ungeprüft; abweichende Importe erzeugen Konflikte.

## Tabellen und Belege

Transaktionen und Fondsmeldungen können direkt in den Tabellen bearbeitet werden. Vor dem Speichern werden
alle geänderten Zeilen validiert; Korrekturen benötigen eine Begründung und erhalten einen Prüfverlauf.
Bei Fondsmeldungen bleiben ISIN, Meldedatum und Meldungsart als Identität gesperrt. Für eine andere Meldung
wird ein neuer Datensatz angelegt. Die Auswahlspalte öffnet die zugehörigen Originale direkt im Browser,
auch bei Betrieb im Docker-Container. Der Download behält den ursprünglichen Dateinamen.
