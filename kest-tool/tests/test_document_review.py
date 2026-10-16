from datetime import date
import json

import pytest

from kest_helpers import APPLE, add_tx, ctx, repo, depot  # noqa: F401
from kest_tool.demo import _pdf
from kest_tool.document_review import save_review
from kest_tool.importers.pdf_importer import PARSER_VERSION
from kest_tool.models import TxType


def document(repo):
    doc, _ = repo.add_document(_pdf(['Trade Republic', 'Wertpapierabrechnung Kauf', 'ISIN: '+APPLE,
                                    'Datum 01.02.2024', 'Währung EUR']), 'unvollstaendig.pdf',
                               source='TradeRepublic', status='pruefen', tax_year=2024)
    return doc


def values(depot):
    return dict(depot_id=depot, tx_type='Kauf', trade_date=date(2024, 2, 1),
                isin=APPLE, quantity=2, amount=100, currency='EUR')


def test_manual_completion_finishes_originally_incomplete_document(repo, depot):
    doc = document(repo)
    tid = save_review(repo, doc['id'], values(depot), confirmed=True)
    assert repo.document(doc['id'])['status'] == 'verarbeitet'
    assert repo.transaction(tid)['review_status'] == 'geprueft'
    assert json.loads(repo.document(doc['id'])['extraction_json'])['manual_review']['confirmed']
    with pytest.raises(ValueError, match='bereits eine Buchung'):
        save_review(repo, doc['id'], values(depot), confirmed=True)
    assert len(repo.transactions()) == 1


@pytest.mark.parametrize('overrides', [{'amount': None}, {'currency': 'USD', 'fx_rate': None},
                                     {'isin': 'US0378331006'}, {'quantity': None}])
def test_incomplete_or_invalid_manual_values_never_create_booking(repo, depot, overrides):
    doc = document(repo)
    with pytest.raises(ValueError):
        save_review(repo, doc['id'], {**values(depot), **overrides}, confirmed=True)
    assert not repo.transactions() and repo.document(doc['id'])['status'] == 'pruefen'


def test_original_confirmation_required(repo, depot):
    doc = document(repo)
    with pytest.raises(ValueError, match='Original'):
        save_review(repo, doc['id'], values(depot), confirmed=False)
    assert not repo.transactions()


def test_linked_booking_updated_in_place_with_audit(repo, depot):
    doc = document(repo)
    tid = save_review(repo, doc['id'], values(depot), confirmed=True)
    save_review(repo, doc['id'], {**values(depot), 'amount': 120}, confirmed=True,
                transaction_id=tid, reason='Brutto im Original korrigiert')
    assert len(repo.transactions()) == 1
    assert repo.transaction(tid)['amount'] == 120
    assert any(a['entity'] == 'transaction' and a['action'] == 'manuell geändert' for a in repo.audit_entries())


def test_duplicate_is_blocked_before_marking_document_done(repo, depot):
    doc = document(repo)
    add_tx(repo, depot, TxType.BUY, '2024-02-01', isin=APPLE, quantity=2, amount=100)
    with pytest.raises(ValueError, match='Identische Buchung'):
        save_review(repo, doc['id'], values(depot), confirmed=True)
    assert repo.document(doc['id'])['status'] == 'pruefen'


def test_import_results_stay_editable_across_widget_reruns(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from kest_tool.config import load_settings
    from kest_tool.context import create_context
    from kest_tool.processing import ProcessResult
    home = tmp_path / 'inline'
    monkeypatch.setenv('KEST_TOOL_HOME', str(home))
    context = create_context(load_settings(local_file=tmp_path / 'none.yaml'), base_dir=home)
    bid = context.repo.add_broker('Trade Republic', 'TradeRepublic')
    dep = context.repo.add_depot(bid, 'TR')
    doc = document(context.repo)
    context.close()
    app = str(Path(__file__).resolve().parents[1] / 'app.py')
    at = AppTest.from_file(app, default_timeout=120)
    at.session_state['last_process_results'] = [ProcessResult(doc['id'], doc['original_filename'], 'pruefen', 'Werte fehlen')]
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    key = f'upload_results_dash_{doc["id"]}'
    assert at.number_input(key=key+'_quantity').value is None
    assert at.number_input(key=key+'_amount').value is None
    at.number_input(key=key+'_quantity').set_value(2.0).run()
    assert at.number_input(key=key+'_quantity').value == 2
    at.number_input(key=key+'_amount').set_value(100.0)
    at.selectbox(key=key+'_currency').select('EUR')
    at.checkbox(key=key+'_confirmed').check()
    next(b for b in at.button if b.label == 'Geprüfte Buchung speichern').click().run()
    assert not at.exception, [e.value for e in at.exception]
    context = create_context(load_settings(local_file=tmp_path / 'none.yaml'), base_dir=home)
    try:
        assert context.repo.document(doc['id'])['status'] == 'verarbeitet'
        assert len(context.repo.transactions()) == 1
        assert context.repo.transactions()[0]['review_status'] == 'geprueft'
    finally:
        context.close()


def test_document_page_opens_one_card_and_moves_to_next_without_selector(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from kest_tool.config import load_settings
    from kest_tool.context import create_context
    home = tmp_path / 'cards'
    monkeypatch.setenv('KEST_TOOL_HOME', str(home))
    context = create_context(load_settings(local_file=tmp_path / 'none.yaml'), base_dir=home)
    bid = context.repo.add_broker('Trade Republic', 'TradeRepublic')
    context.repo.add_depot(bid, 'TR')
    first = document(context.repo)
    second, _ = context.repo.add_document(_pdf(['Trade Republic', 'Dividende', 'ISIN: '+APPLE,
        'Datum 03.02.2024', 'Währung EUR']), 'zweiter-beleg.pdf', source='TradeRepublic', status='pruefen', tax_year=2024)
    context.close()
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=120).run()
    for page_hash, info in at._registered_pages.items():
        if info.get('url_pathname') == 'dokumente':
            at._page_hash = page_hash
            break
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.number_input(key=f'documents_direct_{second["id"]}_amount').value is None
    at.button(key='documents_direct_next').click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.number_input(key=f'documents_direct_{first["id"]}_amount').value is None
    assert not at.button(key='documents_direct_previous').disabled
    assert at.button(key='documents_direct_next').disabled
    at.button(key='documents_direct_previous').click().run()
    assert at.number_input(key=f'documents_direct_{second["id"]}_amount').value is None
    assert not any(s.label == 'Ausgewählten Beleg öffnen' for s in at.selectbox)
