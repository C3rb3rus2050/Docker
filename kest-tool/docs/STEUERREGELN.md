# Steuerregeln des KESt-Tools

> Automatisch erzeugt aus `src/kest_tool/data/tax_rules.yaml` – nicht von Hand bearbeiten.

Letzte Überprüfung: **2026-10-16**
Hinweis: Am 16.10.2026 wurden E 1kv 2025 (Version 27.06.2025), BMF-XML 2025, RIS § 186 InvFG sowie DBA DE/CH/NL/CA im Volltext geprüft. Frühere Quellen bleiben als Auszüge gekennzeichnet. Ein amtliches E 1kv 2026 konnte nicht abgerufen werden; keine Freigabe durch Fortschreibung.

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
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: offiziell belegt (Auszug), 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Positive Einkünfte der 27,5-%-Gruppe nach Verlustausgleich × 27,5 %.
- **Bekannte Einschränkungen:** Option zur Regelbesteuerung (§ 27a Abs 5) wird nicht berechnet.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; BMF Formular E 1kv 2023 (Version vom 11.03.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2023/E1kv.pdf>; BMF Formular E 1kv 2022 (Version vom 12.04.2023) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2022/E1kv.pdf>; WKO – Besteuerung von Kapitalvermögen (Stand 01.05.2026) <https://www.wko.at/steuern/besteuerung-kapitalvermoegen>; BMF E 1kv 2025, Version 27.06.2025, Seiten 1–4; geprüft 16.10.2026 <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download>
- **Tests:** `test_tax_engine.py::test_simple_sale_with_known_cost`, `test_tax_engine.py::test_years_are_separate`
- **Letzte Prüfung:** 2026-10-16

### RATE_25 – Besonderer Steuersatz 25 % für Zinsen aus Geldeinlagen/nicht verbrieften Forderungen bei Kreditinstituten

- **Rechtsgrundlage:** § 27a Abs 1 Z 1 EStG 1988
- **Satz:** 25,0%
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: offiziell belegt (Auszug), 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Zinsen ohne ISIN werden als Geldeinlagenzinsen (25 %) vorgeschlagen; Einstufung immer prüfpflichtig.
- **Bekannte Einschränkungen:** Ob Zinsen eines Brokers Zinsen aus Geldeinlagen bei einem Kreditinstitut sind, wird nicht geprüft.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; WKO – Besteuerung von Kapitalvermögen (Stand 01.05.2026) <https://www.wko.at/steuern/besteuerung-kapitalvermoegen>; BMF E 1kv 2025, Version 27.06.2025, Seiten 1–4; geprüft 16.10.2026 <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download>
- **Tests:** `test_tax_engine.py::test_bank_interest_not_offset_with_losses`
- **Letzte Prüfung:** 2026-10-16

### COST_BASIS_AVERAGE – Gleitender Durchschnittspreis je Depot und Wertpapier

- **Rechtsgrundlage:** § 27a Abs 4 Z 3 EStG 1988
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Anschaffungskosten je Depot+ISIN als Summe/Bestand; Verkauf mindert anteilig.
- **Bekannte Einschränkungen:** Depotüberträge, Altbestände (vor 1.4.2012) und pauschale Anschaffungskosten (§ 93 Abs 4) nicht automatisch.
- **Quellen:** Wertpapier-Anschaffungskosten-VO / § 27a Abs 4 Z 3 EStG (gleitender Durchschnittspreis), Kommentarauszug <https://linda.lindeverlag.at/Dokument/76536_29___5___1___1___3/>
- **Tests:** `test_tax_engine.py::test_moving_average_cost_basis`
- **Letzte Prüfung:** 2026-10-16

### NO_INCIDENTAL_COSTS – Anschaffungsnebenkosten/Spesen nicht abzugsfähig (Privatvermögen, Sondersteuersatz)

- **Rechtsgrundlage:** § 27a Abs 4 Z 2 EStG; § 20 Abs 2 EStG (Abzugsverbot Werbungskosten)
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Kaufgebühren erhöhen die Anschaffungskosten NICHT; Verkaufsgebühren mindern den Erlös NICHT. Gebühren werden ausgewiesen.
- **Bekannte Einschränkungen:** Betriebsvermögen und Kryptowährungen nicht abgedeckt.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; VfGH 14.06.2017, G 336/2016 (Anschaffungsnebenkosten, § 27a Abs 4 Z 2 EStG) – Zusammenfassung <https://gesetzefinden.at/judikatur/vfgh/jfr_20170614_16g00336_01>
- **Tests:** `test_tax_engine.py::test_fees_not_deductible`
- **Letzte Prüfung:** 2026-10-16

### CAPITAL_REPAYMENT – Einlagen-/Kapitalrückzahlung mindert Anschaffungskosten; Überschuss = Veräußerungsvorgang

- **Rechtsgrundlage:** § 4 Abs 12 EStG 1988
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Nur wenn die Buchung ausdrücklich als Kapitalrückzahlung bestätigt ist (Beleg). Sonst ungeklärter Betrag.
- **Bekannte Einschränkungen:** Ob eine ausländische Ausschüttung steuerlich eine Einlagenrückzahlung ist, prüft das Tool nicht.
- **Quellen:** § 4 Abs 12 EStG – Einlagenrückzahlung (Emittenteninformationen, broker-test.at) <https://www.broker-test.at/news/kest-freie-dividende-behandlung-einer-ausschuettung-als-einlagenrueckzahlung-beim-privatinvestorkest-freie-dividende/>
- **Tests:** `test_tax_engine.py::test_capital_repayment_reduces_cost_basis`, `test_tax_engine.py::test_unverified_capital_repayment_is_unclear`
- **Letzte Prüfung:** 2026-10-16

### LOSS_OFFSET – Verlustausgleich innerhalb der Kapitaleinkünfte mit Sondersteuersatz; kein Ausgleich mit 25-%-Bankzinsen/Stiftungszuwendungen; kein Verlustvortrag

- **Rechtsgrundlage:** § 27 Abs 8 EStG 1988
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Verluste aus realisierten Wertänderungen werden mit positiven 27,5-%-Einkünften desselben Jahres verrechnet; Rest verfällt.
- **Bekannte Einschränkungen:** Derivate, Kryptowährungen, Tarifeinkünfte und Stiftungszuwendungen werden nicht verarbeitet.
- **Quellen:** Linde Kommentar zu § 27 Abs 8 EStG (Verlustausgleich, kein Verlustvortrag) <https://linda.lindeverlag.at/Dokument/76536_20___4/>; VfGH 02.03.2021, E 1722/2020 (Verlustausgleich § 27 Abs 8 EStG) – Zusammenfassung <https://gesetzefinden.at/judikatur/vfgh/jfr_20210302_20e01722_01>; BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>
- **Tests:** `test_tax_engine.py::test_restricted_loss_offset`
- **Letzte Prüfung:** 2026-10-16

### LOSS_OFFSET_ORDER – Reihenfolge der Verlustverrechnung (Darstellung)

- **Rechtsgrundlage:** keine verifizierte gesetzliche Reihenfolge
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Annahme: Verrechnung zuerst mit Einkünften ohne ausländische Quellensteuer. Nur Darstellung; maßgeblich ist die Veranlagung.
- **Bekannte Einschränkungen:** Auswirkung auf die anrechenbare Quellensteuer ist ein Schätzwert.
- **Quellen:** keine
- **Tests:** `test_tax_engine.py::test_restricted_loss_offset`
- **Letzte Prüfung:** 2026-10-16

### FOREIGN_TAX_CREDIT – Anrechnung ausländischer Quellensteuer: höchstens DBA-Satz, höchstens österreichische Steuer auf diese Einkünfte; erstattbare Steuer nicht anrechenbar

- **Rechtsgrundlage:** E 1kv Erläuterung (Fußnote zu KZ 940/984/998/900/901); jeweiliges DBA
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: offiziell belegt (Auszug), 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** anrechenbar = min(einbehalten, Brutto × DBA-Satz, Brutto × 27,5 %); Rest = nicht anrechenbar (ggf. im Quellenstaat rückforderbar).
- **Bekannte Einschränkungen:** Nur Länder mit hinterlegtem, als verifiziert markiertem DBA-Satz. Sonst ungeklärter Betrag.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; BMF-Findok 83782 – Anrechnung US-Quellensteuer nach DBA-USA (15 %) <https://findok.bmf.gv.at/findok/iwg/83/83782/83782.1.pdf>; BMF E 1kv 2025, Version 27.06.2025, Seiten 1–4; geprüft 16.10.2026 <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download>
- **Tests:** `test_tax_engine.py::test_dividend_with_withholding_tax`
- **Letzte Prüfung:** 2026-10-16

### DOMESTIC_KEST – Bereits einbehaltene österreichische KESt (inländische Kapitaleinkünfte) – Anrechnung/Endbesteuerung

- **Rechtsgrundlage:** § 97 EStG; E 1kv KZ 899
- **Gültigkeit / Status je Steuerjahr:** 2022: offiziell belegt (Auszug), 2023: offiziell belegt (Auszug), 2024: offiziell belegt (Auszug), 2025: offiziell belegt (Auszug), 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** Depots mit KESt-Abzug durch den Broker → Einkünfte gelten als „inländisch“; einbehaltene KESt wird separat ausgewiesen (KZ 899) und nicht doppelt besteuert.
- **Bekannte Einschränkungen:** Ob der Broker tatsächlich österreichische KESt abführt, muss je Depot und Jahr bestätigt werden.
- **Quellen:** BMF Formular E 1kv 2024 (Version vom 02.10.2024) <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2024/E1kv.pdf>; BMF E 1kv 2025, Version 27.06.2025, Seiten 1–4; geprüft 16.10.2026 <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download>
- **Tests:** `test_tax_engine.py::test_domestic_kest_not_double_counted`
- **Letzte Prüfung:** 2026-10-16

### MELDEFONDS_AGE – Meldefonds: ausschüttungsgleiche Erträge laut OeKB-Meldung; Zufluss zum Meldezeitpunkt; AK-Korrektur

- **Rechtsgrundlage:** § 186 Abs 2 Z 1 und Abs 3 InvFG 2011
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: nur Sekundärquelle – vorläufig, 2025: nur Sekundärquelle – vorläufig, 2026: nur Sekundärquelle – vorläufig
- **Implementierte Logik:** AgE = AgE je Anteil × Bestand zum Meldedatum; anrechenbare Steuer je Anteil × Bestand; AK + Korrekturbetrag × Bestand.
- **Bekannte Einschränkungen:** Nur mit importierter/erfasster Meldung. Fehlende Meldung → manuelle Prüfung (ggf. Nichtmeldefonds).
- **Quellen:** § 186 InvFG 2011 (RIS) – Fassungen bis 31.12.2023 / 1.1.–19.7.2024 (BGBl I 111/2023) / ab 20.7.2024 (BGBl I 113/2024) <https://www.ris.bka.gv.at/eli/bgbl/i/2011/77/P186/NOR40254753>; broker-test.at – Ausschüttungsgleiche Erträge (KZ 936/937) <https://www.broker-test.at/steuern/ausschuettungsgleiche-ertraege/>
- **Tests:** `test_tax_engine.py::test_meldefonds_age`, `test_tax_engine.py::test_fund_income_not_double_counted`
- **Letzte Prüfung:** 2026-10-16

### NICHTMELDEFONDS_PAUSCHAL – Nichtmeldefonds: pauschale AgE = 90 % des Unterschieds erster/letzter Rücknahmepreis, mindestens 10 % des letzten Rücknahmepreises; Zufluss 31.12.

- **Rechtsgrundlage:** § 186 Abs 2 Z 3 InvFG 2011
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: offiziell belegt (Auszug), 2025: offiziell belegt (Auszug), 2026: offiziell belegt (Auszug)
- **Implementierte Logik:** je Anteil max(0,9 × (letzter − erster Rücknahmepreis), 0,1 × letzter Rücknahmepreis) × Bestand 31.12.; AK-Erhöhung.
- **Bekannte Einschränkungen:** Selbstnachweis, Sonderregel bei fehlendem Rücknahmepreis und unterjährige Veräußerung nicht implementiert.
- **Quellen:** § 186 InvFG 2011 (RIS) – Fassungen bis 31.12.2023 / 1.1.–19.7.2024 (BGBl I 111/2023) / ab 20.7.2024 (BGBl I 113/2024) <https://www.ris.bka.gv.at/eli/bgbl/i/2011/77/P186/NOR40254753>; Linde Kommentar zu § 186 InvFG (Pauschalermittlung Nichtmeldefonds 90 % / mind. 10 %) <https://linda.lindeverlag.at/Dokument/76540_3___1___1___2___/>; BMF-Findok 145784 – Schätzung ausschüttungsgleicher Erträge Nichtmeldefonds (10 % Rücknahmepreis) <https://findok.bmf.gv.at/findok/iwg/145/145784/145784.1.pdf>; RIS § 186 InvFG, BGBl I 113/2024, Abs 2 Z 3 und Abs 3; geprüft 16.10.2026 <https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40263477/NOR40263477.html>
- **Tests:** `test_tax_engine.py::test_nichtmeldefonds_pauschal_2023`, `test_tax_engine.py::test_nichtmeldefonds_current_rule_computed`
- **Letzte Prüfung:** 2026-10-16

### NICHTMELDEFONDS_DISTRIBUTIONS – Nichtmeldefonds: tatsächliche Ausschüttungen zusätzlich steuerpflichtig (kein Abzug von der Pauschale)

- **Rechtsgrundlage:** § 186 Abs 2 Z 3 InvFG 2011
- **Gültigkeit / Status je Steuerjahr:** 2022: nur Sekundärquelle – vorläufig, 2023: nur Sekundärquelle – vorläufig, 2024: offiziell belegt (Auszug), 2025: offiziell belegt (Auszug), 2026: offiziell belegt (Auszug)
- **Implementierte Logik:** Ausschüttungen eines Nichtmeldefonds = steuerpflichtige Fondsausschüttung.
- **Bekannte Einschränkungen:** –
- **Quellen:** Linde Kommentar zu § 186 InvFG (Pauschalermittlung Nichtmeldefonds 90 % / mind. 10 %) <https://linda.lindeverlag.at/Dokument/76540_3___1___1___2___/>; RIS § 186 InvFG, BGBl I 113/2024, Abs 2 Z 3 und Abs 3; geprüft 16.10.2026 <https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40263477/NOR40263477.html>
- **Tests:** `test_tax_engine.py::test_meldefonds_vs_nichtmeldefonds`
- **Letzte Prüfung:** 2026-10-16

### REIT_BDC – REITs/BDCs: keine automatische Ableitung aus Wertpapierart

- **Rechtsgrundlage:** Grundsatz: Einstufung nach Rechtsform/Beleg, nicht nach Bezeichnung
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Ertragsbestandteile werden nur nach bestätigter Klassifizierung je Buchung berücksichtigt, sonst ungeklärt.
- **Bekannte Einschränkungen:** Behandlung als ausländischer Immobilienfonds (ImmoInvFG) nicht implementiert.
- **Quellen:** keine
- **Tests:** `test_tax_engine.py::test_reit_without_classification_is_unclear`
- **Letzte Prüfung:** 2026-10-16

### FX_CONVERSION – Umrechnung Fremdwährung in EUR

- **Rechtsgrundlage:** nicht verifiziert
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: nicht verifiziert – keine Berechnung, 2026: nicht verifiziert – keine Berechnung
- **Implementierte Logik:** Vorrang: Kurs aus Beleg bzw. Benutzereingabe. Fehlt er, wird auf Wunsch der EZB-Referenzkurs des Buchungstags (sonst letzter Bankarbeitstag davor, max. 7 Tage) ergänzt und als Quelle vermerkt. Ohne Kurs kein EUR-Betrag. Positionen in Fremdwährung sind vorläufig.
- **Bekannte Einschränkungen:** Nicht geprüft, ob der EZB-Referenzkurs oder ein anderer Kurs (z. B. Devisenmittelkurs der Bank) steuerlich maßgeblich ist.
- **Quellen:** keine
- **Tests:** `test_tax_engine.py::test_missing_data_detected`, `test_fx.py::test_fill_missing_fx_and_compute`
- **Letzte Prüfung:** 2026-10-16

### SECURITIZED_DERIVATIVE – Verkauf öffentlich begebener verbriefter Derivate aus belegtem Long-Bestand

- **Rechtsgrundlage:** § 27 Abs 4, § 27a Abs 1, Abs 2 Z 2/7, Abs 3 Z 3 und Abs 4 EStG
- **Gültigkeit / Status je Steuerjahr:** 2022: nicht verifiziert – keine Berechnung, 2023: nicht verifiziert – keine Berechnung, 2024: nicht verifiziert – keine Berechnung, 2025: offiziell belegt (Auszug), 2026: offiziell belegt (Auszug)
- **Implementierte Logik:** Erlös minus belegte Anschaffungskosten; 27,5-%-Gruppe; eigene Derivate-Kennzahlen. Explizite geprüfte Klassifizierung erforderlich.
- **Bekannte Einschränkungen:** Nur Long-Kauf/Verkauf/Rückzahlung (als Verkauf erfassen); keine Shorts, Stillhalter, physischen Ausübungen, unverbrieften Derivate oder Privatplatzierungen. 2026-Kennzahlen bleiben unverifiziert.
- **Quellen:** RIS § 27a EStG ab 20.07.2024, Abs 1–4, geprüft 16.10.2026 <https://www.ris.bka.gv.at/eli/bgbl/1988/400/P27a/NOR40263362>; BMF E 1kv 2025, Version 27.06.2025, Seiten 1–4; geprüft 16.10.2026 <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download>
- **Tests:** `test_review_regressions.py::test_securitized_derivative_has_own_e1kv_fields`
- **Letzte Prüfung:** 2026-10-16

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
| E1KV_2025 | BMF E 1kv 2025, Version 27.06.2025, Seiten 1–4; geprüft 16.10.2026 | offiziell | <https://formulare.bmf.gv.at/service/formulare/inter-Steuern/pdfs/2025/E1kv.pdf?open=download> |
| BMF_XML_2025 | BMF XML-Struktur Jahreserklärungen 2025, Abschnitt EINKUENFTE_KAPITALVERMOEGEN | offiziell | <https://www.bmf.gv.at/dam/jcr%3Afd281668-2d12-4066-9942-c5685f6cc247/BMF_XML_Jahreserklaerungen_2025.xml> |
| INVFG_186_2024 | RIS § 186 InvFG, BGBl I 113/2024, Abs 2 Z 3 und Abs 3; geprüft 16.10.2026 | offiziell | <https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40263477/NOR40263477.html> |
| DBA_DE | DBA Deutschland Art 10 Abs 2 lit b (Privatpersonen), RIS | offiziell | <https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Anlage=&Artikel=10&FassungVom=2024-01-20&Gesetzesnummer=20002157&Paragraf=&Uebergangsrecht=> |
| DBA_CH | DBA Schweiz Art 10 Abs 2 und Art 23, RIS | offiziell | <https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004202> |
| DBA_NL | DBA Niederlande Art 10 Abs 2, RIS (Privatpersonen) | offiziell | <https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004091> |
| DBA_CA | DBA Kanada Art 10 Abs 2 lit b, synthetisierte Fassung mit MLI, RIS | offiziell | <https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40220703/III_93_2018_DBA_Kanada_synthesised_deutsch_final.pdf> |
| ESTG_27A_CURRENT | RIS § 27a EStG ab 20.07.2024, Abs 1–4, geprüft 16.10.2026 | offiziell | <https://www.ris.bka.gv.at/eli/bgbl/1988/400/P27a/NOR40263362> |

## DBA-Quellensteuersätze (Dividenden)

| Land | Satz | verifiziert | Hinweis |
|---|---|---|---|
| US | 15% | ja | DBA-USA: Begrenzung auf 15 % für natürliche Personen (BMF-Findok) |
| DE | 15% | ja | Art 10: 15 % Höchstsatz für gewöhnliche Dividenden natürlicher Personen, Nutzungsberechtigung und DBA-Ansässigkeit vorausgesetzt; keine Sondergesellschaften. |
| CH | 15% | ja | Art 10: 15 % Höchstsatz für gewöhnliche Dividenden natürlicher Personen, Nutzungsberechtigung und DBA-Ansässigkeit vorausgesetzt; keine Sondergesellschaften. |
| NL | 15% | ja | Art 10: 15 % Höchstsatz für gewöhnliche Dividenden natürlicher Personen, Nutzungsberechtigung und DBA-Ansässigkeit vorausgesetzt; keine Sondergesellschaften. |
| FR | – | nein | Widersprüchliche Sekundärquellen (12,8 % / 15 %) – DBA prüfen |
| IE | – | nein | Nicht geprüft |
| GB | – | nein | Nicht geprüft |
| CA | 15% | ja | Art 10: 15 % Höchstsatz für gewöhnliche Dividenden natürlicher Personen, Nutzungsberechtigung und DBA-Ansässigkeit vorausgesetzt; keine Sondergesellschaften. |

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
| foreign_tax_27_5_inland | 984 | Anrechenbare ausländische Steuer auf Einkünfte mit KESt-Abzug (27,5 %) | nicht verifiziert – keine Berechnung |
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
| foreign_tax_27_5_inland | 984 | Anrechenbare ausländische Steuer auf Einkünfte mit KESt-Abzug (27,5 %) | nicht verifiziert – keine Berechnung |
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
| foreign_tax_27_5_inland | 984 | Anrechenbare ausländische Steuer auf Einkünfte mit KESt-Abzug (27,5 %) | nicht verifiziert – keine Berechnung |
- Die Fußnote zu den Quellensteuer-Kennzahlen nennt KZ 940, 984, 998, 900 und 901; die exakte Zuordnung je Einkunftsart ist im Formular zu prüfen.
- Werbungskosten sind auch bei Regelbesteuerungsoption nicht abzugsfähig (Formularhinweis).
- Durch die Erfassung von Substanzverlusten in 891/892 bzw. 895/896 wird die Verlustausgleichsoption ausgeübt (Formularhinweis).
- Derivate (982/995, 895/896) und Kryptowährungen (171–174) werden vom Tool nicht berechnet.

### 2025 – E 1kv 2025 (Version 27.06.2025), Originalformular und XML geprüft 16.10.2026

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
| interest25_ausland | 861 | Zinsen aus Geldeinlagen bei Kreditinstituten (ausländisch, 25 %) | offiziell belegt (Auszug) |
| interest25_inland | 860 | Zinsen aus Geldeinlagen bei Kreditinstituten (inländisch, 25 %) | offiziell belegt (Auszug) |
| kest_inland | 899 | Einbehaltene KESt auf inländische Kapitaleinkünfte | offiziell belegt (Auszug) |
| foreign_tax_27_5 | 998 | Anrechenbare ausländische Steuer auf Einkünfte ohne KESt-Abzug (27,5 %) | offiziell belegt (Auszug) |
| foreign_tax_27_5_inland | 984 | Anrechenbare ausländische Steuer auf Einkünfte mit KESt-Abzug (27,5 %) | offiziell belegt (Auszug) |
| foreign_tax_25_inland | 900 | Anrechenbare ausländische Steuer auf Einkünfte mit KESt-Abzug (25 %) | offiziell belegt (Auszug) |
| foreign_tax_25_ausland | 901 | Anrechenbare ausländische Steuer auf Einkünfte ohne KESt-Abzug (25 %) | offiziell belegt (Auszug) |
| derivative_gains_inland | 982 | Verbriefte Derivate Überschüsse (inland, 27,5 %) | offiziell belegt (Auszug) |
| derivative_losses_inland | 895 | Verbriefte Derivate Verluste (inland, 27,5 %) | offiziell belegt (Auszug) |
| derivative_gains_ausland | 995 | Verbriefte Derivate Überschüsse (ausland, 27,5 %) | offiziell belegt (Auszug) |
| derivative_losses_ausland | 896 | Verbriefte Derivate Verluste (ausland, 27,5 %) | offiziell belegt (Auszug) |
- Kennzahlen und Spaltenzuordnung anhand des BMF-Originalformulars geprüft.
- Verifizierte Kennzahlen bestätigen nicht automatisch die Vollständigkeit der Berechnungsdaten.
- KZ 189 (inländische Dividenden innerhalb von Fonds) benötigt zusätzliche OeKB-Daten und ist manuell abzugleichen.

### 2026 – E 1kv 2026 – NICHT verifiziert

- Stand 16.10.2026 kein abrufbares amtliches Formular für 2026. Kennzahlen 2025 sind ausschließlich Planungshinweise, keine bestätigten Kennzahlen 2026.
