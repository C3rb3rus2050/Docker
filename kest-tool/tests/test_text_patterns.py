import pytest

from kest_helpers import ctx, repo  # noqa: F401
from kest_tool.importers.pdf_importer import parse_text
from kest_tool.importers.text_patterns import normalize_document_text


@pytest.mark.parametrize('body,family', [
    ('Anfangssaldo 100,00 EUR\nEndsaldo 120,00 EUR', 'Kontoauszug'),
    ('Opening balance 100.00 EUR\nClosing balance 120.00 EUR', 'Kontoauszug'),
    ('Bescheinigung nach § 45a\nHöhe der Kapitalerträge 123 EUR', 'Jahressteuerbescheinigung'),
    ('Depotbestand zum 31.12.2024\nISIN Bezeichnung Kurswert', 'Depotauszug'),
    ('Voraussichtliche Kosten 2 EUR\nProduktkosten 1 EUR', 'Kosteninformation'),
    ('Berechtigtes Wertpapier Example\nEx-Tag Zahltag Art Betrag', 'Dividendenabrechnung'),
    ('Entitled security Example\nEx-date Payment date Amount', 'Dividendenabrechnung'),
    ('Zinszeitraum 01.01.2024 - 31.01.2024\nBruttozinsen 2,00 EUR', 'Zinsabrechnung'),
    ('Wir haben für Sie Aktien gekauft\nKurswert 100,00 EUR', 'Kaufabrechnung'),
    ('We have sold securities for you\nMarket Value 100.00 EUR', 'Verkaufsabrechnung'),
])
def test_missing_title_is_inferred_from_independent_body_signals(body, family):
    ex = parse_text('Trade Republic\n' + body)
    assert ex.doc_type == family
    assert ex.classification['method'] == 'Textbausteine'
    assert len(ex.classification['evidence']) >= 2
    assert not ex.complete
    assert any(c['name'] == 'Textmuster-Zuordnung' and c['result'] == 'warn' for c in ex.checks)


def test_single_incidental_word_is_not_a_fingerprint():
    ex = parse_text('Trade Republic\nProduktkosten können anfallen.\nAnfangssaldo 100 EUR')
    assert ex.doc_type == 'Unbekannt'
    assert ex.classification['method'] == 'Schlüsselwörter'


def test_conflicting_body_signals_stay_a_review_only_bundle():
    ex = parse_text('Trade Republic\nOpening balance 100\nClosing balance 200\n'
                    'Estimated costs 3\nProduct costs 1')
    assert ex.doc_type == 'Sammelabrechnung'
    assert not ex.creates_transaction and not ex.complete


def test_explicit_trade_heading_beats_incidental_account_text():
    ex = parse_text('Scalable Capital\nWertpapierabrechnung: Kauf\n'
                    'Anfangssaldo 100\nEndsaldo 50\nISIN US0378331005\n'
                    'Ausführungstag 02.02.2024\nStückzahl 1\nKurswert 50 EUR')
    assert ex.doc_type == 'Kaufabrechnung'
    assert ex.tx_type == 'Kauf'
    assert ex.classification['method'] == 'Überschrift/Abrechnung'


@pytest.mark.parametrize('heading,family', [
    ('K O N T O A U S Z U G', 'Kontoauszug'),
    ('Jahressteuer-\nbescheinigung', 'Jahressteuerbescheinigung'),
    ('Kosten\u00adinformation', 'Kosteninformation'),
    ('Advance Lump Sum', 'Vorabpauschale (DE)'),
    ('Abrechnung über den Kauf von Kryptowerten', 'Kryptoabrechnung'),
    ('Ertragsthesaurierung', 'Ertragsabrechnung'),
    ('Wahldividende', 'Ertragsabrechnung'),
    ('AUSSCHÜTTUNG / AUSSCHÜTTUNGSGLEICHER ERTRAG', 'Ertragsabrechnung'),
    ('Jahresdepotauszug', 'Depotauszug'),
    ('Vergütung des Vermögensverwalters', 'Gebührenabrechnung'),
])
def test_additional_titles_and_pdf_text_artifacts(heading, family):
    ex = parse_text('Trade Republic\n' + heading)
    assert ex.doc_type == family
    assert not ex.creates_transaction


def test_normalization_keeps_financial_numbers_and_original_quantities():
    assert normalize_document_text('0.125 pc. 1 234,56 EUR\nUS0378331005') == '0.125 pc. 1 234,56 EUR\nUS0378331005'


def test_fund_distribution_title_is_not_lost_inside_a_compound_word():
    ex = parse_text('Baader Bank\nFondsausschüttung\nISIN US0378331005\n'
                    'Zahltag 02.02.2024\nBruttobetrag 12,00 EUR')
    assert ex.doc_type == 'Ausschüttungsabrechnung' and ex.tx_type == 'Ausschüttung'


def test_inferred_information_document_is_not_marked_completed(repo):
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    from kest_tool.processing import process_documents, store_uploads
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for y, line in enumerate(['Trade Republic', 'Opening balance 100 EUR', 'Closing balance 120 EUR']):
        canvas.drawString(50, 800 - 20 * y, line)
    canvas.save()
    store_uploads(repo, [('unknown.pdf', buffer.getvalue())], 2024)
    doc = repo.documents()[0]
    processed = process_documents(repo, [doc['id']])
    assert processed[0].status == 'pruefen'
    assert repo.document(doc['id'])['status'] == 'pruefen'
    assert repo.document(doc['id'])['doc_type'] == 'Kontoauszug'
