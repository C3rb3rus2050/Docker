# Belege direkt prüfen – Version 1.2.0

Die Ergebnisliste nach dem Upload und **Belege & Prüfung** zeigen Original und bearbeitbare Werte direkt nebeneinander. Keine Zeile markieren, kein einzelnes Dokument aus einer Auswahlliste öffnen, kein separates Fenster. Die Standardansicht ist **Direkt bearbeiten**; Suche/Filter sind optional eingeklappt. Je Seite werden bis zu fünf Belege angezeigt.

1. Original links lesen; Stückzahl, Brutto, Datum, ISIN, Währung und Steuern rechts ergänzen.
2. Das Depot wird bei eindeutiger Zuordnung vorausgewählt. Mehrdeutige Depots oder unbekannte Buchungsarten benötigen eine bewusste Zuordnung.
3. Den Vergleich mit dem Original bestätigen und **Geprüfte Buchung speichern** klicken.
4. Vorhandene Einzelbuchungen lassen sich in derselben Karte korrigieren; dafür ist eine Begründung nötig. Mehrere verknüpfte Buchungen stehen direkt in einer editierbaren Tabelle.

Leere Pflichtfelder bleiben leer. Eine manuell vervollständigte, bestätigte Buchung kann abgeschlossen werden, obwohl der Parser ursprünglich Werte nicht erkannt hat. Die ursprüngliche Extraktion bleibt als Beleg erhalten; die manuelle Prüfung und alle Änderungen werden separat protokolliert. Exakte Dubletten werden abgewiesen, mögliche Dubletten benötigen einen ausdrücklichen Abgleich. Ein erneuter Klick auf eine veraltete Übernahmekarte erzeugt keine zweite Buchung.

**Beleg erneut bestimmen** liest nur diesen Beleg neu, bei Bedarf mit lokaler Tesseract-OCR. **Erkennung für diese Ansicht aktualisieren** verarbeitet alle Belege im aktuellen Filter, nicht nur die fünf sichtbaren Karten. Für den gesamten offenen Bestand die Ansicht **Zu prüfen** ohne weitere Filter verwenden. Bestehende finanzielle Buchungswerte werden bei der automatischen Neuanalyse nicht überschrieben; Abweichungen erscheinen zur Prüfung.

Informationsdokumente, Steuerberichte und Kapitalmaßnahmen werden nicht zu erfundenen Einzelbuchungen. Eine falsch erkannte Dokumentart kann unmittelbar in der Karte korrigiert werden. „Keine zusätzliche Buchung“ muss ausdrücklich mit Begründung bestätigt werden.

## Erkennungsverbesserungen und öffentliche Quellen

Recherchebasis: 79 unveränderte öffentliche Ertrags-Textauszüge der Familien Trade Republic, Baader und Scalable aus dem Portfolio-Performance-Commit `f84ff1a432ec9ba61c17aa2ae4191c8b068643a7`:

- [Trade-Republic-Testbestand](https://github.com/portfolio-performance/portfolio/tree/f84ff1a432ec9ba61c17aa2ae4191c8b068643a7/name.abuchen.portfolio.tests/src/name/abuchen/portfolio/datatransfer/pdf/traderepublic)
- [Baader-Testbestand](https://github.com/portfolio-performance/portfolio/tree/f84ff1a432ec9ba61c17aa2ae4191c8b068643a7/name.abuchen.portfolio.tests/src/name/abuchen/portfolio/datatransfer/pdf/baaderbank)
- [Scalable-Testbestand](https://github.com/portfolio-performance/portfolio/tree/f84ff1a432ec9ba61c17aa2ae4191c8b068643a7/name.abuchen.portfolio.tests/src/name/abuchen/portfolio/datatransfer/pdf/scalablecapital)

Bei 16 Fällen fehlten zuvor Pflichtwerte. Der Parser erkennt nun auch die Bruttosumme ausschließlich aus der Positionsübersicht vor Abrechnung/Steuern, mehrzeilige Positionen mit ISIN vor der Stückzahl, zusammengeklebte Währung/ISIN, `BerechtigteAnzahl` ohne Leerzeichen sowie ausgewählte französische und niederländische Tabellen. Der Buchungstag stammt bevorzugt aus der Zahlungstabelle, nicht aus einem früheren Ex-Tag. Die Parser-Version ist 7; ältere Analyse-Caches werden beim Öffnen erneuert.

In der untersuchten Stichprobe fehlen danach keine typabhängigen Parser-Pflichtfelder mehr. Das bedeutet **nicht**, dass alle 79 Belege automatisch gebucht werden dürfen: Beispielsweise bleiben Quellenstaat, widersprüchliche Zahlen, Stornos, fremde Steuerabzüge oder Sonderfälle offen. Nominalbeträge von Anleihen werden nicht als Aktien-Stückzahl erfunden. 14 feste öffentliche Fälle mit manuell am Text abgeglichenen Erwartungen und SHA-256 sind reproduzierbar prüfbar:

```bash
python scripts/validate_broker_corpus.py tests/public_layout_manifest.json --public
```

Die öffentlichen Textauszüge werden nicht als Original-PDF-Nachweis ausgegeben und nicht mitgeliefert. Die konkreten PDFs des Nutzers stehen der Entwicklung nicht zur Verfügung. Nach dem Update deshalb die serverseitig vorhandenen Belege erneut bestimmen und mit dem Original abgleichen.
