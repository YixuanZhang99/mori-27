"""Transport/protocol tests use real loopback HTTP, never external services."""
import copy
import hashlib
import importlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.llm import UsageError, take_usage
from zoo.mle_bench_lite.cny_budget import POLICY


def protocol():
    return importlib.import_module('zoo.mle_bench_lite.provider_protocol')


def binding(**changes):
    return {'requested_model': 'deepseek-flash', 'request_format': 'deepseek',
            'max_completion_tokens': 16, 'input_capacity': 1048576,
            'temperature': 0.0, **changes}


def reply(**changes):
    return {'model': 'deepseek-flash',
            'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
            'choices': [{'finish_reason': 'stop', 'message': {'content': 'answer'}}], **changes}


@pytest.fixture
def local_endpoint():
    class State:
        responses = []
        requests = []
    state = State()
    state.responses, state.requests = [], []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state.requests.append(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers['Authorization'] == 'Bearer fixture-only-secret'
            value = state.responses.pop(0)
            if value == 'disconnect':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if value == 'redirect':
                self.send_response(307)
                self.send_header('Location', '/unsafe')
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(value if isinstance(value, bytes) else json.dumps(value).encode())
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.url = f'http://127.0.0.1:{server.server_port}/v1'
    yield state
    server.shutdown(); server.server_close(); worker.join(timeout=5)


def provider(endpoint, **options):
    cls = importlib.import_module('zoo.mle_bench_lite.governed_provider').GovernedCNYProvider
    campaign = {**POLICY, 'campaign_id': 'fixture-campaign', 'limit_micro_cny': 200000000,
                'policy_sha256': 'a' * 64}
    return cls('deepseek-flash', endpoint.url, campaign_binding=campaign,
               max_completion_tokens=16, api_key='fixture-only-secret', **options)


def test_deepseek_wire_protocol_applies_only_supported_fields():
    raw = protocol().build_request('hello', binding())
    assert raw == (b'{"max_tokens":16,"messages":[{"content":"hello","role":"user"}],'
                   b'"model":"deepseek-flash","reasoning_effort":"high","stream":false,'
                   b'"thinking":{"type":"enabled"}}')


def test_openevolve_two_role_transport_uses_original_bound_argument(local_endpoint):
    from test_openevolve_governed_transport import prompt
    local_endpoint.responses.append(reply())
    p = provider(local_endpoint, message_mode='openevolve_v1')
    body = p.prepare_request(prompt())
    result = p.perform_request(body, prompt=prompt())
    assert result.result == 'answer' and result.usage['total_tokens'] == 7
    wire = json.loads(local_endpoint.requests[0])
    assert wire['messages'][0] == {'role': 'system', 'content': 'vendor system'}
    assert wire['messages'][1]['content'].startswith('vendor user')


def test_legacy_openai_wire_protocol_is_preserved():
    assert protocol().build_request('hello', binding(request_format='openai', temperature=0.25)) == (
        b'{"max_completion_tokens":16,"messages":[{"content":"hello","role":"user"}],'
        b'"model":"deepseek-flash","temperature":0.25}')


@pytest.mark.parametrize('changes,reason', [
    ({'model': 'other-model'}, 'model_mismatch'),
    ({'model': None}, 'model_mismatch'),
    ({'choices': []}, 'incomplete_output'),
    ({'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]}, 'incomplete_output'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'content': ''}}]}, 'invalid_content'),
    ({'usage': {'total_tokens': 7}}, 'invalid_usage_details'),
    ({'usage': {'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 7}}, 'invalid_usage_details'),
    ({'usage': {'prompt_tokens': 3, 'completion_tokens': 17, 'total_tokens': 20}}, 'output_bound_exceeded'),
    ({'usage': {'prompt_tokens': 1048577, 'completion_tokens': 4, 'total_tokens': 1048581}}, 'input_bound_exceeded'),
])
def test_known_usage_survives_contract_failure(changes, reason):
    raw = json.dumps(reply(**changes)).encode()
    parsed = protocol().parse_response(raw, binding())
    assert parsed.integrity_reason == reason
    assert parsed.usage['total_tokens'] == changes.get('usage', {}).get('total_tokens', 7)
    assert parsed.response_sha256 == hashlib.sha256(raw).hexdigest()
    assert parsed.result is None
    assert parsed.to_dict()['integrity_reason'] == reason


@pytest.mark.parametrize('raw,reason', [(b'not json', 'invalid_json'), (b'[]', 'invalid_response'),
                                       (json.dumps(reply(usage=None)).encode(), 'invalid_usage')])
def test_unknown_usage_is_not_fabricated(raw, reason):
    result = protocol().parse_response(raw, binding())
    assert result.usage is None
    assert result.integrity_reason == reason
    assert result.result is None


def test_parsed_known_outcome_is_detached_and_retains_replay_content():
    outcome = protocol().parse_response(json.dumps(reply()).encode(), binding())
    assert outcome.result == 'answer'
    usage = outcome.usage
    usage['total_tokens'] = 0
    assert outcome.usage['total_tokens'] == 7
    record = outcome.to_dict()
    record['usage']['total_tokens'] = 100
    assert outcome.to_dict()['usage']['total_tokens'] == 7


def test_fresh_sessions_have_separate_usage_and_frozen_applied_contract(local_endpoint):
    first, second = provider(local_endpoint), provider(local_endpoint)
    local_endpoint.responses.append(reply())
    result = first.perform_request(first.prepare_request('private input'))
    assert result.result == 'answer'
    assert take_usage(first) == 7
    assert take_usage(first) == 0
    assert take_usage(second) == 0
    declared = first.governance_binding()
    assert declared['schema_version'] == 2
    assert declared['call_bound'] == {'kind': 'hard', 'units': {'token': 1048592}}
    assert declared['phase_call_limits'] == {'operator': 1, 'evaluation': 0}
    assert declared['external_currency'] == {'schema_version': 1, 'bridge': 'cny_invocation_v1'}
    assert 'temperature' not in declared['sampling']['parameters']
    assert 'seed' not in declared['sampling']['parameters']
    evidence = json.dumps([first.manifest_binding(), declared, result.to_dict()])
    assert 'fixture-only-secret' not in evidence
    assert 'private input' not in evidence
    assert 'Authorization' not in evidence
    declared['phase_call_limits']['operator'] = 100
    assert first.governance_binding()['phase_call_limits']['operator'] == 1


def test_unbound_call_refuses_before_http(local_endpoint):
    p = provider(local_endpoint)
    with pytest.raises(UsageError, match='bound|bridge'):
        p('hello')
    assert local_endpoint.requests == []
    assert take_usage(p) == 0


def test_estimate_only_contract_is_refused_before_http(local_endpoint):
    with pytest.raises(ValueError, match='capacity|hard'):
        provider(local_endpoint, token_admission='estimated_utf8_v1')
    assert local_endpoint.requests == []


@pytest.mark.parametrize('change', ['output', 'model', 'messages', 'extra'])
def test_tampered_wire_payload_is_refused_before_http(local_endpoint, change):
    p = provider(local_endpoint)
    body = json.loads(p.prepare_request('hello'))
    if change == 'output':
        body['max_tokens'] = 100
    elif change == 'model':
        body['model'] = 'other'
    elif change == 'messages':
        body['messages'].append({'role': 'assistant', 'content': 'prior control'})
    else:
        body['seed'] = 123
    with pytest.raises(ValueError, match='wire|request|protocol'):
        p.perform_request(json.dumps(body, sort_keys=True, separators=(',', ':')).encode())
    assert local_endpoint.requests == []
    assert take_usage(p) == 0


@pytest.mark.parametrize('failure', ['disconnect', 'redirect'])
def test_ambiguous_http_is_never_retried_or_reclassified_zero(local_endpoint, failure):
    p = provider(local_endpoint)
    local_endpoint.responses.append(failure)
    with pytest.raises(UsageError, match='unknown usage'):
        p.perform_request(p.prepare_request('hello'))
    assert len(local_endpoint.requests) == 1
    assert p.last_usage is None
    with pytest.raises(UsageError, match='unresolved'):
        p.perform_request(p.prepare_request('another request'))
    assert len(local_endpoint.requests) == 1


def test_known_failure_preserves_meter_then_blocks_session(local_endpoint):
    p = provider(local_endpoint)
    local_endpoint.responses.append(reply(model='wrong-model'))
    result = p.perform_request(p.prepare_request('hello'))
    assert result.integrity_reason == 'model_mismatch'
    assert take_usage(p) == 7
    with pytest.raises(UsageError, match='integrity|unresolved'):
        p.perform_request(p.prepare_request('again'))
    assert len(local_endpoint.requests) == 1


def test_pre_dispatch_refusal_resets_new_call_usage_to_known_zero(local_endpoint):
    p = provider(local_endpoint)
    # The core meter resets raw last_usage before entering the bridge call.
    p.last_usage = None
    with pytest.raises(ValueError, match='wire|request|protocol'):
        p.perform_request(b'{}')
    assert p.last_usage == {'total_tokens': 0}
    assert local_endpoint.requests == []


def test_campaign_binding_cannot_smuggle_credentials_into_manifest(local_endpoint):
    cls = importlib.import_module('zoo.mle_bench_lite.governed_provider').GovernedCNYProvider
    campaign = {**POLICY, 'campaign_id': 'fixture-campaign', 'limit_micro_cny': 200000000,
                'policy_sha256': 'a' * 64, 'Authorization': 'Bearer fixture-only-secret'}
    with pytest.raises(ValueError, match='campaign'):
        cls('deepseek-flash', local_endpoint.url, campaign_binding=campaign,
            max_completion_tokens=16, api_key='fixture-only-secret')
    assert local_endpoint.requests == []


def test_remote_sampling_is_explicitly_unverified(local_endpoint):
    p = provider(local_endpoint)
    assert p.governance_binding()['sampling']['method'] == 'supplier_unverified'
    assert p.manifest_binding()['seed_applied'] is False
    assert p.manifest_binding()['temperature_applied'] is False
    assert p.manifest_binding()['immutable_snapshot_verified'] is False


@pytest.mark.parametrize('choices', [
    [{'finish_reason': 'stop', 'message': {'content': ''}}],
    [{'finish_reason': 'length', 'message': {'content': 'partial'}}],
])
def test_known_content_failure_does_not_poison_later_distinct_invocation(local_endpoint, choices):
    p = provider(local_endpoint)
    local_endpoint.responses.extend([reply(choices=choices), reply()])
    failed = p.perform_request(p.prepare_request('first invocation'))
    assert failed.integrity_reason in {'invalid_content', 'incomplete_output'}
    assert take_usage(p) == 7
    later = p.perform_request(p.prepare_request('different admitted invocation'))
    assert later.result == 'answer'
    assert take_usage(p) == 7
    assert len(local_endpoint.requests) == 2
