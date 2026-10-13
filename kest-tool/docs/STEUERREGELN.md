# Steuerregeln des KESt-Tools

> Automatisch erzeugt aus `src/kest_tool/data/tax_rules.yaml` – nicht von Hand bearbeiten.

Letzte Überprüfung: **2026-10-13**  
Hinweis: formulare.bmf.gv.at, www.bmf.gv.at, findok.bmf.gv.at, ris.bka.gv.at und oekb.at waren aus der Entwicklungsumgebung nicht direkt abrufbar. Verifikation erfolgte über Suchmaschinen-Auszüge.

## Verifikationsstatus

| Status | Bedeutung | Wirkung in der Berechnung |
|---|---|---|
| offiziell belegt (Auszug) | durch Auszug einer offiziellen Quelle bestätigt | berechnet |
| nur Sekundärquelle – vorläufig | nur Sekundärquellen | berechnet, als **vorläufig** markiert |
| nicht verifiziert – keine Berechnung | keine belastbare Grundlage | **kein Betrag**, Position „manuell steuerlich zu prüfen“ |

Steuerjahre ohne Eintrag in der Regeldatei werden vollständig abgelehnt (keine Berechnung).

## Regeln

### RATE_27_5 – Besonderer Steuersatz 27,5 % für Kapitaleinkünfte (Dividenden, Fondserträge, realisierte Wertsteigerungen)

