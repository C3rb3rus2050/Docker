from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import application
from app.runtime import Runtime
from kest_tool import demo
from kest_tool.config import load_settings
from kest_tool.context import create_context, shutdown_logging
from kest_tool.models import TransactionIn, TxType
from kest_tool.tax.engine import compute


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('KEST_TOOL_HOME', str(tmp_path / 'data'))
    settings = load_settings()
    settings.save_local({'fx': {'auto_fetch': False}})
    context = create_context(settings)
    runtime = Runtime(context)
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<html>React test shell</html>')
    (dist / 'assets' / 'app.js').write_text('console.log("test")')
    with TestClient(application(runtime, dist), headers={'X-KESt-Request': '1'}) as client:
        yield client, context
    runtime.close()
    shutdown_logging()


def depot(c):
    bid = c.repo.add_broker('Trade Republic', 'TradeRepublic')
    return c.repo.add_depot(bid, 'Depot')


def tx(did):
    return {'depot_id': did, 'tx_type': 'Kauf', 'trade_date': '2024-02-01',
            'isin': 'US0378331005', 'security_name': 'Muster', 'quantity': 2,
            'amount': 100, 'currency': 'EUR'}


def test_deployment_prefix_health_spa_and_unknown_api(env):
    client, c = env
    assert client.get('/').url.path == '/steuer/'
    assert client.get('/steuer/api/health').json()['frontend'] is True
    assert 'React test shell' in client.get('/steuer/wertpapiere').text
    assert client.get('/steuer/assets/app.js').status_code == 200
    assert client.get('/steuer/api/not-real').status_code == 404
    assert client.get('/steuer/api/meta').json()['version'] == '2.0.1'


def test_browser_boundary_rejects_cross_site_writes(env):
    client, c = env
    r = client.post('/steuer/api/brokers', json={'name': 'Other'}, headers={'X-KESt-Request': ''})
    assert r.status_code == 403
    r = client.post('/steuer/api/brokers', json={'name': 'Other'}, headers={'Sec-Fetch-Site': 'cross-site'})
    assert r.status_code == 403 and not c.repo.brokers()


def test_existing_data_visible_after_reopening_with_new_server(env):
    client, c = env
    tid = c.repo.add_transaction(TransactionIn(**tx(depot(c))))
    before = c.db.one('SELECT * FROM transactions WHERE id=?', (tid,))
    rows = client.get('/steuer/api/transactions?year=2024').json()
    assert rows[0]['id'] == tid and rows[0]['amount'] == 100
    assert client.get('/steuer/api/dashboard?year=2024').json()['stats']['transactions'] == 1
    assert before == c.db.one('SELECT * FROM transactions WHERE id=?', (tid,))


def test_transaction_edit_revision_audit_duplicate_and_soft_delete(env):
    client, c = env
    values = tx(depot(c))
    r = client.post('/steuer/api/transactions', json={'values': values})
    assert r.status_code == 200, r.text
    tid = r.json()['id']
    assert client.post('/steuer/api/transactions', json={'values': values}).status_code == 409
    old = client.get(f'/steuer/api/transactions/{tid}').json()
    assert client.patch(f'/steuer/api/transactions/{tid}', json={'values': {'amount': 110}}).status_code == 422
    assert client.patch(f'/steuer/api/transactions/{tid}', json={
        'values': {'amount': 110}, 'reason': 'Original korrigiert', 'revision': old['revision']}).status_code == 200
    assert c.repo.transaction(tid)['amount_eur'] == 110
    assert client.patch(f'/steuer/api/transactions/{tid}', json={
        'values': {'amount': 90}, 'reason': 'alter Tab', 'revision': old['revision']}).status_code == 409
    assert client.request('DELETE', f'/steuer/api/transactions/{tid}', json={'values': {}, 'reason': 'Fehlbuchung'}).status_code == 200
    assert not c.repo.transactions() and c.repo.transaction(tid)['deleted'] == 1
    assert any(a['action'] == 'gelöscht (logisch)' for a in c.repo.audit_entries())


