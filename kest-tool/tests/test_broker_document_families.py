"""Own examples of structures observed in public broker fixtures; offline regression tests."""
from datetime import date

import pytest

from kest_helpers import ctx, repo  # noqa: F401
from kest_tool import demo
from kest_tool.importers.pdf_importer import parse_text, extract_text
from kest_tool.processing import process_documents, store_uploads


@pytest.mark.parametrize('title,expected', [
    ('KONTOÜBERSICHT', 'Kontoauszug'), ('KONTOAUSZUG', 'Kontoauszug'),
    ('ACCOUNT STATEMENT SUMMARY', 'Kontoauszug'), ('Cash Account Statement', 'Kontoauszug'),
    ('Depotauszug', 'Depotauszug'), ('EX-ANTE KOSTENINFORMATION ZUM WERTPAPIERKAUF', 'Kosteninformation'),
    ('EX-POST KOSTENINFORMATION', 'Kosteninformation'), ('STEUERLICHE OPTIMIERUNG', 'Steuerkorrektur'),
    ('Steuerneuberechnung', 'Steuerkorrektur'), ('Reklassifizierung einer Ausschüttung', 'Steuerkorrektur'),
    ('Depotübertrag eingehend', 'Depotübertrag'), ('AKTIENSPLIT', 'Kapitalmaßnahme'),
    ('Laufzeitende', 'Kapitalmaßnahme'), ('Knock Out', 'Kapitalmaßnahme'),
    ('Reinvestierung', 'Kapitalmaßnahme'), ('Gesamtrückzahlung', 'Kapitalmaßnahme'),
    ('ABRECHNUNG CRYPTOGESCHÄFT', 'Kryptoabrechnung'), ('ABRECHNUNG CRYPTO SAVEBACK', 'Kryptoabrechnung'),
    ('ABRECHNUNG EINZAHLUNG', 'Zahlungsbeleg'), ('ÜBERWEISUNGSDETAILS', 'Zahlungsbeleg'),
    ('Jahressteuerbescheinigung', 'Jahressteuerbescheinigung'), ('Verlustbescheinigung', 'Jahressteuerbescheinigung'),
    ('Steuerreport für Österreich', 'Jahressteuerbescheinigung'), ('Vorabpauschale 2024', 'Vorabpauschale (DE)'),
    ('Note de contrat', 'Fremdsprachige Abrechnung'), ('REGOLAMENTO TITOLI', 'Fremdsprachige Abrechnung'),
])
def test_special_document_families_do_not_create_spurious_transactions(title, expected):
    ex = parse_text(f'Trade Republic\n{title}\nDatum 05.02.2024\nISIN US0378331005\n'
                    'Kauf Apple 2 Stk. 50,00 EUR 100,00 EUR\nKurswert 100,00 EUR')
    assert ex.doc_type == expected
    assert not ex.creates_transaction and not ex.complete


def test_scalable_trade_type_has_priority_over_security_name():
    for security in ('Quality Dividend Growth', 'Income Dividend Aristocrats'):
        ex = parse_text(f'''Scalable Capital Bank GmbH
Datum 06.02.2024
Wertpapierabrechnung
für Sparplanausführung
Ausführung 02.02.2024 11:42:00
Typ Wertpapier Anzahl Kurs Betrag
Kauf {security} 2,00 Stk. 50,00 EUR 100,00 EUR
US0378331005
Belastung 100,00 EUR
Valuta: 06.02.2024''')
        assert ex.tx_type == 'Kauf' and ex.complete, ex.warnings
        assert ex.value('amount') == 100 and ex.value('quantity') == 2


def test_english_position_decimal_and_security_name():
    ex = parse_text('''Scalable Capital Bank GmbH
Contract note
Execution 02.02.2024
Type Security Quantity Price Amount
Buy Dividend Growth 0.125 pc. 80.000 EUR 10.00 EUR
US0378331005
Debit 10.00 EUR''')
    assert ex.tx_type == 'Kauf' and ex.complete, ex.warnings
    assert ex.value('quantity') == .125 and ex.value('price') == 80


def test_english_baader_units_are_decimal_not_thousands():
    ex = parse_text('''Scalable Capital GmbH
Transaction Statement: Purchase
Units 2.734 Apple EUR 10.125
ISIN US0378331005
Market Value EUR 27.68
Trade Date Trade Time
2024-02-02 11:10:00
Amount debited to account 123 Value: 2024-02-06 EUR 27.68''')
    assert ex.complete, ex.warnings
    assert ex.value('quantity') == 2.734 and ex.value('price') == 10.125
    assert ex.value('trade_date') == date(2024, 2, 2)


