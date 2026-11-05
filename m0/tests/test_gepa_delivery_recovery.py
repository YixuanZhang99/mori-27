"""GEPA delivery regressions: real loopback accounting and durable boundaries."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from core.llm import UsageError
from core.loop import Framework, LoopConfig
from test_gepa_recipe import Fixture, TASK, dataset, run, rows
from test_governed_cny_framework import campaign_fixture
from zoo.gepa_gsm8k.runner import governed_setup
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge


class InjectedCrash(BaseException):
    pass


@pytest.fixture
def endpoint():
    state = SimpleNamespace(requests=[], fixture=Fixture())
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state.requests.append(request)
            content = state.fixture(request['messages'][0]['content'])
            body = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 3,
                'completion_tokens': 4, 'total_tokens': 7}, 'choices': [{'finish_reason': 'stop',
                'message': {'content': content}}]}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    state.url = f'http://127.0.0.1:{server.server_port}/v1'
    yield state
    server.shutdown(); server.server_close(); worker.join(timeout=5)


def build(path, endpoint, ledger, *, resume=False, output_tokens=4096):
    data = dataset()
    profile, registry, provider = governed_setup(data, seed=0, minibatch_size=2,
        max_proposals=0, ledger=ledger, api_key='fixture-only', base_url=endpoint.url,
        max_completion_tokens=output_tokens)
    return Framework.from_profile(profile, provider, data, LoopConfig(max_generations=0,
        total_budget=profile['budget']['options']['limits']['global']['token'], reeval_floor=0,
        resume_from_checkpoint=resume), str(path), component_registry=registry)


def test_resume_settles_saved_response_before_new_dispatch(tmp_path, endpoint, monkeypatch):
    ledger = campaign_fixture(tmp_path)
    original = CNYInvocationBridge._settle_response
    def crash_before_settlement(*_args):
        raise InjectedCrash()
    monkeypatch.setattr(CNYInvocationBridge, '_settle_response', crash_before_settlement)
    with pytest.raises(InjectedCrash):
        build(tmp_path / 'run', endpoint, ledger).evolve(TASK)
    assert len(endpoint.requests) == 1
    assert ledger.snapshot()['pending_calls']
    monkeypatch.setattr(CNYInvocationBridge, '_settle_response', original)
    restored = build(tmp_path / 'run', endpoint, ledger, resume=True)
    # A different run still cannot spend while this response is unsettled.
    with pytest.raises(UsageError, match='unresolved'):
        build(tmp_path / 'other', endpoint, ledger).evolve(TASK)
    assert len(endpoint.requests) == 1
    result = restored.evolve(TASK)
    assert result['reporting']['final_audit']['state'] == 'completed'
    assert len(endpoint.requests) == 8  # Original response adopted, not requested twice.
    snapshot = ledger.snapshot()
    assert not snapshot['pending_calls'] and snapshot['reserved_micro_cny'] == 0
    assert snapshot['settled_upper_bound_micro_cny'] == 8 * 38
    assert restored.replay(TASK)['replay_certificate']['passed']
    assert len(endpoint.requests) == 8 and ledger.snapshot() == snapshot


def test_supported_large_output_limit_reaches_main_and_final(tmp_path, endpoint):
    ledger = campaign_fixture(tmp_path)
    framework = build(tmp_path / 'run', endpoint, ledger, output_tokens=65536)
    result = framework.evolve(TASK)
    assert result['reporting']['final_audit']['state'] == 'completed'
    assert len(endpoint.requests) == 8
    assert all(request['max_tokens'] == 65536 for request in endpoint.requests)
    assert framework._composed.budget.state()['global']['used']['token'] == 8 * 7
    assert framework.replay(TASK)['replay_certificate']['passed']
    assert len(endpoint.requests) == 8


def test_evaluation_declares_aggregate_tokens_without_invented_input_split(tmp_path):
    framework, _, provider = run(tmp_path)
    evaluations = [r['evidence']['evidence']['eval_result']
                   for r in rows(framework, 'composed_physical_evidence')]
    assert {r['contract']['binding']['split_id'] for r in evaluations} == {'train', 'dev', 'final_audit'}
    assert all(r['contract']['token_accounting'] == 'total_only' for r in evaluations)
    assert all(r['cost']['tokens_out'] == 0 for r in evaluations)
    solver_calls = sum(json.loads(prompt).get('kind') == 'gsm8k_solver' for prompt in provider.prompts)
    assert sum(r['cost']['tokens_in'] for r in evaluations) == solver_calls


@pytest.mark.parametrize('boundary', ['frozen', 'settled', 'terminal'])
def test_interrupted_final_evaluation_adopts_original_evidence_and_cost(tmp_path, monkeypatch, boundary):
    from core.composition.recovery import ContinuationStore
    from core.x1.store import AppendOnlyStore
    baseline, _, baseline_provider = run(tmp_path / 'baseline')
    original = ContinuationStore.append
    frozen = False
    def interrupt_after_append(self, kind, payload):
        nonlocal frozen
        original(self, kind, payload)
        if kind == 'metric_final_frozen':
            frozen = True
        hit = ((boundary == 'frozen' and kind == 'metric_final_frozen') or
               (boundary == 'settled' and frozen and kind == 'hierarchical_budget'
                and payload['event'] == 'settle') or
               (boundary == 'terminal' and kind == 'metric_final_completed'))
        if hit:
            raise InjectedCrash()
    path = tmp_path / 'interrupted'
    first_provider = Fixture()
    with monkeypatch.context() as patch:
        patch.setattr(ContinuationStore, 'append', interrupt_after_append)
        with pytest.raises(InjectedCrash):
            run(path, provider=first_provider)
    before = list(AppendOnlyStore(path / 'x1.jsonl').read())
    frozen_rows = [r['payload'] for r in before if r['kind'] == 'metric_final_frozen']
    completed_before = [r['payload'] for r in before if r['kind'] == 'composed_physical_evidence'
                        and r['payload']['request']['split_id'] == 'final_audit']
    second_provider = Fixture()
    if boundary != 'frozen':
        second_provider.forbidden = True
    restored, result, _ = run(path, provider=second_provider, resume=True)
    assert result['reporting']['final_audit']['state'] == 'completed'
    assert rows(restored, 'metric_final_frozen') == frozen_rows
    assert len(rows(restored, 'metric_final_completed')) == 1
    if completed_before:
        assert [r for r in rows(restored, 'composed_physical_evidence')
                if r['request']['split_id'] == 'final_audit'] == completed_before
    assert len(first_provider.prompts) + len(second_provider.prompts) == len(baseline_provider.prompts)
    assert restored._composed.budget.state()['global']['used'] == baseline._composed.budget.state()['global']['used']
    second_provider.forbidden = True
    assert restored.replay(TASK)['replay_certificate']['passed']
