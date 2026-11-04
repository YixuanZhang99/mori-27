"""Real loopback HTTP tests; these are not external model measurements."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.llm import UsageError, take_usage
from zoo.mle_bench_lite.agent_common import token_usage_summary
from zoo.mle_bench_lite.provider import BenchmarkProvider


@pytest.fixture
def endpoint():
    class Server:
        replies = []
        requests = []
    state = Server()
    state.replies, state.requests = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            assert self.headers['Authorization'] == 'Bearer provider-test-secret'
            if hasattr(state, 'observe_dispatch'):
                state.observe_dispatch()
            value = state.replies.pop(0)
            if value == 'redirect':
                self.send_response(307)
                self.send_header('Location', '/v1/leaked')
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.url = f'http://127.0.0.1:{server.server_port}/v1'
    yield state
    server.shutdown(); server.server_close(); worker.join(timeout=5)


def response(model='fixed-snapshot', total=7, content='print(42)'):
    return {'model': model, 'usage': {'total_tokens': total},
            'choices': [{'message': {'content': content}}]}


def provider(tmp_path, endpoint, **options):
    return BenchmarkProvider('requested-alias', endpoint.url, tmp_path / 'token_usage',
        options.pop('token_budget', 100), api_key='provider-test-secret', **options)


def test_actual_model_receipts_exact_bill_and_reopening_preserve_identity(tmp_path, endpoint):
    endpoint.replies.extend([response(), response(total=11)])
    p = provider(tmp_path, endpoint, max_completion_tokens=8)
    assert p('one') == 'print(42)'
    assert take_usage(p) == 7
    assert take_usage(p) == 0
    p2 = provider(tmp_path, endpoint, max_completion_tokens=8)
    p2('two')
    assert p2.actual_model == 'fixed-snapshot'
    usage = token_usage_summary(tmp_path / 'token_usage')
    assert usage['total_tokens'] == 18 and usage['models'] == ['fixed-snapshot']
    assert all(r['model'] == 'requested-alias' and r['max_completion_tokens'] == 8
               for r in endpoint.requests)
    evidence = ''.join(p.read_text() for p in tmp_path.rglob('*.json'))
    assert 'provider-test-secret' not in evidence and 'print(42)' not in evidence


def test_response_model_drift_preserves_charge_and_blocks_more_http(tmp_path, endpoint):
    endpoint.replies.extend([response(), response(model='other-snapshot')])
    p = provider(tmp_path, endpoint)
    p('one')
    with pytest.raises(ValueError, match='model changed'):
        p('two')
    assert take_usage(p) == 7
    with pytest.raises(UsageError, match='unresolved'):
        p('three')
    assert len(endpoint.requests) == 2
    with pytest.raises(ValueError, match='model changed'):
        provider(tmp_path, endpoint)


@pytest.mark.parametrize('invalid', [None, '', 123])
def test_missing_model_is_not_inferred_from_requested_alias(tmp_path, endpoint, invalid):
    endpoint.replies.append(response(model=invalid))
    p = provider(tmp_path, endpoint)
    with pytest.raises(ValueError, match='actual model'):
        p('one')
    assert take_usage(p) == 7
    with pytest.raises(ValueError, match='receipt identity'):
        token_usage_summary(tmp_path / 'token_usage')


@pytest.mark.parametrize('invalid', [None, {}, {'total_tokens': True},
    {'total_tokens': 7, 'prompt_tokens': 6, 'completion_tokens': 2}])
def test_unknown_usage_stays_pending_across_process_restart(tmp_path, endpoint, invalid):
    value = response(); value['usage'] = invalid
    endpoint.replies.append(value)
    p = provider(tmp_path, endpoint)
    with pytest.raises(UsageError):
        p('one')
    assert p.last_usage is None
    with pytest.raises(UsageError, match='unfinished'):
        provider(tmp_path, endpoint)
    assert len(endpoint.requests) == 1


def test_malformed_content_does_not_erase_known_usage(tmp_path, endpoint):
    endpoint.replies.append(response(content=None))
    p = provider(tmp_path, endpoint)
    with pytest.raises(ValueError, match='usable content'):
        p('one')
    assert take_usage(p) == 7
    assert token_usage_summary(tmp_path / 'token_usage')['total_tokens'] == 7


def test_single_response_overspend_is_measured_and_prevents_another_request(tmp_path, endpoint):
    endpoint.replies.append(response(total=12))
    p = provider(tmp_path, endpoint, token_budget=10, max_completion_tokens=8)
    with pytest.raises(ValueError, match='exceeded'):
        p('one')
    assert take_usage(p) == 12
    with pytest.raises(ValueError, match='exhausted'):
        p('two')
    assert len(endpoint.requests) == 1
    assert token_usage_summary(tmp_path / 'token_usage')['total_tokens'] == 12


def test_redirect_is_not_followed_or_retried(tmp_path, endpoint):
    endpoint.replies.append('redirect')
    p = provider(tmp_path, endpoint)
    with pytest.raises(UsageError, match='unknown usage'):
        p('one')
    assert p.last_usage is None and len(endpoint.requests) == 1


@pytest.mark.parametrize('url', ['http://example.com/v1', 'https://user:secret@example.com/v1',
    'https://example.com/v1?api_key=secret', 'file:///tmp/fixture', 'https://example.com/#secret'])
def test_unsafe_endpoint_rejected_before_request(tmp_path, url):
    with pytest.raises(ValueError, match='HTTPS'):
        BenchmarkProvider('model', url, tmp_path / 'usage', 100)


def test_no_key_is_zero_cost_and_does_not_write_call_intent(tmp_path, endpoint):
    p = BenchmarkProvider('model', endpoint.url, tmp_path / 'usage', 100, api_key='')
    with pytest.raises(ValueError, match='API_KEY'):
        p('one')
    assert take_usage(p) == 0 and not endpoint.requests
    assert not list(p.calls_dir.iterdir())


@pytest.mark.parametrize('tamper', ['receipt_bill', 'completion_hash', 'request_hash', 'delete_start'])
def test_reopened_provider_rejects_changed_call_evidence_without_paid_retry(tmp_path, endpoint, tamper):
    endpoint.replies.append(response())
    p = provider(tmp_path, endpoint); p('one')
    receipt_path = next(p.usage_dir.glob('*.json'))
    start_path = next(p.calls_dir.glob('*.started.json'))
    end_path = next(p.calls_dir.glob('*.completed.json'))
    if tamper == 'delete_start':
        start_path.unlink()
    else:
        path = {'receipt_bill': receipt_path, 'completion_hash': end_path, 'request_hash': start_path}[tamper]
        value = json.loads(path.read_text())
        if tamper == 'receipt_bill':
            value['total_tokens'] = 0
        elif tamper == 'completion_hash':
            value['usage_receipt_sha256'] = '0' * 64
        else:
            value['request_sha256'] = '0' * 64
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, UsageError)):
        provider(tmp_path, endpoint)
    assert len(endpoint.requests) == 1


def deepseek_response(*, finish_reason='stop', content='print(42)'):
    return {'id': 'response-1', 'created': 1793775000, 'model': 'deepseek-flash',
        'system_fingerprint': 'backend-fixture',
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
                  'prompt_cache_hit_tokens': 80, 'prompt_cache_miss_tokens': 20,
                  'completion_tokens_details': {'reasoning_tokens': 15}},
        'choices': [{'finish_reason': finish_reason, 'message': {'content': content}}]}


def deepseek_provider(tmp_path, endpoint, ledger, **options):
    return BenchmarkProvider('deepseek-flash', endpoint.url, tmp_path / 'token_usage',
        60000, max_completion_tokens=16384, api_key='provider-test-secret',
        request_format='deepseek', spending_ledger=ledger, **options)


def test_deepseek_wire_contract_and_durable_charge(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    observed = []
    endpoint.observe_dispatch = lambda: observed.append(CampaignBudget(ledger.path).snapshot())
    endpoint.replies.append(deepseek_response())
    p = deepseek_provider(tmp_path, endpoint, ledger)
    assert p('one') == 'print(42)'
    request = endpoint.requests[0]
    assert request['max_tokens'] == 16384 and 'max_completion_tokens' not in request
    assert request['thinking'] == {'type': 'enabled'} and request['reasoning_effort'] == 'high'
    assert request['stream'] is False and 'temperature' not in request
    receipt = json.loads(next(p.usage_dir.glob('*.json')).read_text())
    assert receipt['completion_tokens_details'] == {'reasoning_tokens': 15}
    assert receipt['system_fingerprint'] == 'backend-fixture'
    assert receipt['immutable_snapshot_verified'] is False
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 360
    assert ledger.snapshot()['pending_calls'] == []
    assert take_usage(p) == 120
    operation = ledger.snapshot()['operations'][0]
    assert operation['call_id'] == receipt['usage_id']
    assert operation['request_sha256'] == receipt['request_sha256']
    assert operation['response_sha256'] == receipt['response_sha256']
    assert observed[0]['reserved_micro_cny'] == 2228224
    assert observed[0]['pending_calls'] == [receipt['usage_id']]


def test_budget_refusal_performs_zero_http_and_writes_no_local_call(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db', limit_micro_cny=1000)
    p = deepseek_provider(tmp_path, endpoint, ledger)
    with pytest.raises(ValueError, match='exhausted'):
        p('one')
    assert endpoint.requests == [] and take_usage(p) == 0
    assert list(p.calls_dir.iterdir()) == []


@pytest.mark.parametrize('finish_reason', ['length', 'content_filter', None])
def test_incomplete_deepseek_output_is_charged_before_rejection(tmp_path, endpoint, finish_reason):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response(finish_reason=finish_reason))
    p = deepseek_provider(tmp_path, endpoint, ledger)
    with pytest.raises(ValueError, match='completion'):
        p('one')
    assert take_usage(p) == 120
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 360
    assert ledger.snapshot()['pending_calls'] == []
    assert token_usage_summary(p.usage_dir)['total_tokens'] == 120


def test_missing_detailed_usage_blocks_paid_requests_in_fresh_run(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(response(model='deepseek-flash', total=120))
    p = deepseek_provider(tmp_path / 'first', endpoint, ledger)
    with pytest.raises(ValueError, match='integer'):
        p('one')
    assert take_usage(p) == 120  # known total is not erased by missing components
    assert ledger.snapshot()['reserved_micro_cny'] == 2228224
    other = deepseek_provider(tmp_path / 'other', endpoint, CampaignBudget(ledger.path))
    with pytest.raises(ValueError, match='unresolved'):
        other('two')
    assert len(endpoint.requests) == 1 and take_usage(other) == 0


def test_deepseek_endpoint_cannot_silently_use_unbudgeted_generic_protocol(tmp_path):
    with pytest.raises(ValueError, match='campaign'):
        BenchmarkProvider('deepseek-flash', 'https://api.deepseek.com', tmp_path / 'usage', 60000)


def test_different_campaign_resume_refused_before_http(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'one.db')
    endpoint.replies.append(deepseek_response())
    deepseek_provider(tmp_path, endpoint, ledger)('one')
    other = CampaignBudget.create(tmp_path / 'two.db')
    with pytest.raises(ValueError, match='campaign|provider configuration'):
        deepseek_provider(tmp_path, endpoint, other)
    assert len(endpoint.requests) == 1


def test_deepseek_http_failure_reservation_survives_a_fresh_provider(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append('redirect')
    p = deepseek_provider(tmp_path / 'first', endpoint, ledger)
    with pytest.raises(UsageError, match='unknown usage'):
        p('one')
    assert p.last_usage is None
    other = deepseek_provider(tmp_path / 'other', endpoint, CampaignBudget(ledger.path))
    with pytest.raises(ValueError, match='unresolved'):
        other('two')
    assert len(endpoint.requests) == 1
    assert ledger.snapshot()['reserved_micro_cny'] == 2228224


@pytest.mark.parametrize('returned_model', ['deepseek-pro', '', None])
def test_wrong_deepseek_model_preserves_tokens_but_cannot_settle_flash_prices(tmp_path, endpoint, returned_model):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    value = deepseek_response(); value['model'] = returned_model
    endpoint.replies.append(value)
    p = deepseek_provider(tmp_path / 'first', endpoint, ledger)
    with pytest.raises(ValueError, match='model'):
        p('one')
    assert take_usage(p) == 120
    receipt = json.loads(next(p.usage_dir.glob('*.json')).read_text())
    assert receipt['total_tokens'] == 120
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 0
    assert ledger.snapshot()['reserved_micro_cny'] == 2228224
    other = deepseek_provider(tmp_path / 'other', endpoint, CampaignBudget(ledger.path))
    with pytest.raises(ValueError, match='unresolved'):
        other('two')
    assert len(endpoint.requests) == 1


def test_full_output_and_input_capacity_refusal_preserves_prior_charge(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    first = deepseek_response()
    first['usage'] = {'prompt_tokens': 30000, 'completion_tokens': 15787, 'total_tokens': 45787}
    last = deepseek_response()
    last['usage'] = {'prompt_tokens': 4480, 'completion_tokens': 12563, 'total_tokens': 17043}
    endpoint.replies.extend([first, last])
    p = deepseek_provider(tmp_path, endpoint, ledger)
    p('a' * 30000)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='capacity'):
        p('last candidate')
    assert len(endpoint.requests) == 1
    assert take_usage(p) == 0
    assert ledger.snapshot() == before
    assert token_usage_summary(p.usage_dir)['total_tokens'] == 45787


def test_unicode_input_capacity_is_checked_before_any_paid_reservation(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response())
    p = deepseek_provider(tmp_path, endpoint, ledger)
    with pytest.raises(ValueError, match='capacity'):
        p('界' * 15000)
    assert not endpoint.requests and take_usage(p) == 0
    assert ledger.snapshot()['operations'] == []
    assert not list(p.calls_dir.iterdir())


def test_model_capacity_mode_refuses_a_small_budget_before_http(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response())
    p = deepseek_provider(tmp_path, endpoint, ledger, token_admission='model_capacity_v1')
    with pytest.raises(ValueError, match='capacity'):
        p('one')
    assert not endpoint.requests and not ledger.snapshot()['operations']
    assert p.manifest_binding()['token_admission']['guarantee'] == 'service_capacity_bound'


@pytest.mark.parametrize('reason', ['stop', 'length', None])
def test_completion_reason_is_persisted_even_for_rejected_output(tmp_path, endpoint, reason):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response(finish_reason=reason))
    p = deepseek_provider(tmp_path, endpoint, ledger)
    if reason == 'stop':
        p('one')
    else:
        with pytest.raises(ValueError, match='completion'):
            p('one')
    receipt = json.loads(next(p.usage_dir.glob('*.json')).read_text())
    start = json.loads(next(p.calls_dir.glob('*.started.json')).read_text())
    assert receipt['finish_reason'] == reason
    assert receipt['token_admission'] == start['token_admission']
    assert receipt['token_admission']['input_allowance'] == 1027
    assert receipt['token_admission']['total_allowance'] == 17411
    assert start['provider']['token_admission']['guarantee'] == 'estimate_only'
    assert ledger.snapshot()['pending_calls'] == []


def test_input_estimate_breach_is_charged_invalidates_audit_and_blocks_restart(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.usage_audit import audit_usage
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    value = deepseek_response()
    value['usage'] = {'prompt_tokens': 2000, 'completion_tokens': 20, 'total_tokens': 2020}
    endpoint.replies.extend([value, deepseek_response()])
    p = deepseek_provider(tmp_path, endpoint, ledger)
    with pytest.raises(ValueError, match='admission'):
        p('one')
    assert take_usage(p) == 2020
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 4160
    audit = audit_usage(p.usage_dir, spending_ledger=ledger)
    assert audit['known_tokens'] == 2020 and audit['costs_complete']
    assert not audit['complete'] and not audit['unresolved_calls']
    with pytest.raises(ValueError, match='audit'):
        deepseek_provider(tmp_path, endpoint, ledger)
    with pytest.raises(ValueError):
        p('two')
    assert len(endpoint.requests) == 1


def test_changed_admission_policy_cannot_resume_old_receipts(tmp_path, endpoint):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response())
    deepseek_provider(tmp_path, endpoint, ledger)('one')
    with pytest.raises(ValueError, match='configuration'):
        deepseek_provider(tmp_path, endpoint, ledger, token_admission='model_capacity_v1')
    assert len(endpoint.requests) == 1


def test_prior_overrun_is_not_reclassified_as_ordinary_budget_exhaustion(tmp_path, endpoint):
    from core.llm import ProviderBudgetExhausted
    endpoint.replies.append(response(total=12))
    p = provider(tmp_path, endpoint, token_budget=10, max_completion_tokens=8)
    with pytest.raises(ValueError, match='exceeded'):
        p('one')
    with pytest.raises(ValueError) as caught:
        p('two')
    assert not isinstance(caught.value, ProviderBudgetExhausted)
    with pytest.raises(ValueError, match='exceeded'):
        provider(tmp_path, endpoint, token_budget=10, max_completion_tokens=8)
    assert len(endpoint.requests) == 1