def test_upload_original_byte_identity_duplicates_and_review(env):
    client, c = env
    d = depot(c)
    payload = demo._pdf(['Trade Republic', 'Wertpapierabrechnung: Kauf', 'ISIN US0378331005',
                         'Ausführungstag 01.02.2024', 'Stückzahl 2', 'Kurswert 100,00 EUR'])
    response = client.post('/steuer/api/import', data={'year': '2024'},
                           files=[('files', ('muster.pdf', payload, 'application/pdf'))])
    assert response.status_code == 200, response.text
    did = response.json()['results'][0]['document_id']
    original = client.get(f'/steuer/api/documents/{did}/original')
    assert original.content == payload
    assert original.headers['content-type'].startswith('application/pdf')
    assert original.headers['cache-control'] == 'no-store'
    repeated = client.post('/steuer/api/import', data={'year': '2024'},
                           files=[('files', ('muster.pdf', payload, 'application/pdf'))])
    assert repeated.json()['upload']['duplicates'] == 1
    doc = client.get(f'/steuer/api/documents/{did}').json()
    values = tx(d)
    tid = doc['transactions'][0]['id'] if doc['transactions'] else None
    response = client.post(f'/steuer/api/documents/{did}/review', json={
        'values': values, 'confirmed': True, 'transaction_id': tid,
        'reason': 'Mit Original abgeglichen', 'revision': doc['revision']})
    assert response.status_code == 200, response.text
    assert len(c.repo.transactions()) == 1
    assert c.repo.document(did)['status'] == 'verarbeitet'


def test_review_rejects_unrelated_transaction(env):
    client, c = env
    d = depot(c)
    tid = c.repo.add_transaction(TransactionIn(**tx(d)))
    doc, _ = c.repo.add_document(demo._pdf(['Trade Republic', 'Kosteninformation']), 'kosten.pdf')
    r = client.post(f'/steuer/api/documents/{doc["id"]}/review', json={
        'values': tx(d), 'confirmed': True, 'transaction_id': tid, 'reason': 'falsch'})
    assert r.status_code == 422
    assert c.repo.transaction(tid)['review_status'] == 'ungeprueft'


def test_reading_does_not_download_fx_and_unknown_upload_is_reviewed(env, monkeypatch):
    client, c = env
    def forbidden(*args, **kwargs):
        raise AssertionError('No external request on GET')
    monkeypatch.setattr('kest_tool.fx.FxService.download', forbidden)
    doc, _ = c.repo.add_document(demo._pdf(['Trade Republic', 'Dividendenabrechnung', 'Brutto 2 USD']), 'offen.pdf')
    assert client.get(f'/steuer/api/documents/{doc["id"]}').status_code == 200
    r = client.post('/steuer/api/documents/process', json={'ids': [doc['id']]})
    assert r.status_code == 200 and r.json()[0]['status'] == 'pruefen'


def test_document_metadata_is_whitelisted_and_versioned(env):
    client, c = env
    doc, _ = c.repo.add_document(demo._pdf(['MUSTER']), 'muster.pdf')
    base = f'/steuer/api/documents/{doc["id"]}'
    assert client.patch(base, json={'values': {'stored_path': '../secret'}}).status_code == 422
    assert client.patch(base, json={'values': {'status': 'bad'}}).status_code == 422
    assert client.patch(base, json={'values': {'status': 'ignoriert'}}).status_code == 200
    assert c.repo.document(doc['id'])['status'] == 'ignoriert'


