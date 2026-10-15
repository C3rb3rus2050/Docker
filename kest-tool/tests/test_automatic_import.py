import io
from datetime import date

import pandas as pd
import pytest

from kest_helpers import ctx, repo, depot  # noqa: F401
from kest_tool.importers.automatic import automatic_tables
from kest_tool.importers.csv_importer import ImportError_
from kest_tool.processing import store_uploads, process_tables

HEADER = 'Datum;Typ;ISIN;Stück;Bruttobetrag;Währung\n'
ROW = '01.02.2024;Kauf;US0378331005;2;300,00;EUR\n'


def run(repo, text, filename='TradeRepublic.csv'):
    uploaded = store_uploads(repo, [(filename, text.encode())], 2026)
    return process_tables(repo, uploaded.csv_docs)


def test_preamble_repeated_sections_and_broker_without_selection(repo):
    text = 'Trade Republic\nExport erstellt;15.10.2026\n' + HEADER + ROW + '\n' + HEADER + ROW
    result = run(repo, text)[0]
    assert result.status == 'angelegt'
    assert '1 übernommen, 1 Dubletten' in result.message
    assert len(repo.transactions(2024)) == 1
    doc = repo.document(result.document_id)
    assert doc['tax_year'] == 2024 and doc['source'] == 'TradeRepublic'
    assert run(repo, text) == []  # original and bookings idempotent


def test_partial_import_can_retry_without_duplicating_bookings(repo):
    text = HEADER + ROW + 'unbekannt;Kauf;US0378331005;2;300,00;EUR\n'
    first = run(repo, text)[0]
    assert first.status == 'pruefen' and '1 übernommen' in first.message
    again = run(repo, text)[0]
    assert '0 übernommen, 1 Dubletten, 1 zur Prüfung' in again.message
    assert len(repo.transactions(2024)) == 1


def test_malformed_section_never_silently_skips_rows(repo):
    result = run(repo, HEADER + ROW + 'falsche;Spaltenzahl\n')[0]
    assert result.status == 'pruefen' and 'Spaltenzahl' in result.message
    assert not repo.transactions(2024)


def test_generic_amount_is_not_assumed_gross(repo):
    result = run(repo, (HEADER + ROW).replace('Bruttobetrag', 'Betrag'))[0]
    assert result.status == 'pruefen' and 'Brutto' in result.message
    assert not repo.transactions(2024)


def test_ambiguous_depots_do_not_receive_guessed_transactions(repo):
    broker = repo.add_broker('Trade Republic', 'TradeRepublic')
    repo.add_depot(broker, 'Depot eins')
    repo.add_depot(broker, 'Depot zwei')
    result = run(repo, HEADER + ROW)[0]
    assert result.status == 'pruefen' and 'Depot' in result.message
    assert not repo.transactions(2024)


def test_german_tax_never_silently_treated_as_austrian(repo):
    text = HEADER.strip() + ';Kapitalertragsteuer\n' + ROW.strip() + ';15,00\n'
    result = run(repo, text)[0]
    assert result.status == 'pruefen' and 'österreichische' in result.message
    assert not repo.transactions(2024)


def test_oekb_table_automatically_routes_without_depot(repo):
    text = 'ISIN;Meldedatum;Ausschüttung;Währung\nIE00B4L5Y983;01.02.2024;1,25;EUR\n'
    result = run(repo, text, 'fonds.csv')[0]
    assert result.status == 'angelegt' and '1 übernommen' in result.message
    assert repo.document(result.document_id)['source'] == 'OeKB'


def test_missing_currency_stays_open(repo):
    result = run(repo, (HEADER + ROW).replace(';Währung', '').replace(';EUR', ''))[0]
    assert result.status == 'pruefen' and 'Währung' in result.message


def test_all_excel_sheets_are_considered(repo, depot):
    data = io.BytesIO()
    with pd.ExcelWriter(data, engine='openpyxl') as writer:
        for name in ('Erster', 'Zweiter'):
            automatic_tables((HEADER + ROW).encode(), 'x.csv')[0].to_excel(writer, index=False, sheet_name=name)
    upload = store_uploads(repo, [('export.xlsx', data.getvalue())], 2026)
    result = process_tables(repo, upload.csv_docs)[0]
    assert '1 übernommen, 1 Dubletten' in result.message


def test_historical_fx_is_used_automatically(repo):
    from kest_tool.fx import FxRates
    class Service:
        url = 'https://www.ecb.europa.eu/'
        def rates(self, **options):
            return FxRates({'USD': {date(2024, 2, 1): 1.08}})
    upload = store_uploads(repo, [('TradeRepublic.csv', (HEADER + ROW).replace('EUR', 'USD').encode())], 2026)
    result = process_tables(repo, upload.csv_docs, fx_service=Service())[0]
    assert result.status == 'angelegt', result.message
    tx = repo.transactions(2024)[0]
    assert tx['fx_rate'] == pytest.approx(1.08) and 'EZB' in tx['fx_source']
