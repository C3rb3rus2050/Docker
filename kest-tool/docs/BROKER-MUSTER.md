# Broker-Dokumentmuster und Erkennungsgrenzen

Stand: 15. Oktober 2026. Die Musteranalyse verwendet öffentliche PDF-Textextrakte aus Portfolio Performance, fixiert auf Commit `c54f42fcbe22eb6d308d57190920ea4d4c36a09e`:

- [Trade Republic: 248 Muster](https://github.com/portfolio-performance/portfolio/tree/c54f42fcbe22eb6d308d57190920ea4d4c36a09e/name.abuchen.portfolio.tests/src/name/abuchen/portfolio/datatransfer/pdf/traderepublic)
- [Scalable Capital: 71 Muster](https://github.com/portfolio-performance/portfolio/tree/c54f42fcbe22eb6d308d57190920ea4d4c36a09e/name.abuchen.portfolio.tests/src/name/abuchen/portfolio/datatransfer/pdf/scalablecapital)
- [Baader Bank: 137 Muster](https://github.com/portfolio-performance/portfolio/tree/c54f42fcbe22eb6d308d57190920ea4d4c36a09e/name.abuchen.portfolio.tests/src/name/abuchen/portfolio/datatransfer/pdf/baaderbank)

Die 456 Textmuster decken 91 Kombinationen aus Broker und Dateinamensfamilie ab. Alle werden einer Dokumentfamilie zugeordnet; das bedeutet ausdrücklich keine vollständige oder fehlerfreie Buchungserkennung. 24 fremdsprachige Abrechnungen bleiben gezielt zur Prüfung. Die veröffentlichten Originalmuster werden nicht in diesem Repository vervielfältigt. Regressionstests verwenden synthetische Beispiele.

| Dokumentfamilie | Verarbeitung |
| --- | --- |
| Kauf, Verkauf, Sparplan, RoundUp, Saveback, Zeichnung | Einzelbuchung bei vollständigen, widerspruchsfreien Angaben; Gebühren separat |
| Dividende, Ausschüttung, Ertrag | Brutto, Stückzahl, Währung und Steuerfelder extrahieren; unklare Beträge prüfen |
| Zinsabrechnung | Explizite Bruttowerte und getrennte Cash-Zinsperioden berücksichtigen; Buchungsdatum bevorzugen |
| Cash-Zinsen zusammen mit Geldmarktfonds-Erträgen | Bestandteile anzeigen, getrennte Zuordnung prüfen |
| Kontoauszug, Depotauszug, Kosteninformation, Zahlungsbeleg | Original erhalten; keine pauschale Wertpapierbuchung aus Summen erzeugen |
| Vorabpauschale Deutschland | Informationsbeleg; keine österreichische Steuerbuchung daraus ableiten |
| Steuerkorrektur, Jahressteuerunterlagen, Verlustbescheinigung | Gesonderte Prüfung |
| Storno, Depotübertrag, Kapitalmaßnahme, Fälligkeit, Wiederanlage, Krypto | Gesonderte Prüfung; keine ungesicherte Einzelbuchung |
| Fremdsprachige Sonderformate | Familie erkennen, Werte manuell prüfen |

## Schutz gegen falsche Zuordnung

Dokumentüberschriften und Abrechnungstabellen haben Vorrang vor Wörtern im Wertpapiernamen. Beispielsweise bleibt ein Sparplankauf eines „Dividend“-ETF ein Kauf. Hinweise in Anhängen zu Verkäufen werden nicht als neue Vorabpauschale oder Depotübertrag gewertet. Englische Tabellen erhalten passende Dezimalregeln. Mehrere Ausführungszeilen werden nicht stillschweigend zu einer einzelnen Buchung verkürzt.

Kontoauszüge und umfangreiche Broker-Unterlagen können bis zu 250 Seiten enthalten. Für andere PDFs gilt weiterhin die engere Seitengrenze. Die Textmustersuche ersetzt keine Prüfung von OCR, Bildqualität oder geänderten Original-PDF-Layouts.

## Vorhandene Belege erneut analysieren

Unter **Belege & Prüfung → Alle Belege** Filter wählen und **Erkennung für diese Ansicht aktualisieren** drücken. Die erneute Analyse aktualisiert den Prüfbericht. Weichen sicher erkannte Angaben von einer bestehenden ursprünglichen PDF-Buchung ab, wird diese zur Prüfung markiert. Gespeicherte Beträge und Buchungsarten werden nicht automatisch überschrieben und keine Dubletten erzeugt. Ergänzend verknüpfte Belege werden nicht mit der ursprünglichen Buchung verwechselt.

Die Listen bieten Textsuche, Prüfstatus, Sortierung, Auswahl und direkte Bearbeitung. Weitere Spalten lassen sich einblenden; große Listen werden in Seiten mit 50 Einträgen aufgeteilt. Über eine ausgewählte Zeile sind zugehörige Originalbelege erreichbar.

## Offizielle Hinweise

- [Trade Republic: Dokumente abrufen](https://support.traderepublic.com/de-de/267)
- [Scalable: Verlustbescheinigung](https://help.scalable.capital/steuern-de12f868/wie-erhalte-ich-eine-verlustbescheinigung-5a063e61)
- [Scalable Österreich: Steuerleicht](https://at.scalable.capital/steuerleicht)

Dokumentart und deutsche Steuerbegriffe bestimmen nicht automatisch die österreichische Steuerbehandlung. Individuelle Broker-Abrechnungen sind nicht durch öffentliche Muster oder Internetdaten ersetzbar.

## Ergänzung: Textbausteine und beschädigte Überschriften

Die Erkennung berücksichtigt zusätzlich bedingte Trennstriche, unsichtbare Zeichen, bekannte über zwei Zeilen getrennte Überschriften und vollständig mit Buchstabenabständen geschriebene Titel. Zahlen und ISINs werden dabei nicht umformatiert.

Fehlt eine eindeutige Überschrift, werden unabhängige Inhaltsmerkmale kombiniert: etwa Anfangs- und Endsaldo, Bescheinigung nach § 45a plus Kapitalertragssumme, Depotbestand plus ISIN-Bewertungstabelle, Produktkosten plus Kostenvorschau oder berechtigtes Wertpapier plus Ex-/Zahltagsangaben. Auch explizite Ausführungssätze zusammen mit Kurswerten und Zinszeitraum zusammen mit Bruttozinsen unterstützen eine vorläufige Einordnung. Ein einzelnes Stichwort reicht für diese Rückfallebene nicht aus. Mehrere widersprechende Familien ergeben eine prüfpflichtige Sammelabrechnung.

Eine anhand solcher Inhaltsmerkmale erschlossene Familie wird nicht automatisch als abschließend verarbeitet oder gebucht. Der Prüfbericht und die Belegdetails zeigen die gefundenen Textstellen und die Methode. Eine klare vorhandene Abrechnungsüberschrift hat Vorrang vor diesen Inhaltsmerkmalen.

Weitere bekannte Titel umfassen Advance Lump Sum, Jahresdepotauszug, Ertragsthesaurierung, Wahldividende, Vergütung des Vermögensverwalters und Abrechnung über den Kauf von Kryptowerten. Thesaurierung, Wahlrechte und die Trade-Republic-Überschrift „Ausschüttung / Ausschüttungsgleicher Ertrag“ werden zur gesonderten Prüfung eingeordnet.

Der Abgleich nutzt zusätzlich die öffentlichen Implementierungen der Musterfamilien im selben fixierten Portfolio-Performance-Commit:

- [TradeRepublicPDFExtractor.java](https://github.com/portfolio-performance/portfolio/blob/c54f42fcbe22eb6d308d57190920ea4d4c36a09e/name.abuchen.portfolio/src/name/abuchen/portfolio/datatransfer/pdf/TradeRepublicPDFExtractor.java)
- [ScalableCapitalPDFExtractor.java](https://github.com/portfolio-performance/portfolio/blob/c54f42fcbe22eb6d308d57190920ea4d4c36a09e/name.abuchen.portfolio/src/name/abuchen/portfolio/datatransfer/pdf/ScalableCapitalPDFExtractor.java)
- [BaaderBankPDFExtractor.java](https://github.com/portfolio-performance/portfolio/blob/c54f42fcbe22eb6d308d57190920ea4d4c36a09e/name.abuchen.portfolio/src/name/abuchen/portfolio/datatransfer/pdf/BaaderBankPDFExtractor.java)

Diese Quellen dienen dem Layoutabgleich; ihre deutschen Buchungs- oder Steuerannahmen werden nicht automatisch übernommen. Die lokalen Testfälle bleiben synthetisch.
