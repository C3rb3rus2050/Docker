"""Own synthetic layouts based on public OeKB output; no third-party PDFs bundled."""
from datetime import date

import pytest

from kest_helpers import ctx, repo  # noqa: F401
from kest_tool import demo
from kest_tool.importers.oekb_layouts import extract_published_reports, parse_published_report
from kest_tool.processing import process_documents, process_tables, store_uploads

REPORT = '''OeKB Kapitalmarkt Services
ISIN IE00B4L5Y983
Name der Anteilsgattung des Fonds Musterfonds
Art gem FMV 2015 InvF
Meldedatum 21.11.2025
Jahresmeldung JA
Ausschüttungsmeldung NEIN
Geschäftsjahres-Ende 31.08.2025
Währung, in der die Meldung vorgenommen wurde EUR
Kennzahlen ESt-Erklärung Privatanleger
Privatanleger mit Option Privatanleger ohne Option
Ausschüttungen 27,5% (Kennzahlen 897 oder 898) 1,0000 2,0000
Ausschüttungsgleiche Erträge 27,5% (Kennzahlen 936 oder 937) 3,0000 4,0000
Anzurechnende ausländische (Quellen)Steuer 0,1000 0,2000
Die Anschaffungskosten des Fondsanteils sind zu korrigieren um -0,3000 -0,4000
'''


def test_private_without_option_and_negative_costs_never_codes_or_percentage():
    result = parse_published_report(REPORT)
    assert not result['missing'] and not result['warnings']
    assert result['values']['age_per_unit'] == 4
    assert result['values']['taxable_distribution_per_unit'] == 2
    assert result['values']['creditable_tax_per_unit'] == .2
    assert result['values']['ak_correction_per_unit'] == -.4
    assert 'distribution_per_unit' not in result['values']


def test_subrow_16_2_1_does_not_overwrite_age():
    text = REPORT.replace('Ausschüttungsgleiche Erträge 27,5% (Kennzahlen 936 oder 937)', '16.2 Ausschüttungsgleiche')
    result = parse_published_report(text + '16.2.1 Vorsicht: Vom Fonds 0,0000 0,0000\n')
    assert result['values']['age_per_unit'] == 4
    assert not result['warnings']
    assert parse_published_report(text + '16.2.1 Vorsicht: Vom Fonds 1,0000 1,0000\n')['warnings']


def test_unidentified_columns_or_missing_tax_values_stay_open():
    assert parse_published_report(REPORT.replace('Privatanleger ohne Option', 'Unbekannte Spalte'))['warnings']
    result = parse_published_report(REPORT.replace('Anzurechnende ausländische (Quellen)Steuer 0,1000 0,2000', ''))
    assert any('creditable_tax_per_unit' in m for m in result['missing'])


def test_multiple_reports_in_one_pdf_are_linked_and_idempotent(repo):
    # Separate metadata pages, as in actual OeKB bundles.
    import pymupdf
    source = pymupdf.open(stream=demo._pdf(REPORT.splitlines()), filetype='pdf')
    second = pymupdf.open(stream=demo._pdf(REPORT.replace('IE00B4L5Y983', 'IE00B3RBWM25').splitlines()), filetype='pdf')
    source.insert_pdf(second)
    data = source.tobytes()
    assert len(extract_published_reports(data)) == 2
    upload = store_uploads(repo, [('fonds.pdf', data)], 2026)
    results = process_documents(repo, upload.pdf_ids)
    assert results[0].status == 'angelegt', results[0].message
    assert len(repo.fund_reports()) == 2 and not repo.transactions(2025)
    assert all(r['document_id'] == upload.pdf_ids[0] for r in repo.fund_reports())
    assert repo.document(upload.pdf_ids[0])['tax_year'] == 2025
    process_documents(repo, upload.pdf_ids)
    assert len(repo.fund_reports()) == 2


def test_aif_values_are_extracted_but_not_automatically_applied(repo):
    payload = demo._pdf(REPORT.replace('InvF', 'AIF').splitlines())
    upload = store_uploads(repo, [('fonds.pdf', payload)], 2025)
    result = process_documents(repo, upload.pdf_ids)[0]
    assert result.status == 'pruefen' and 'AIF' in result.message
    assert not repo.fund_reports()
    assert 'fund_reports' in repo.document(upload.pdf_ids[0])['extraction_json']


def test_vertical_published_csv_no_mapping_needed(repo):
    text = '''ISIN;IE00B4L5Y983
Meldedatum;21.11.2025
Währung;EUR
Jahresmeldung;JA
Bezeichnung;Privatanleger mit Option;Privatanleger ohne Option
Ausschüttungen 27,5% (Kennzahlen 897 oder 898);1,0000;2,0000
Ausschüttungsgleiche Erträge 27,5% (Kennzahlen 936 oder 937);3,0000;4,0000
Anzurechnende ausländische (Quellen)Steuer;0,1000;0,2000
Die Anschaffungskosten des Fondsanteils sind zu korrigieren um;-0,3000;-0,4000
'''
    upload = store_uploads(repo, [('oekb.csv', text.encode())], 2026)
    result = process_tables(repo, upload.csv_docs)[0]
    assert result.status == 'angelegt', result.message
    assert repo.fund_reports()[0]['age_per_unit'] == 4
    assert repo.fund_reports()[0]['ak_correction_per_unit'] == -.4


def test_fund_table_currency_is_never_assumed(repo):
    upload = store_uploads(repo, [('fonds.csv', b'ISIN;Meldedatum;AGE\nIE00B4L5Y983;21.11.2025;4,0000')], 2025)
    result = process_tables(repo, upload.csv_docs)[0]
    assert result.status == 'pruefen' and 'Währung' in result.message


def test_foreign_currency_fund_table_uses_historical_fx(repo):
    from kest_tool.fx import FxRates
    class Service:
        url = 'https://www.ecb.europa.eu/'
        def rates(self, **options):
            return FxRates({'USD': {date(2025, 11, 21): 1.1}})
    text = 'ISIN;Meldedatum;AGE;Währung\nIE00B4L5Y983;21.11.2025;4,0000;USD'
    upload = store_uploads(repo, [('fonds.csv', text.encode())], 2025)
    result = process_tables(repo, upload.csv_docs, fx_service=Service())[0]
    assert result.status == 'angelegt', result.message
    report = repo.fund_reports()[0]
    assert report['fx_rate'] == pytest.approx(1.1) and 'EZB' in report['notes']


def test_long_recognizable_oekb_pdf_is_not_truncated():
    import pymupdf
    from kest_tool.importers.pdf_importer import extract_text
    doc = pymupdf.open()
    for index in range(31):
        page = doc.new_page()
        page.insert_text((40, 40), 'OeKB Kennzahlen ESt Privatanleger' if index == 0 else f'Seite {index + 1}')
    text, _ = extract_text(doc.tobytes(), 'pymupdf')
    assert 'Seite 31' in text