@pytest.mark.parametrize('title', ['WERTPAPIERABRECHNUNG ROUND UP', 'WERTPAPIERABRECHNUNG SAVEBACK',
                                  'SECURITIES SETTLEMENT SAVEBACK'])
def test_roundup_and_saveback_are_purchases(title):
    ex = parse_text(f'Trade Republic\n{title}\nDatum 02.02.2024\nApple 2 Stk. 50,00 EUR 100,00 EUR\n'
                    'US0378331005\nGesamt 100,00 EUR')
    assert ex.tx_type == 'Kauf' and ex.complete, ex.warnings


def test_new_trade_settlement_fee_and_ipo_execution():
    ex = parse_text('''Trade Republic
WERTPAPIERABRECHNUNG
Ausführung der Zeichnungsorder am 02.02.2024 um 11:10 Uhr
Apple 2 Stk. 50,00 EUR 100,00 EUR
US0378331005
Abwicklungskostenpauschale -1,00 EUR
VERRECHNUNGSKONTO WERTSTELLUNG BETRAG
DE12345678901234567890 06.02.2024 -101,00 EUR''')
    assert ex.tx_type == 'Kauf' and ex.value('fees') == 1
    assert ex.complete, ex.warnings


@pytest.mark.parametrize('english', [False, True])
def test_cash_interest_periods_sum_and_use_actual_booking_date(english):
    title = 'INTEREST INVOICE' if english else 'ABRECHNUNG ZINSEN'
    income = 'Interest' if english else 'Zinsen'
    ex = parse_text(f'''Trade Republic
DATUM 05.02.2024
{title}
Cash {income} 4,00% 01.01.2024 - 15.01.2024 1,25 EUR
Cash {income} 3,75% 16.01.2024 - 31.01.2024 2,50 EUR
IBAN BOOKING DATE TOTAL
DE12345678901234567890 01.02.2024 3,75 EUR''')
    assert ex.complete, ex.warnings
    assert ex.value('amount') == 3.75 and ex.value('trade_date') == date(2024, 2, 1)
    assert len(ex.components) == 2


def test_mixed_cash_and_money_market_income_is_not_booked_as_one_dividend():
    ex = parse_text('''Trade Republic
ABRECHNUNG ZINSEN
ÜBERSICHT
Cash Zinsen 3,75% 10,00 EUR
Geldmarkt Dividende 3,75% 2,00 EUR
Gesamt 12,00 EUR
Datum 01.02.2024''')
    assert ex.doc_type == 'Sammelabrechnung' and not ex.creates_transaction
    assert [c['Brutto'] for c in ex.components] == [10, 2]


def test_scalable_period_end_does_not_become_confirmed_payment_date():
    ex = parse_text('''Scalable Capital
Datum 04.04.2024
Rechnungsabschluss
Zeitraum 01.01.2024 - 31.03.2024
Habenzinsen 12,50 EUR
Gesamt 12,50 EUR''')
    assert ex.value('amount') == 12.5
    assert not ex.complete and ex.fields['trade_date'].confidence < .8


def test_dividend_tax_appendix_is_not_a_depot_transfer():
    ex = parse_text('''Scalable Capital
Dividende
ISIN US0378331005
Zahltag 01.02.2024
Bruttobetrag EUR 10,00
Ausbuchung
Stück 2 Apple
Einbuchung
Stück 2 Apple''')
    assert ex.creates_transaction and ex.doc_type != 'Depotübertrag'


def test_sale_appendix_mentions_vorabpauschale_but_is_not_vorab_document():
    ex = parse_text('''Scalable Capital
Wertpapierabrechnung: Verkauf
ISIN IE00B4L5Y983
STK 2 World Fund
Handelstag 02.02.2024
Kurswert EUR 100,00
Vorabpauschale bereits bezahlt 2,00 EUR''')
    assert ex.doc_type == 'Verkaufsabrechnung' and ex.creates_transaction


def test_statement_stays_a_beleg_even_if_it_contains_multiple_buys(repo):
    payload = demo._pdf(['Trade Republic', 'KONTOÜBERSICHT', 'Datum 01.02.2024',
                         'Kauf Apple 2 Stk. 50 EUR 100 EUR', 'ISIN US0378331005'])
    uploaded = store_uploads(repo, [('konto.pdf', payload)], 2024)
    result = process_documents(repo, uploaded.pdf_ids)[0]
    assert result.status == 'beleg' and not repo.transactions()
    assert repo.document(result.document_id)['doc_type'] == 'Kontoauszug'