- **Rechtsgrundlage:** § 27a Abs 1 Z 2 EStG 1988
- **Satz:** 27,5%
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Positive Einkünfte der 27,5-%-Gruppe nach Verlustausgleich × 27,5 %.
- **Bekannte Einschränkungen:** Option zur Regelbesteuerung (§ 27a Abs 5) wird nicht berechnet.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; BMF Formular E 1kv 2023 (Version vom 11.03.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2023/E1kv.pdf>; BMF Formular E 1kv 2022 (Version vom 12.04.2023) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2022/E1kv.pdf>; WKO – Besteuerung von Kapitalvermögen (Stand 01.05.2026) <https://www.wko.at/steuern/besteuerung-kapitalvermoegen>
- **Tests:** `test_tax_engine.py::test_simple_sale_with_known_cost`, `test_tax_engine.py::test_years_are_separate`
- **Letzte Prüfung:** 2026-10-13

### RATE_25 – Besonderer Steuersatz 25 % für Zinsen aus Geldeinlagen/nicht verbrieften Forderungen bei Kreditinstituten

- **Rechtsgrundlage:** § 27a Abs 1 Z 1 EStG 1988
- **Satz:** 25,0%
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Zinsen ohne ISIN werden als Geldeinlagenzinsen (25 %) vorgeschlagen; Einstufung immer prüfpflichtig.
- **Bekannte Einschränkungen:** Ob Zinsen eines Brokers Zinsen aus Geldeinlagen bei einem Kreditinstitut sind, wird nicht geprüft.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; WKO – Besteuerung von Kapitalvermögen (Stand 01.05.2026) <https://www.wko.at/steuern/besteuerung-kapitalvermoegen>
- **Tests:** `test_tax_engine.py::test_bank_interest_not_offset_with_losses`
- **Letzte Prüfung:** 2026-10-13

### COST_BASIS_AVERAGE – Gleitender Durchschnittspreis je Depot und Wertpapier

- **Rechtsgrundlage:** § 27a Abs 4 Z 3 EStG 1988
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Anschaffungskosten je Depot+ISIN als Summe/Bestand; Verkauf mindert anteilig.
- **Bekannte Einschränkungen:** Depotüberträge, Altbestände (vor 1.4.2012) und pauschale Anschaffungskosten (§ 93 Abs 4) nicht automatisch.
- **Quellen:** Wertpapier-Anschaffungskosten-VO / § 27a Abs 4 Z 3 EStG (gleitender Durchschnittspreis), Kommentarauszug <https://linda.lindeverlag.at/Dokument/76536_29___5___1___1___3/>
- **Tests:** `test_tax_engine.py::test_moving_average_cost_basis`
- **Letzte Prüfung:** 2026-10-13

### NO_INCIDENTAL_COSTS – Anschaffungsnebenkosten/Spesen nicht abzugsfähig (Privatvermögen, Sondersteuersatz)

- **Rechtsgrundlage:** § 27a Abs 4 Z 2 EStG; § 20 Abs 2 EStG (Abzugsverbot Werbungskosten)
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Kaufgebühren erhöhen die Anschaffungskosten NICHT; Verkaufsgebühren mindern den Erlös NICHT. Gebühren werden ausgewiesen.
- **Bekannte Einschränkungen:** Betriebsvermögen und Kryptowährungen nicht abgedeckt.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; VfGH 14.06.2017, G 336/2016 (Anschaffungsnebenkosten, § 27a Abs 4 Z 2 EStG) – Zusammenfassung <https://gesetzefinden.at/judikatur/vfgh/jfr_20170614_16g00336_01>
- **Tests:** `test_tax_engine.py::test_fees_not_deductible`
- **Letzte Prüfung:** 2026-10-13

### CAPITAL_REPAYMENT – Einlagen-/Kapitalrückzahlung mindert Anschaffungskosten; Überschuss = Veräußerungsvorgang

- **Rechtsgrundlage:** § 4 Abs 12 EStG 1988
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Nur wenn die Buchung ausdrücklich als Kapitalrückzahlung bestätigt ist (Beleg). Sonst ungeklärter Betrag.
- **Bekannte Einschränkungen:** Ob eine ausländische Ausschüttung steuerlich eine Einlagenrückzahlung ist, prüft das Tool nicht.
- **Quellen:** § 4 Abs 12 EStG – Einlagenrückzahlung (Emittenteninformationen, broker-test.at) <https://www.broker-test.at/news/kest-freie-dividende-behandlung-einer-ausschuettung-als-einlagenrueckzahlung-beim-privatinvestorkest-freie-dividende/>
- **Tests:** `test_tax_engine.py::test_capital_repayment_reduces_cost_basis`, `test_tax_engine.py::test_unverified_capital_repayment_is_unclear`
- **Letzte Prüfung:** 2026-10-13

### LOSS_OFFSET – Verlustausgleich innerhalb der Kapitaleinkünfte mit Sondersteuersatz; kein Ausgleich mit 25-%-Bankzinsen/Stiftungszuwendungen; kein Verlustvortrag

- **Rechtsgrundlage:** § 27 Abs 8 EStG 1988
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Verluste aus realisierten Wertänderungen werden mit positiven 27,5-%-Einkünften desselben Jahres verrechnet; Rest verfällt.
- **Bekannte Einschränkungen:** Derivate, Kryptowährungen, Tarifeinkünfte und Stiftungszuwendungen werden nicht verarbeitet.
- **Quellen:** Linde Kommentar zu § 27 Abs 8 EStG (Verlustausgleich, kein Verlustvortrag) <https://linda.lindeverlag.at/Dokument/76536_20___4/>; VfGH 02.03.2021, E 1722/2020 (Verlustausgleich § 27 Abs 8 EStG) – Zusammenfassung <https://gesetzefinden.at/judikatur/vfgh/jfr_20210302_20e01722_01>; BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>
- **Tests:** `test_tax_engine.py::test_restricted_loss_offset`
- **Letzte Prüfung:** 2026-10-13

### LOSS_OFFSET_ORDER – Reihenfolge der Verlustverrechnung (Darstellung)

- **Rechtsgrundlage:** keine verifizierte gesetzliche Reihenfolge
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Annahme: Verrechnung zuerst mit Einkünften ohne ausländische Quellensteuer. Nur Darstellung; maßgeblich ist die Veranlagung.
- **Bekannte Einschränkungen:** Auswirkung auf die anrechenbare Quellensteuer ist ein Schätzwert.
- **Quellen:** keine
- **Tests:** `test_tax_engine.py::test_restricted_loss_offset`
- **Letzte Prüfung:** 2026-10-13

### FOREIGN_TAX_CREDIT – Anrechnung ausländischer Quellensteuer: höchstens DBA-Satz, höchstens österreichische Steuer auf diese Einkünfte; erstattbare Steuer nicht anrechenbar

- **Rechtsgrundlage:** E 1kv Erläuterung (Fußnote zu KZ 940/984/998/900/901); jeweiliges DBA
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** anrechenbar = min(einbehalten, Brutto × DBA-Satz, Brutto × 27,5 %); Rest = nicht anrechenbar (ggf. im Quellenstaat rückforderbar).
- **Bekannte Einschränkungen:** Nur Länder mit hinterlegtem, als verifiziert markiertem DBA-Satz. Sonst ungeklärter Betrag.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; BMF-Findok 83782 – Anrechnung US-Quellensteuer nach DBA-USA (15 %) <https://findok.bmf.gv.at/findok/iwg/83/83782/83782.1.pdf>
- **Tests:** `test_tax_engine.py::test_dividend_with_withholding_tax`
- **Letzte Prüfung:** 2026-10-13

### DOMESTIC_KEST – Bereits einbehaltene österreichische KESt (inländische Kapitaleinkünfte) – Anrechnung/Endbesteuerung

- **Rechtsgrundlage:** § 97 EStG; E 1kv KZ 899
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Depots mit KESt-Abzug durch den Broker → Einkünfte gelten als „inländisch“; einbehaltene KESt wird separat ausgewiesen (KZ 899) und nicht doppelt besteuert.
- **Bekannte Einschränkungen:** Ob der Broker tatsächlich österreichische KESt abführt, muss je Depot und Jahr bestätigt werden.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>
- **Tests:** `test_tax_engine.py::test_domestic_kest_not_double_counted`
- **Letzte Prüfung:** 2026-10-13

### MELDEFONDS_AGE – Meldefonds: ausschüttungsgleiche Erträge laut OeKB-Meldung; Zufluss zum Meldezeitpunkt; AK-Korrektur

- **Rechtsgrundlage:** § 186 Abs 2 Z 1 und Abs 3 InvFG 2011
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** AgE = AgE je Anteil × Bestand zum Meldedatum; anrechenbare Steuer je Anteil × Bestand; AK + Korrekturbetrag × Bestand.
- **Bekannte Einschränkungen:** Nur mit importierter/erfasster Meldung. Fehlende Meldung → manuelle Prüfung (ggf. Nichtmeldefonds).
- **Quellen:** § 186 InvFG 2011 (RIS) – Fassungen bis 31.12.2023 / 1.1.–19.7.2024 (BGBl I 111/2023) / ab 20.7.2024 (BGBl I 113/2024) <https://www.ris.bka.gv.at/eli/bgbl/i/2011/77/P186/NOR40254753>; broker-test.at – Ausschüttungsgleiche Erträge (KZ 936/937) <https://www.broker-test.at/steuern/ausschuettungsgleiche-ertraege/>
- **Tests:** `test_tax_engine.py::test_meldefonds_age`, `test_tax_engine.py::test_fund_income_not_double_counted`
- **Letzte Prüfung:** 2026-10-13

### NICHTMELDEFONDS_PAUSCHAL – Nichtmeldefonds: pauschale AgE = 90 % des Unterschieds erster/letzter Rücknahmepreis, mindestens 10 % des letzten Rücknahmepreises; Zufluss 31.12.

- **Rechtsgrundlage:** § 186 Abs 2 Z 3 InvFG 2011
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** je Anteil max(0,9 × (letzter − erster Rücknahmepreis), 0,1 × letzter Rücknahmepreis) × Bestand 31.12.; AK-Erhöhung.
- **Bekannte Einschränkungen:** Selbstnachweis, Sonderregel bei fehlendem Rücknahmepreis und unterjährige Veräußerung nicht implementiert.
- **Quellen:** § 186 InvFG 2011 (RIS) – Fassungen bis 31.12.2023 / 1.1.–19.7.2024 (BGBl I 111/2023) / ab 20.7.2024 (BGBl I 113/2024) <https://www.ris.bka.gv.at/eli/bgbl/i/2011/77/P186/NOR40254753>; Linde Kommentar zu § 186 InvFG (Pauschalermittlung Nichtmeldefonds 90 % / mind. 10 %) <https://linda.lindeverlag.at/Dokument/76540_3___1___1___2___/>; BMF-Findok 145784 – Schätzung ausschüttungsgleicher Erträge Nichtmeldefonds (10 % Rücknahmepreis) <https://findok.bmf.gv.at/findok/iwg/145/145784/145784.1.pdf>
- **Tests:** `test_tax_engine.py::test_nichtmeldefonds_pauschal_2023`, `test_tax_engine.py::test_nichtmeldefonds_unverified_year_not_computed`
- **Letzte Prüfung:** 2026-10-13

### NICHTMELDEFONDS_DISTRIBUTIONS – Nichtmeldefonds: tatsächliche Ausschüttungen zusätzlich steuerpflichtig (kein Abzug von der Pauschale)

- **Rechtsgrundlage:** § 186 Abs 2 Z 3 InvFG 2011
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Ausschüttungen eines Nichtmeldefonds = steuerpflichtige Fondsausschüttung.
- **Bekannte Einschränkungen:** –
- **Quellen:** Linde Kommentar zu § 186 InvFG (Pauschalermittlung Nichtmeldefonds 90 % / mind. 10 %) <https://linda.lindeverlag.at/Dokument/76540_3___1___1___2___/>
- **Tests:** `test_tax_engine.py::test_meldefonds_vs_nichtmeldefonds`
- **Letzte Prüfung:** 2026-10-13

### REIT_BDC – REITs/BDCs: keine automatische Ableitung aus Wertpapierart

- **Rechtsgrundlage:** Grundsatz: Einstufung nach Rechtsform/Beleg, nicht nach Bezeichnung
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Ertragsbestandteile werden nur nach bestätigter Klassifizierung je Buchung berücksichtigt, sonst ungeklärt.
- **Bekannte Einschränkungen:** Behandlung als ausländischer Immobilienfonds (ImmoInvFG) nicht implementiert.
- **Quellen:** keine
- **Tests:** `test_tax_engine.py::test_reit_without_classification_is_unclear`
- **Letzte Prüfung:** 2026-10-13

### FX_CONVERSION – Umrechnung Fremdwährung in EUR

- **Rechtsgrundlage:** nicht verifiziert
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Es wird ausschließlich der im Beleg/vom Benutzer angegebene Kurs verwendet; ohne Kurs kein EUR-Betrag. Positionen in Fremdwährung sind vorläufig.
- **Bekannte Einschränkungen:** Keine automatische Kursbeschaffung.
- **Quellen:** keine
- **Tests:** `test_tax_engine.py::test_missing_data_detected`
- **Letzte Prüfung:** 2026-10-13

## Quellen

| ID | Titel | Art | URL |
|---|---|---|---|
| E1KV_2024 | BMF Formular E 1kv 2024 (Version vom 02.10.2024) | offiziell | <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf> |
| E1KV_2023 | BMF Formular E 1kv 2023 (Version vom 11.03.2024) | offiziell | <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2023/E1kv.pdf> |
| E1KV_2022 | BMF Formular E 1kv 2022 (Version vom 12.04.2023) | offiziell | <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2022/E1kv.pdf> |
| ESTG_27 | § 27 EStG 1988 (RIS, Bundesrecht konsolidiert) | offiziell | <https://www.ris.bka.gv.at/eli/bgbl/1988/400/P27/NOR40130674> |
| ESTG_27A | § 27a EStG 1988 (RIS) | offiziell | <https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40137806/NOR40137806.pdf> |
| VFGH_2017_G336 | VfGH 14.06.2017, G 336/2016 (Anschaffungsnebenkosten, § 27a Abs 4 Z 2 EStG) – Zusammenfassung | sekundaer_zu_offiziell | <https://gesetzefinden.at/judikatur/vfgh/jfr_20170614_16g00336_01> |
| VFGH_2021_VERLUST | VfGH 02.03.2021, E 1722/2020 (Verlustausgleich § 27 Abs 8 EStG) – Zusammenfassung | sekundaer_zu_offiziell | <https://gesetzefinden.at/judikatur/vfgh/jfr_20210302_20e01722_01> |
| LINDE_ESTR_27_8 | Linde Kommentar zu § 27 Abs 8 EStG (Verlustausgleich, kein Verlustvortrag) | sekundaer | <https://linda.lindeverlag.at/Dokument/76536_20___4/> |
| INVFG_186 | § 186 InvFG 2011 (RIS) – Fassungen bis 31.12.2023 / 1.1.–19.7.2024 (BGBl I 111/2023) / ab 20.7.2024 (BGBl I 113/2024) | offiziell | <https://www.ris.bka.gv.at/eli/bgbl/i/2011/77/P186/NOR40254753> |
| LINDE_INVFG_186 | Linde Kommentar zu § 186 InvFG (Pauschalermittlung Nichtmeldefonds 90 % / mind. 10 %) | sekundaer | <https://linda.lindeverlag.at/Dokument/76540_3___1___1___2___/> |
| FINDOK_145784 | BMF-Findok 145784 – Schätzung ausschüttungsgleicher Erträge Nichtmeldefonds (10 % Rücknahmepreis) | offiziell | <https://findok.bmf.gv.at/findok/iwg/145/145784/145784.1.pdf> |
| FINDOK_DBA_USA | BMF-Findok 83782 – Anrechnung US-Quellensteuer nach DBA-USA (15 %) | offiziell | <https://findok.bmf.gv.at/findok/iwg/83/83782/83782.1.pdf> |
| BROKERTEST_AGE | broker-test.at – Ausschüttungsgleiche Erträge (KZ 936/937) | sekundaer | <https://www.broker-test.at/steuern/ausschuettungsgleiche-ertraege/> |
| ESTG_4_12 | § 4 Abs 12 EStG – Einlagenrückzahlung (Emittenteninformationen, broker-test.at) | sekundaer | <https://www.broker-test.at/news/kest-freie-dividende-behandlung-einer-ausschuettung-als-einlagenrueckzahlung-beim-privatinvestorkest-freie-dividende/> |
| WKO_KAPITAL_2026 | WKO – Besteuerung von Kapitalvermögen (Stand 01.05.2026) | sekundaer | <https://www.wko.at/steuern/besteuerung-kapitalvermoegen> |
| WP_AK_VO | Wertpapier-Anschaffungskosten-VO / § 27a Abs 4 Z 3 EStG (gleitender Durchschnittspreis), Kommentarauszug | sekundaer | <https://linda.lindeverlag.at/Dokument/76536_29___5___1___1___3/> |
| OEKB_DATEN | OeKB – Fondsdaten-Portal / Fondsdaten Plus / Nutzungsbedingungen | offiziell | <https://www.oekb.at/kapitalmarkt-services/unser-datenangebot/fonds/oekb-fondsdaten-portal.html> |

## DBA-Quellensteuersätze (Dividenden)

| Land | Satz | verifiziert | Hinweis |
|---|---|---|---|
| US | 15% | ja | DBA-USA: Begrenzung auf 15 % für natürliche Personen (BMF-Findok) |
| DE | 15% | nein | Sekundärquellen nennen 15 % – DBA Österreich–Deutschland prüfen |
| CH | 15% | nein | Sekundärquellen nennen 15 % (35 % Einbehalt, Rest rückforderbar) – DBA prüfen |
| NL | 15% | nein | Sekundärquellen nennen 15 % – DBA prüfen |
| FR | – | nein | Widersprüchliche Sekundärquellen (12,8 % / 15 %) – DBA prüfen |
| IE | – | nein | Nicht geprüft |
| GB | – | nein | Nicht geprüft |
| CA | – | nein | Nicht geprüft |

## E 1kv-Kennzahlen

### 2022 – E 1kv 2022 (Version 12.04.2023) – Kennzahlenstruktur laut Auszug wie 2024

| Schlüssel | KZ | Bezeichnung | Status |
|---|---|---|---|
| dividends_inland | 862 | Einkünfte aus der Überlassung von Kapital (inländisch, 27,5 %) | offiziell belegt (Auszug) |
| dividends_ausland | 863 | Einkünfte aus der Überlassung von Kapital (ausländisch, 27,5 %) | offiziell belegt (Auszug) |
| fund_dist_inland | 897 | Ausschüttungen Investmentfonds (inländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| fund_dist_ausland | 898 | Ausschüttungen Investmentfonds (ausländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| age_inland | 936 | Ausschüttungsgleiche Erträge (inländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| age_ausland | 937 | Ausschüttungsgleiche Erträge (ausländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| gains_inland | 981 | Einkünfte aus realisierten Wertsteigerungen (inländisch, 27,5 %) | offiziell belegt (Auszug) |
| gains_ausland | 994 | Einkünfte aus realisierten Wertsteigerungen (ausländisch, 27,5 %) | offiziell belegt (Auszug) |
| losses_inland | 891 | Verluste aus realisierten Wertsteigerungen (inländisch) | offiziell belegt (Auszug) |
| losses_ausland | 892 | Verluste aus realisierten Wertsteigerungen (ausländisch) | offiziell belegt (Auszug) |
| interest25_ausland | 861 | Zinsen aus Geldeinlagen bei Kreditinstituten (ausländisch, 25 %) | nur Sekundärquelle – vorläufig |
| interest25_inland | 860 | Zinsen aus Geldeinlagen bei Kreditinstituten (inländisch, 25 %) | nur Sekundärquelle – vorläufig |
| kest_inland | 899 | Einbehaltene KESt auf inländische Kapitaleinkünfte | offiziell belegt (Auszug) |
| foreign_tax_27_5 | 998 | Anrechenbare ausländische (Quellen)Steuer auf Einkünfte mit 27,5 % | nur Sekundärquelle – vorläufig |
- Die Fußnote zu den Quellensteuer-Kennzahlen nennt KZ 940, 984, 998, 900 und 901; die exakte Zuordnung je Einkunftsart ist im Formular zu prüfen.
- Werbungskosten sind auch bei Regelbesteuerungsoption nicht abzugsfähig (Formularhinweis).
- Durch die Erfassung von Substanzverlusten in 891/892 bzw. 895/896 wird die Verlustausgleichsoption ausgeübt (Formularhinweis).
- Derivate (982/995, 895/896) und Kryptowährungen (171–174) werden vom Tool nicht berechnet.

### 2023 – E 1kv 2023 (Version 11.03.2024) – Kennzahlenstruktur laut Auszug wie 2024

| Schlüssel | KZ | Bezeichnung | Status |
|---|---|---|---|
| dividends_inland | 862 | Einkünfte aus der Überlassung von Kapital (inländisch, 27,5 %) | offiziell belegt (Auszug) |
| dividends_ausland | 863 | Einkünfte aus der Überlassung von Kapital (ausländisch, 27,5 %) | offiziell belegt (Auszug) |
| fund_dist_inland | 897 | Ausschüttungen Investmentfonds (inländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| fund_dist_ausland | 898 | Ausschüttungen Investmentfonds (ausländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| age_inland | 936 | Ausschüttungsgleiche Erträge (inländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| age_ausland | 937 | Ausschüttungsgleiche Erträge (ausländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| gains_inland | 981 | Einkünfte aus realisierten Wertsteigerungen (inländisch, 27,5 %) | offiziell belegt (Auszug) |
| gains_ausland | 994 | Einkünfte aus realisierten Wertsteigerungen (ausländisch, 27,5 %) | offiziell belegt (Auszug) |
| losses_inland | 891 | Verluste aus realisierten Wertsteigerungen (inländisch) | offiziell belegt (Auszug) |
| losses_ausland | 892 | Verluste aus realisierten Wertsteigerungen (ausländisch) | offiziell belegt (Auszug) |
| interest25_ausland | 861 | Zinsen aus Geldeinlagen bei Kreditinstituten (ausländisch, 25 %) | nur Sekundärquelle – vorläufig |
| interest25_inland | 860 | Zinsen aus Geldeinlagen bei Kreditinstituten (inländisch, 25 %) | nur Sekundärquelle – vorläufig |
| kest_inland | 899 | Einbehaltene KESt auf inländische Kapitaleinkünfte | offiziell belegt (Auszug) |
| foreign_tax_27_5 | 998 | Anrechenbare ausländische (Quellen)Steuer auf Einkünfte mit 27,5 % | nur Sekundärquelle – vorläufig |
- Die Fußnote zu den Quellensteuer-Kennzahlen nennt KZ 940, 984, 998, 900 und 901; die exakte Zuordnung je Einkunftsart ist im Formular zu prüfen.
- Werbungskosten sind auch bei Regelbesteuerungsoption nicht abzugsfähig (Formularhinweis).
- Durch die Erfassung von Substanzverlusten in 891/892 bzw. 895/896 wird die Verlustausgleichsoption ausgeübt (Formularhinweis).
- Derivate (982/995, 895/896) und Kryptowährungen (171–174) werden vom Tool nicht berechnet.

### 2024 – E 1kv 2024 (Version 02.10.2024)

| Schlüssel | KZ | Bezeichnung | Status |
|---|---|---|---|
| dividends_inland | 862 | Einkünfte aus der Überlassung von Kapital (inländisch, 27,5 %) | offiziell belegt (Auszug) |
| dividends_ausland | 863 | Einkünfte aus der Überlassung von Kapital (ausländisch, 27,5 %) | offiziell belegt (Auszug) |
| fund_dist_inland | 897 | Ausschüttungen Investmentfonds (inländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| fund_dist_ausland | 898 | Ausschüttungen Investmentfonds (ausländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| age_inland | 936 | Ausschüttungsgleiche Erträge (inländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| age_ausland | 937 | Ausschüttungsgleiche Erträge (ausländisches Depot, 27,5 %) | offiziell belegt (Auszug) |
| gains_inland | 981 | Einkünfte aus realisierten Wertsteigerungen (inländisch, 27,5 %) | offiziell belegt (Auszug) |
| gains_ausland | 994 | Einkünfte aus realisierten Wertsteigerungen (ausländisch, 27,5 %) | offiziell belegt (Auszug) |
| losses_inland | 891 | Verluste aus realisierten Wertsteigerungen (inländisch) | offiziell belegt (Auszug) |
| losses_ausland | 892 | Verluste aus realisierten Wertsteigerungen (ausländisch) | offiziell belegt (Auszug) |
| interest25_ausland | 861 | Zinsen aus Geldeinlagen bei Kreditinstituten (ausländisch, 25 %) | nur Sekundärquelle – vorläufig |
| interest25_inland | 860 | Zinsen aus Geldeinlagen bei Kreditinstituten (inländisch, 25 %) | nur Sekundärquelle – vorläufig |
| kest_inland | 899 | Einbehaltene KESt auf inländische Kapitaleinkünfte | offiziell belegt (Auszug) |
| foreign_tax_27_5 | 998 | Anrechenbare ausländische (Quellen)Steuer auf Einkünfte mit 27,5 % | nur Sekundärquelle – vorläufig |
- Die Fußnote zu den Quellensteuer-Kennzahlen nennt KZ 940, 984, 998, 900 und 901; die exakte Zuordnung je Einkunftsart ist im Formular zu prüfen.
- Werbungskosten sind auch bei Regelbesteuerungsoption nicht abzugsfähig (Formularhinweis).
- Durch die Erfassung von Substanzverlusten in 891/892 bzw. 895/896 wird die Verlustausgleichsoption ausgeübt (Formularhinweis).
- Derivate (982/995, 895/896) und Kryptowährungen (171–174) werden vom Tool nicht berechnet.

### 2025 – E 1kv 2025 – NICHT verifiziert

- Für 2025 lag kein prüfbarer Auszug des offiziellen Formulars vor. Die Kennzahlen 2024 werden nur als Hinweis angezeigt.

### 2026 – E 1kv 2026 – NICHT verifiziert

- Für 2026 lag kein prüfbarer Auszug des offiziellen Formulars vor. Die Kennzahlen 2024 werden nur als Hinweis angezeigt.
