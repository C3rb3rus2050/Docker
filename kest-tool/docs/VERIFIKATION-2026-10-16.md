# Quellenprüfung und Änderungen vom 16.10.2026

## Amtliche Formulare

- [E 1kv 2025, Version 27.06.2025](https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download): Original-PDF, vier Seiten, einschließlich Spalten und Erläuterungen geprüft. Die URL ohne `?open=download` liefert eine HTML-Zwischenseite; HTTP 200 allein ist kein PDF-Nachweis.
- [BMF-XML-Struktur 2025](https://www.bmf.gv.at/dam/jcr%3Afd281668-2d12-4066-9942-c5685f6cc247/BMF_XML_Jahreserklaerungen_2025.xml): Kennzahlen im E1-Abschnitt `EINKUENFTE_KAPITALVERMOEGEN` zusätzlich abgeglichen. Das XML allein belegt keine inhaltliche Zuordnung.
- Bestätigt für 2025: 860/861, 862/863, 981/994, 891/892, 897/898, 936/937, 899; Quellensteuer 984/998 (27,5 %) und 900/901 (25 %); verbriefte Derivate 982/995, Verluste 895/896.
- Für 2026 konnte am Prüftag kein Originalformular abgerufen werden. Die Anwendung verwendet ausdrücklich unverifizierte Planungshinweise aus 2025. Die Kennzahlen werden nicht als verifiziert fortgeschrieben.
- KZ 189 benötigt gesonderte Angaben zu bereits auf Fondsebene erfassten inländischen Dividenden und wird nicht automatisch befüllt.

## Nichtmeldefonds

[§ 186 Abs 2 Z 3 und Abs 3 InvFG, Fassung BGBl I 113/2024](https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40263477/NOR40263477.html) bestätigt weiterhin die jährliche Pauschale: Maximum aus 90 % der Differenz erster/letzter Rücknahmepreis und 10 % des letzten Rücknahmepreises. Zufluss ist der 31. Dezember. Ausschüttungen ohne Meldung sind voll steuerpflichtig; Selbstnachweise sind gesondert möglich.

Die bisherige Sperre für 2024–2026 ist aufgehoben. Ohne Preise oder Devisenkurs gibt es weiterhin keinen berechneten Betrag. Die Pauschale erhöht die Anschaffungskosten nun auch in der Bestandsübersicht des laufenden Jahres. Fehlende historische Fondsdaten blockieren davon abhängige Verkaufsberechnungen. Unterjährige Sonderfälle, Selbstnachweise und unvollständige Jahresdaten erfordern weiter Einzelprüfung.

## DBA für gewöhnliche Dividenden natürlicher Personen

Zusätzlich zu USA sind folgende 15-%-Höchstsätze anhand amtlicher Texte hinterlegt:

- [Deutschland, Art 10 Abs 2 lit b](https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Anlage=&Artikel=10&FassungVom=2024-01-20&Gesetzesnummer=20002157&Paragraf=&Uebergangsrecht=)
- [Schweiz, Art 10 Abs 2 und Art 23](https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004202)
- [Niederlande, Art 10 Abs 2](https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004091)
- [Kanada, Art 10 Abs 2 lit b, synthetisierte Fassung](https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40220703/III_93_2018_DBA_Kanada_synthesised_deutsch_final.pdf)

Dies sind Anrechnungshöchstsätze, keine Aussage über tatsächlich einbehaltene Steuern. DBA-Ansässigkeit und Nutzungsberechtigung werden vorausgesetzt; Sondergesellschaften, Betriebsstätten und Fonds sind nicht durch einen gewöhnlichen Dividendensatz abgedeckt. FR/IE/GB bleiben ohne generelle Freigabe. Dividendensätze werden nicht mehr fälschlich auf Zinsen angewendet.

## Derivate, Altbestand und Kapitalmaßnahmen

[§ 27a EStG, Fassung ab 20.07.2024](https://www.ris.bka.gv.at/eli/bgbl/1988/400/P27a/NOR40263362) und das E-1kv-Formular 2025 belegen die Behandlung verbriefter Derivate. Für 2025/2026 werden Verkäufe aus belegten Long-Beständen unterstützt, wenn die neue steuerliche Klasse **Öffentlich begebenes verbrieftes Derivat** mit Emittentenquelle geprüft ist. Kauf und Verkauf sind die Buchungsarten; Rückzahlung eines solchen Wertpapiers kann als Verkauf mit tatsächlichem Erlös erfasst werden. Kennzahlen sind getrennt von Aktiengewinnen/-verlusten. Für 2026 bleibt die Formularzuordnung unverifiziert.

Nicht erfasst: Shorts, Stillhaltergeschäfte, physische Ausübungen, unverbriefte Derivate, Privatplatzierungen, automatische Behandlung bloß anhand einer ISIN oder Brokerbezeichnung. Die bisherige allgemeine Klasse Derivat bleibt manuell.

Historische Erwerbe werden konservativ angehalten: bei geprüften Aktien/Fonds vor 1.1.2011, bei anderen/ungeklärten Wertpapieren vor 1.4.2012. Das ist eine Prüfungssperre, **keine automatische Steuerbefreiung**. Gemischte Alt-/Neubestände, wesentliche Beteiligungen und Übertragsdaten sind nicht vollständig modelliert. Eine ungeklärte Kapitalmaßnahme sperrt auch Verkaufsberechnungen späterer Jahre. Splits und Reverse-Splits bleiben über das belegte Verhältnis unterstützt. Fusionen und Abspaltungen werden nicht anhand ihrer Bezeichnung automatisch bewertet.

## Nachvollziehbarkeit und technische Korrekturen

- Gemischte taggleiche Bestandsänderungen benötigen eine tatsächliche, eindeutige `execution_order` je Depot und ISIN. Unter **Buchungen → Weitere Spalten anzeigen → Reihenfolge am Tag** bearbeiten. Die Reihenfolge darf nicht aus der Upload-Reihenfolge abgeleitet werden.
- Geprüfte/ungeprüfte Fondskorrekturen bleiben als Hinweise bei späteren Verkäufen und Beständen sichtbar.
- Kapitalrückzahlungen erzeugen bei unbekannten Anschaffungskosten keinen erfundenen Überschuss.
- Excel speichert importierte Textwerte ausdrücklich als Text; CSV neutralisiert führende Formelzeichen. Echte numerische Verluste und erzeugte Summenformeln bleiben erhalten.
- Nichtendliche Buchungswerte werden abgelehnt; bestehende Datenbanken erhalten die neue Reihenfolgenspalte automatisch (Schema 4).

## Echte Dokumente und Testgrenzen

Ein reproduzierbarer Test prüft fünf unveränderte öffentliche Broker-Textauszüge aus einem festgelegten Portfolio-Performance-Commit samt SHA-256. Referenzen und manuell abgeglichene Erwartungen stehen in `tests/public_layout_manifest.json`. Keine fremden Originalbelege werden in dieses Repository kopiert.

```bash
python scripts/validate_broker_corpus.py tests/public_layout_manifest.json --public
```

Die Fälle umfassen Trade Republic Kauf/Sparplan/Dividende, Scalable Dividende und Baader Kauf. Drei Fälle sind eindeutig; zwei müssen wegen Quellenstaat bzw. widersprüchlicher Kurse/deutscher Steuern zur Prüfung offen bleiben. Ein bestandenes Prüfkennzeichen bedeutet daher nicht, dass jeder Beleg automatisch gebucht wird.

**Original-PDF-Extraktion und OCR mit echten Kundendokumenten sind damit nicht verifiziert.** Für einen lokalen anonymisierten PDF-Bestand kann derselbe Runner mit einem privaten Manifest ausgeführt werden. Ohne `--public` erfolgt kein Dokumentdownload. Manifestformat:

```json
[{"file":"anonymisiert.pdf","expected":{"tx_type":"Kauf","amount":100.0,"quantity":1.0,"currency":"EUR","trade_date":"2025-01-02","complete":true}}]
```

```bash
python scripts/validate_broker_corpus.py /sicherer/pfad/manifest.json
```

Erwartungen zuvor am Original ablesen. Der Runner gibt nur Fallnummer, Status und abweichende Feldnamen aus. Private PDFs, Textauszüge und Manifeste außerhalb des Git-Checkouts halten. Die Dokumente werden nicht an externe Dienste übermittelt.
