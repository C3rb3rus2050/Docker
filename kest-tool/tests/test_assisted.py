import io
import json
from urllib.error import URLError

import pytest

from kest_tool.importers.assisted import AssistanceError, endpoint_url, suggest, validate_proposals


TEXT = 'ISIN US0378331005\nBruttobetrag 12,50 EUR\nZahltag 01.02.2024\nStück 2\nNetto 10,00 EUR'


def test_source_and_value_required_and_tax_fields_never_accepted():
    fields, rejected = validate_proposals({'fields': {
        'amount': {'value': '12,50', 'source': 'Bruttobetrag 12,50 EUR'},
        'isin': {'value': 'US0378331005', 'source': 'ISIN US0378331005'},
        'currency': {'value': 'USD', 'source': 'Bruttobetrag 12,50 EUR'},
        'fees': {'value': '1,00', 'source': 'Gebühren 1,00 EUR'},
        'tax_class': {'value': 'investmentfonds', 'source': TEXT},
        'trade_date': {'value': '01.02.2024', 'source': 'Zahltag 01.02.2024'},
    }}, TEXT)
    assert fields['amount']['value'] == 12.5
    assert fields['trade_date']['value'] == '2024-02-01'
    assert fields['isin']['confidence'] == 0  # no invented confidence percentage
    assert set(rejected) == {'currency', 'fees', 'tax_class'}


@pytest.mark.parametrize('name,raw', [('amount', '1,234'), ('amount', '-1'), ('amount', 'NaN'),
    ('amount', '1e5'), ('isin', 'US0378331006'), ('trade_date', '31.02.2024'),
    ('trade_date', '01.01.2999'), ('currency', 'euro'), ('fx_rate', '0')])
def test_invalid_or_ambiguous_values_discarded(name, raw):
    source = f'Angabe {raw}'
    fields, rejected = validate_proposals({'fields': {name: {'value': raw, 'source': source}}}, source)
    assert fields == {} and rejected == [name]


def test_partial_number_cannot_be_used_as_evidence():
    fields, rejected = validate_proposals({'fields': {'amount': {'value': '50',
        'source': 'Bruttobetrag 12,50 EUR'}}}, TEXT)
    assert fields == {} and rejected == ['amount']


@pytest.mark.parametrize('endpoint', ['file:///etc/passwd', 'http://user:pass@localhost',
    'http://localhost?token=x', 'http://localhost/api/generate', 'https://localhost/#x'])
def test_endpoint_must_be_plain_http_base(endpoint):
    with pytest.raises(AssistanceError):
        endpoint_url(endpoint)


def test_request_is_bounded_json_and_minimizes_identifiers(monkeypatch):
    calls = []
    class Client:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return io.BytesIO(json.dumps({'response': json.dumps({'fields': {
                'amount': {'value': '12,50', 'source': 'Bruttobetrag 12,50 EUR'}}})}).encode())
    monkeypatch.setattr('kest_tool.importers.assisted.build_opener', lambda *a: Client())
    result = suggest(TEXT + '\nname@example.com\nDE89370400440532013000', 'http://ollama:11434', 'qwen2.5:7b')
    assert result['fields']['amount']['value'] == 12.5
    request, timeout = calls[0]
    body = json.loads(request.data)
    assert body['stream'] is False and body['format'] == 'json'
    assert 'name@example.com' not in body['prompt'] and 'DE89370400440532013000' not in body['prompt']
    assert request.full_url == 'http://ollama:11434/api/generate'


@pytest.mark.parametrize('response', [b'not JSON', b'{"response":"{}"}', b'{}', b'x' * 128001],
                         ids=['invalid-json', 'missing-fields', 'missing-response', 'too-large'])
def test_bad_responses_fail_closed(monkeypatch, response):
    class Client:
        def open(self, *a, **kw):
            return io.BytesIO(response)
    monkeypatch.setattr('kest_tool.importers.assisted.build_opener', lambda *a: Client())
    with pytest.raises(AssistanceError):
        suggest(TEXT, 'http://ollama:11434', 'test')


def test_offline_failure_is_actionable(monkeypatch):
    class Client:
        def open(self, *a, **kw):
            raise URLError('offline')
    monkeypatch.setattr('kest_tool.importers.assisted.build_opener', lambda *a: Client())
    with pytest.raises(AssistanceError, match='Ollama'):
        suggest(TEXT, 'http://ollama:11434', 'test')


def test_apply_proposals_updates_draft_only_and_requires_new_confirmation(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from kest_tool.config import load_settings
    from kest_tool.context import create_context
    from kest_tool.demo import _pdf
    from kest_tool.processing import ProcessResult
    home = tmp_path / 'assistance'
    monkeypatch.setenv('KEST_TOOL_HOME', str(home))
    settings = load_settings(local_file=home / 'config' / 'config.yaml')
    settings.save_local({'assistant': {'enabled': True}})
    context = create_context(settings, base_dir=home)
    bid = context.repo.add_broker('Trade Republic', 'TradeRepublic')
    context.repo.add_depot(bid, 'TR')
    doc, _ = context.repo.add_document(_pdf(['Trade Republic', 'Kauf', 'ISIN US0378331005',
        'Datum 01.02.2024', 'Währung EUR']), 'unknown.pdf', status='pruefen', tax_year=2024)
    context.close()
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=120)
    key = f'upload_results_dash_{doc["id"]}'
    at.session_state['last_process_results'] = [ProcessResult(doc['id'], 'unknown.pdf', 'pruefen', 'Offen')]
    at.run()
    assert not at.exception
    at.number_input(key=key+'_quantity').set_value(3.0)
    at.checkbox(key=key+'_confirmed').check().run()
    at.session_state[key+'_ai_proposals'] = {'fields': {'amount': {'value': 12.5, 'source': 'Brutto 12,50'}},
                                           'rejected': [], 'model': 'test', 'truncated': False}
    at.run()
    at.multiselect(key=key+'_ai_selected').select('amount').run()
    at.button(key=key+'_ai_apply').click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.number_input(key=key+'_amount').value == 12.5
    assert at.number_input(key=key+'_quantity').value == 3
    assert at.checkbox(key=key+'_confirmed').value is False
    context = create_context(load_settings(), base_dir=home)
    try:
        assert not context.repo.transactions()
        assert context.repo.document(doc['id'])['status'] == 'pruefen'
        assert any(e['event'] == 'KI-Vorschläge ins Prüfformular übernommen'
                   for e in context.repo.document_events(doc['id']))
    finally:
        context.close()