def test_security_review_requires_sources_and_keeps_optional_clearing(env):
    client, c = env
    values = {'isin': 'US0378331005', 'name': 'Apple', 'security_type': 'Aktie'}
    assert client.post('/steuer/api/securities', json={'values': values}).status_code == 200
    base = '/steuer/api/securities/US0378331005'
    r = client.patch(base, json={'values': values, 'review': 'geprueft'})
    assert r.status_code == 422
    values.update(tax_class='beteiligung_kapitalgesellschaft', tax_class_source='Emittent', tax_class_verified=True)
    r = client.patch(base, json={'values': values, 'review': 'geprueft'})
    assert r.status_code == 200, r.text
    assert client.get(base).json()['review_reasons'] == []
    values['country'] = None
    assert client.patch(base, json={'values': values, 'review': 'geprueft'}).status_code == 200


def test_broker_depot_year_specific_tax_settings(env):
    client, c = env
    b = client.post('/steuer/api/brokers', json={'name': 'Scalable', 'key': 'ScalableCapital'}).json()['id']
    r = client.post('/steuer/api/depots', json={'broker_id': b, 'name': 'Depot'})
    assert r.status_code == 200, r.text
    d = r.json()['id']
    body = {'kest_withheld': 'nein', 'loss_offset_by_broker': 'nein', 'source': 'Beleg'}
    assert client.put(f'/steuer/api/depots/{d}/tax/2024', json=body).status_code == 200
    assert client.get(f'/steuer/api/depots/{d}/tax/2025').json()['kest_withheld'] == 'unbekannt'


def test_tax_result_is_identical_to_domain_calculation(env):
    client, c = env
    c.repo.add_transaction(TransactionIn(**tx(depot(c))))
    expected = compute(c.repo, 2024)
    response = client.get('/steuer/api/tax/2024')
    assert response.status_code == 200, response.text
    assert response.json()['summary'] == expected.summary
    assert response.json()['summary_confirmed'] == expected.summary_confirmed
    assert response.json()['positions'] == json.loads(json.dumps(expected.positions, default=str))


@pytest.mark.parametrize('kind', ['excel', 'csv', 'pdf', 'e1kv'])
def test_exports_downloads_are_record_based_and_inside_store(env, kind):
    client, c = env
    c.repo.add_transaction(TransactionIn(**tx(depot(c))))
    r = client.post('/steuer/api/exports/2024/'+kind)
    assert r.status_code == 200, r.text
    entry = r.json()[0]
    response = client.get(f'/steuer/api/exports/{entry["id"]}/download')
    assert response.status_code == 200
    assert response.content == c.store.absolute(entry['stored_path']).read_bytes()
    assert client.get('/steuer/api/exports/999999/download').status_code == 404


def test_fund_reports_and_price_conflicts(env):
    client, c = env
    values = {'isin': 'IE00B4L5Y983', 'report_date': '2024-02-01', 'age_per_unit': 1.0}
    assert client.post('/steuer/api/funds', json=values).status_code == 200
    assert client.post('/steuer/api/funds', json={**values, 'age_per_unit': 2}).json()['status'] == 'konflikt'
    assert client.get('/steuer/api/conflicts').json()
    assert len(client.get('/steuer/api/funds').json()) == 2
    price = {'isin': 'IE00B4L5Y983', 'tax_year': 2024, 'first_price': 10, 'last_price': 11, 'source': 'Emittent'}
    assert client.post('/steuer/api/nmf-prices', json=price).status_code == 200
    assert client.post('/steuer/api/nmf-prices', json={**price, 'last_price': 12}).json()['status'] == 'konflikt'


def test_settings_and_api_key_never_return_secret(env, monkeypatch):
    client, c = env
    monkeypatch.delenv('EODHD_API_KEY', raising=False)
    key = 'synthetic-test-secret'
    assert client.put('/steuer/api/settings/eodhd', json={'values': {'key': key}}).status_code == 200
    r = client.get('/steuer/api/settings')
    assert r.status_code == 200 and r.json()['eodhd_configured'] is True
    assert key not in r.text and key not in client.get('/steuer/api/meta').text
    r = client.put('/steuer/api/settings', json={'values': {'assistant': {
        'enabled': True, 'endpoint': 'http://test-ollama:11434', 'model': 'test-model'}}})
    assert r.status_code == 200, r.text
    assert client.get('/steuer/api/settings').json()['assistant']['model'] == 'test-model'