def test_large_recognizable_statement_can_be_read_without_truncation():
    import pymupdf
    doc = pymupdf.open()
    for index in range(31):
        doc.new_page().insert_text((40, 40), 'Trade Republic\nKONTOAUSZUG' if index == 0 else f'Page {index+1}')
    text, _ = extract_text(doc.tobytes(), 'pymupdf')
    assert 'Page 31' in text


def test_reextract_flags_old_wrong_type_without_overwriting_amount(repo):
    from kest_tool.models import TransactionIn, TxType
    depot = repo.add_depot(repo.add_broker('Scalable Capital', 'ScalableCapital'), 'Depot')
    payload = demo._pdf(['Scalable Capital', 'Wertpapierabrechnung', 'für Sparplanausführung',
        'Ausführung 02.02.2024', 'Typ Wertpapier Anzahl Kurs Betrag',
        'Kauf Dividend Growth 2 Stk. 50,00 EUR 100,00 EUR', 'US0378331005', 'Belastung 100,00 EUR'])
    doc, _ = repo.add_document(payload, 'sparplan.pdf', tax_year=2024, status='verarbeitet')
    tid = repo.add_transaction(TransactionIn(depot_id=depot, tx_type=TxType.DIVIDEND,
        trade_date=date(2024, 2, 2), isin='US0378331005', amount=100, quantity=2,
        source_type='pdf', document_id=doc['id']))
    result = process_documents(repo, [doc['id']], reextract=True)[0]
    assert result.status == 'pruefen' and 'Buchungsart' in result.message
    assert repo.transaction(tid)['tx_type'] == 'Dividende'
    assert repo.transaction(tid)['amount'] == 100 and repo.transaction(tid)['review_status'] == 'pruefen'
    assert len(repo.transactions()) == 1


def test_refresh_of_supplemental_statement_does_not_flag_linked_trades(repo):
    from kest_tool.models import TransactionIn, TxType
    depot = repo.add_depot(repo.add_broker('Trade Republic', 'TradeRepublic'), 'Depot')
    doc, _ = repo.add_document(demo._pdf(['Trade Republic', 'Kontoauszug']), 'konto.pdf', status='verarbeitet')
    tid = repo.add_transaction(TransactionIn(depot_id=depot, tx_type=TxType.BUY,
        trade_date=date(2024, 2, 2), isin='US0378331005', amount=100, quantity=2, source_type='pdf'))
    repo.link_document(doc['id'], tid)
    result = process_documents(repo, [doc['id']], reextract=True)[0]
    assert result.status == 'uebersprungen'
    assert repo.transaction(tid)['review_status'] == 'ungeprueft'


def test_overview_execution_negative_cash_booking_and_distinct_value_date():
    # Synthetic reproduction of the supplied layout; no account details or
    # original user transaction values are included in the published fixture.
    ex = parse_text('''Trade Republic
WERTPAPIERABRECHNUNG
ÜBERSICHT
Limit-Order Kauf am 13.02.2024, um 14:37 Uhr (Europe/Berlin) an der Lang & Schwarz Exchange.
Der Kontrahent der Transaktion ist Lang & Schwarz TradeCenter AG & Co. KG.
POSITION ANZAHL KURS BETRAG
Muster Aktie 3 Stk. 42,50 EUR 127,50 EUR
Registered Shares o.N.
ISIN: US0378331005
GESAMT 127,50 EUR
ABRECHNUNG
POSITION BETRAG
Fremdkostenzuschlag -1,00 EUR
GESAMT -128,50 EUR
BUCHUNG
VERRECHNUNGSKONTO VALUTA BETRAG
DE00000000000000000000 15.02.2024 -128,50 EUR
Diese Abrechnung wird maschinell erstellt und daher nicht unterschrieben.
Sofern keine Umsatzsteuer ausgewiesen ist, handelt es sich um eine umsatzsteuerfreie Leistung.''')
    assert ex.complete, ex.warnings
    assert ex.doc_type == 'Kaufabrechnung'
    assert ex.value('trade_date') == date(2024, 2, 13)
    assert ex.value('value_date') == date(2024, 2, 15)
    assert ex.value('quantity') == 3
    assert ex.value('price') == 42.5 and ex.value('amount') == 127.5
    assert ex.value('fees') == 1.0
