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