def test_assistant_requires_per_document_consent(env):
    client, c = env
    doc, _ = c.repo.add_document(demo._pdf(['MUSTER']), 'muster.pdf')
    r = client.post(f'/steuer/api/documents/{doc["id"]}/assistant', json={'confirmed': False})
    assert r.status_code == 422


def test_consistent_backup_download_and_no_arbitrary_paths(env):
    import io, zipfile
    client, c = env
    c.repo.add_transaction(TransactionIn(**tx(depot(c))))
    r = client.post('/steuer/api/backup')
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert any(n.endswith('kest_tool.db') for n in z.namelist())
    assert client.get('/steuer/api/documents/999999/original').status_code == 404
    assert 'PYTHON' not in client.get('/steuer/../requirements.txt').text


def test_nested_zip_upload_and_empty_table_cells(env):
    import io, zipfile
    client, c = env
    data = b'Datum;Art;ISIN;Stueck;Betrag;Waehrung\n2024-02-01;Kauf;US0378331005;2;100;EUR\n'
    depot(c)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('folder/trades.csv', data)
    r = client.post('/steuer/api/import', data={'year': '2024'},
                    files=[('files', ('muster.zip', archive.getvalue(), 'application/zip'))])
    assert r.status_code == 200, r.text
    assert not r.json()['upload']['skipped']
    doc = c.repo.documents()[0]
    preview = client.get(f'/steuer/api/documents/{doc["id"]}/preview')
    assert preview.status_code == 200, preview.text
    assert preview.json()[0]['total'] == 1
    assert client.get('/steuer/assets/missing.js').status_code == 404


def test_fund_document_review_is_not_a_duplicate_dividend(env):
    client, c = env
    doc, _ = c.repo.add_document(demo._pdf(['OeKB']), 'fonds.pdf', doc_type='OeKB-Fondsmeldung')
    values = {'isin': 'IE00B4L5Y983', 'report_date': '2024-02-01', 'age_per_unit': 1, 'source': 'Muster'}
    r = client.post(f'/steuer/api/documents/{doc["id"]}/fund-review', json={'values': values, 'confirmed': True})
    assert r.status_code == 200, r.text
    assert len(c.repo.fund_reports()) == 1 and not c.repo.transactions()
    assert c.repo.document(doc['id'])['status'] == 'verarbeitet'


def test_malformed_settings_do_not_damage_configuration(env):
    client, c = env
    original = client.get('/steuer/api/settings').json()
    for values in [{'pdf': 'bad'}, {'assistant': {'enabled': 'true'}}, {'tax_years': ['bad']},
                   {'fx': {'auto_fetch': 'yes'}}]:
        assert client.put('/steuer/api/settings', json={'values': values}).status_code == 422
    assert client.get('/steuer/api/settings').json() == original


def test_restore_requires_confirmation_and_keeps_pre_restore_copy(env):
    client, c = env
    tid = c.repo.add_transaction(TransactionIn(**tx(depot(c))))
    saved = client.post('/steuer/api/backup').content
    c.repo.update_transaction(tid, {'amount': 200}, 'Musteränderung nach Sicherung')
    files = [('file', ('backup.zip', saved, 'application/zip'))]
    assert client.post('/steuer/api/backup/restore', files=files).status_code == 422
    r = client.post('/steuer/api/backup/restore', data={'confirmed': 'true'}, files=files)
    assert r.status_code == 200, r.text
    assert client.get(f'/steuer/api/transactions/{tid}').json()['transaction']['amount'] == 100
    assert list(c.base_dir.joinpath('backups').glob('vor_Wiederherstellung_*'))


def test_invalid_restore_never_closes_live_database(env):
    client, c = env
    assert client.post('/steuer/api/backup/restore', data={'confirmed': 'true'},
                       files=[('file', ('bad.zip', b'not zip'))]).status_code == 422
    assert client.get('/steuer/api/health').status_code == 200
