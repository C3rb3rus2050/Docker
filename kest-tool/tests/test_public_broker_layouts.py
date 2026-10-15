"""Synthetic regressions based on public broker layout variants.

Structural references (not copied customer documents): Portfolio Performance,
commit f84ff1a432ec9ba61c17aa2ae4191c8b068643a7; source links are documented in
kest-tool/docs/DOKUMENTENVERARBEITUNG.md.
"""
from datetime import date

import pytest

from kest_tool.importers.pdf_importer import parse_text


def test_english_trade_does_not_become_dividend_from_security_name():
    ex = parse_text("""Trade Republic
SECURITIES SETTLEMENT
Market-Order Buy on 12.08.2022 at 11:30 on Exchange.
POSITION QUANTITY PRICE AMOUNT
Example Dividend Leaders 2.500000 Pcs. 40.00 EUR 100.00 EUR
ISIN: US0378331005
TOTAL 100.00 EUR
BILLING
External cost surcharge -1.00 EUR
TOTAL -101.00 EUR
BOOKING
CLEARING ACCOUNT VALUE DATE AMOUNT
DE00000000000000000000 16.08.2022 -101.00 EUR
""")
    assert ex.tx_type == "Kauf"
    assert ex.value("quantity") == pytest.approx(2.5)
    assert ex.value("amount") == 100
    assert ex.value("total") == 101
    assert ex.value("fees") == 1
    assert ex.value("trade_date") == date(2022, 8, 12)
    assert ex.value("value_date") == date(2022, 8, 16)
    assert ex.complete, ex.warnings


def test_english_savings_plan_pcs_and_execution_date():
    ex = parse_text("""Trade Republic
SECURITIES SETTLEMENT SAVINGS PLAN
Savings plan execution on 16.05.2023 on Exchange.
POSITION QUANTITY AVERAGE RATE AMOUNT
Example Inc. 0.125 Pcs. 400.00 EUR 50.00 EUR
ISIN: US0378331005
TOTAL 50.00 EUR
""")
    assert ex.value("quantity") == .125
    assert ex.value("trade_date") == date(2023, 5, 16)
    assert ex.value("amount") == 50
    assert ex.complete, ex.warnings


def test_split_position_and_plural_stuecke():
    ex = parse_text("""Trade Republic
DIVIDENDE
Datum 04.06.2024
POSITION ANZAHL ERTRAG BETRAG
Example Inc. 1.75 USD
7.000000 Stücke 0.2500 USD
US0378331005
GESAMT 1.75 USD
Quellenstaat US
Quellensteuer -0.26 USD
BUCHUNG
VERRECHNUNGSKONTO DATUM DER ZAHLUNG BETRAG
DE00000000000000000000 05.06.2024 1.49 USD
""")
    assert ex.value("quantity") == 7
    assert ex.value("price") == .25
    assert ex.value("amount") == 1.75
    assert ex.value("currency") == "USD"
    assert ex.value("trade_date") == date(2024, 6, 5)
    assert ex.complete, ex.warnings


def test_unit_price_with_three_decimal_places_is_not_thousands():
    ex = parse_text("""Trade Republic
Market-Order Kauf am 13.05.2022 um 12:14 Uhr.
POSITION ANZAHL KURS BETRAG
Example Inc. 1 Stk. 24.045 EUR 24.05 EUR
US0378331005
GESAMT 24.05 EUR
""")
    assert ex.value("price") == 24.045
    assert ex.value("amount") == 24.05
    assert ex.complete, ex.warnings


SCALABLE_DIV = """Scalable Capital Bank GmbH
Datum 14.06.2024
Dividende
Berechtigtes Wertpapier Example Inc.
ISIN US0378331005
Berechtigte Anzahl 12
Kontobewegung
Buchung Wertstellung Typ Betrag / Stk. Berechtigte Anzahl Gesamt
Wechselkurs
14.06.2024 17.06.2024 Gutschrift 0,25 USD 12 2,50 EUR
USD / EUR 1,2000
Quellenstaat US
Ausländische Quellensteuer -0,38 EUR
Gesamtbetrag 2,12 EUR
Gewinn oder Verlust 2,50 EUR
"""


def test_scalable_income_table_uses_document_eur_gross_not_net():
    ex = parse_text(SCALABLE_DIV)
    assert ex.value("amount") == 2.5
    assert ex.value("currency") == "EUR"
    assert ex.value("income_per_unit") == .25
    assert ex.value("income_per_unit_currency") == "USD"
    assert ex.value("total") == 2.12
    assert ex.value("withholding_tax") == .38
    assert ex.value("quantity") == 12
    assert ex.value("security_name") == "Example Inc."
    assert ex.value("trade_date") == date(2024, 6, 14)
    assert ex.value("value_date") == date(2024, 6, 17)
    assert ex.value("fx_rate") is None  # amounts already provided in EUR; never convert twice
    assert "1,2000" in ex.value("document_fx_quote")
    assert ex.complete, ex.warnings


def test_english_scalable_income_and_german_tax_are_separate():
    ex = parse_text("""Scalable Capital Bank GmbH
Date 27.04.2024
Dividend
Entitled security Example Inc.
ISIN US0378331005
Entitled quantity 17
Clearing account movement
Booking Value date Type Amount / pcs. Entitled quantity Total amount
27.04.2024 29.04.2024 Credit 0.57 EUR 17 9.69 EUR
Taxes -2.55 EUR
Total 7.14 EUR
Capital gains tax 2.42 EUR
Solidarity surcharge 0.13 EUR
""")
    assert ex.value("amount") == 9.69
    assert ex.value("quantity") == 17
    assert ex.value("value_date") == date(2024, 4, 29)
    assert ex.value("kest_at_eur") is None
    assert not ex.complete
    assert any(c["name"] == "Deutsche Steuer" for c in ex.checks)


def test_baader_trade_date_from_execution_table_beats_valuta():
    ex = parse_text("""Scalable Capital Baader Bank
Wertpapierabrechnung: Kauf
Nominale ISIN: US0378331005 Kurs
STK 2 Example Inc. EUR 100,125
Kurswert EUR 200,25
Zu Lasten Konto 123 Valuta: 15.08.2022 EUR 200,25
Details zur Ausführung:
Handelsdatum Handelsuhrzeit
11.08.2022 15:00:00
""")
    assert ex.value("trade_date") == date(2022, 8, 11)
    assert ex.value("amount") == 200.25
    assert ex.value("quantity") == 2
    assert ex.complete, ex.warnings
