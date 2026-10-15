from datetime import date

import pytest

from kest_helpers import ctx, repo, depot  # noqa: F401
from kest_tool import demo
from kest_tool.models import FundReportIn, TransactionIn, TxType
from kest_tool.ui.record_tables import TX_FIELDS, FUND_FIELDS, grid_changes


def test_grid_validates_all_changes_and_preserves_zero(repo, depot):
    tid = repo.add_transaction(TransactionIn(depot_id=depot, tx_type=TxType.BUY,
        trade_date=date(2024, 1, 1), isin='US0378331005', quantity=1, amount=100, fees=1))
    old = repo.transaction(tid)
    record = {'ID': tid, **{k: old.get(k) for k in TX_FIELDS}}
    record['fees'] = 0
    changes = grid_changes([old], [record], 'transaction')
    assert changes == [(tid, {'fees': 0.0})]
    record['quantity'] = -1
    with pytest.raises(ValueError):
        grid_changes([old], [record], 'transaction')
    assert repo.transaction(tid)['fees'] == 1


def test_fund_correction_retains_link_and_audit(repo):
    doc, _ = repo.add_document(demo._pdf(['Original']), 'fonds.pdf')
    result = repo.add_fund_report(FundReportIn(isin='IE00B4L5Y983', report_date=date(2024, 1, 1),
                                              age_per_unit=2, document_id=doc['id']))
    repo.correct_fund_report(result['id'], {'age_per_unit': 3}, 'Wert aus Original berichtigt')
    current = repo.fund_reports()[0]
    assert current['age_per_unit'] == 3 and current['document_id'] == doc['id'] and current['version'] == 2
    audit = [r for r in repo.audit_entries() if r['entity'] == 'fund_report' and r['action'] == 'manuell geändert']
    assert audit and '2.0' in str(audit) and '3.0' in str(audit)
    with pytest.raises(ValueError):
        repo.correct_fund_report(result['id'], {'age_per_unit': 4}, '')
    with pytest.raises(ValueError):
        repo.correct_fund_report(result['id'], {'currency': 'USD', 'fx_rate': None}, 'Test')
    with pytest.raises(ValueError):
        repo.correct_fund_report(result['id'], {'age_per_unit': float('inf')}, 'Test')


def test_nonfinite_values_rejected_before_saving(repo):
    result = repo.add_fund_report(FundReportIn(isin='IE00B4L5Y983', report_date=date(2024, 1, 1), age_per_unit=2))
    old = repo.fund_reports()[0]
    edited = {'ID': result['id'], **{k: old.get(k) for k in FUND_FIELDS}}
    edited['age_per_unit'] = float('inf')
    with pytest.raises(ValueError, match='endliche'):
        grid_changes([old], [edited], 'fund')
