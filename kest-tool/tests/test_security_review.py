import pytest

from kest_helpers import APPLE, SAP, MSCI_WORLD_ACC, ctx, repo  # noqa: F401
from kest_tool.security_review import review_reasons, save_security_review


def stock_values(isin=APPLE):
    return dict(isin=isin, name='Apple', security_type='Aktie', tax_class='beteiligung_kapitalgesellschaft',
                tax_class_verified=True, tax_class_source='Emittentenunterlage 2024', country='us')


def test_reviewed_security_saved_with_audit_and_without_inferred_fields(repo):
    save_security_review(repo, stock_values(), review='geprueft')
    sec = repo.security_by_isin(APPLE)
    assert not review_reasons(sec)
    assert sec['country'] == 'US'
    assert sec['ticker'] is None
    assert any(e['entity_id'] == APPLE for e in repo.audit_entries())


@pytest.mark.parametrize('changes', [{'tax_class_verified': False}, {'security_type': 'Sonstige'},
                                    {'name': None}, {'country': 'USA'}])
def test_incomplete_review_never_saved_as_complete(repo, changes):
    with pytest.raises(ValueError):
        save_security_review(repo, {**stock_values(), **changes}, review='geprueft')
    assert repo.security_by_isin(APPLE) is None


def test_fund_needs_verified_fund_status_but_draft_is_allowed(repo):
    values = dict(isin=MSCI_WORLD_ACC, name='ETF', security_type='ETF thesaurierend',
                  tax_class='investmentfonds', tax_class_verified=True, tax_class_source='Factsheet')
    with pytest.raises(ValueError, match='Meldefondsstatus'):
        save_security_review(repo, values, review='geprueft')
    save_security_review(repo, values, review='pruefen')
    assert review_reasons(repo.security_by_isin(MSCI_WORLD_ACC))
    save_security_review(repo, {**values, 'fund_status': 'meldefonds', 'fund_status_verified': True,
        'fund_status_source': 'OeKB-Abfrage'}, existing_isin=MSCI_WORLD_ACC, review='geprueft')
    assert not review_reasons(repo.security_by_isin(MSCI_WORLD_ACC))


def test_edit_clears_optional_fields_and_does_not_overwrite_another_security(repo):
    save_security_review(repo, {**stock_values(), 'ticker': 'AAPL'}, price_symbol='AAPL.US', review='geprueft')
    save_security_review(repo, {**stock_values(SAP), 'name': 'SAP'}, review='geprueft')
    save_security_review(repo, stock_values(), existing_isin=APPLE, review='geprueft')
    assert repo.security_by_isin(APPLE)['ticker'] is None
    assert repo.security_by_isin(APPLE)['price_symbol'] is None
    assert repo.security_by_isin(SAP)['name'] == 'SAP'
    with pytest.raises(ValueError, match='existiert bereits'):
        save_security_review(repo, stock_values())


def test_security_page_edits_current_card_without_selector_and_moves_to_next(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from kest_tool.config import load_settings
    from kest_tool.context import create_context
    home = tmp_path / 'cards'
    monkeypatch.setenv('KEST_TOOL_HOME', str(home))
    context = create_context(load_settings(), base_dir=home)
    context.repo.ensure_security(APPLE, 'Apple')
    context.repo.ensure_security(SAP, 'SAP')
    context.close()
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=120).run()
    for page_hash, info in at._registered_pages.items():
        if info.get('url_pathname') == 'wertpapiere':
            at._page_hash = page_hash
            break
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any(s.label == 'Bearbeiten' for s in at.selectbox)
    assert not any(t.label == 'Menü durchsuchen' for t in at.text_input)
    key = f'security_{APPLE}'
    at.text_input(key=key+'_name').set_value('Apple geprüft')
    at.selectbox(key=key+'_type').select('Aktie')
    at.selectbox(key=key+'_tax_class').select('beteiligung_kapitalgesellschaft')
    at.text_input(key=key+'_tax_source').set_value('Emittent')
    at.checkbox(key=key+'_tax_verified').check()
    at.selectbox(key=key+'_review').select('geprueft')
    next(b for b in at.button if b.label == 'Änderungen speichern').click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.text_input(key=f'security_{SAP}_name').value == 'SAP'
    assert any('Änderungen gespeichert' in s.value for s in at.success)
    context = create_context(load_settings(), base_dir=home)
    try:
        assert context.repo.security_by_isin(APPLE)['name'] == 'Apple geprüft'
        assert not review_reasons(context.repo.security_by_isin(APPLE))
        assert review_reasons(context.repo.security_by_isin(SAP))
    finally:
        context.close()
