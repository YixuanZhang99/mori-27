"""Offline public MLE agent test using a real loopback transport and isolated currency fixture."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_mle_composed import fixture_public, program, TrustedFixtureRunner, TASK, TEST_ANONYMIZATION_KEY
from zoo.mle_bench_lite.public_train import PublicTrainBundle
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_agent import run_governed_agent


@pytest.mark.parametrize("variant", ["baseline", "full"])
@pytest.mark.parametrize("interrupted,iterations", [(False, 0), (True, 0), (False, 1), (False, 3)])
def test_m7_agent_materializes_frozen_predictions_and_accounts_controls(tmp_path, monkeypatch, interrupted, variant, iterations):
    workspace = tmp_path / 'run/workspace'
    fixture_public(workspace / 'data')
    preview = PublicTrainBundle(workspace / 'data', tmp_path / 'preview', TASK, 1,
                                anonymization_key=TEST_ANONYMIZATION_KEY)
    key_path = tmp_path / 'key'
    key_path.write_bytes(TEST_ANONYMIZATION_KEY)
    key_path.chmod(0o600)
    ledger = CampaignBudget.create(tmp_path / 'fixture.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            request = json.loads(req['messages'][0]['content'])
            calls.append(request)
            content = json.dumps({'artifact': program(preview), 'hypothesis': request['hypothesis']})
            response = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 3,
                'completion_tokens': 4, 'total_tokens': 7}, 'choices': [{'finish_reason': 'stop',
                'message': {'content': content}}]}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(response)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        kwargs = dict(workspace=workspace, task_id=TASK, model='deepseek-flash',
            api_base=f'http://127.0.0.1:{server.server_port}/v1', token_budget=3_000_000,
            seed=1, iterations=iterations, variant=variant, max_completion_tokens=4,
            runner=TrustedFixtureRunner(), anonymization_key_path=key_path,
            spending_ledger_path=ledger.path, api_key='fixture-only')
        if interrupted:
            from core.composition.recovery import ContinuationStore
            from test_materialization_recovery import Crash
            original = ContinuationStore._write
            def cut(self, row):
                original(self, row)
                if row['kind'] == 'governed_evaluation_completed':
                    raise Crash('evaluation terminal')
            monkeypatch.setattr(ContinuationStore, '_write', cut)
            with pytest.raises(Crash):
                run_governed_agent(**kwargs)
            monkeypatch.setattr(ContinuationStore, '_write', original)
            kwargs['resume'] = True
        summary = run_governed_agent(**kwargs)
        from zoo.mle_bench_lite.composed_agent import build_governed_profile
        assert summary['profile'] == build_governed_profile(variant=variant, token_budget=3_000_000, seed=1,
            iterations=iterations, max_completion_tokens=4)
        assert summary['runtime'] == 'composed-v9-m7-governed-external'
        assert summary['submission_materialized'] and (workspace / 'submission.csv').is_file()
        assert len(calls) == 2 + iterations and summary['token_usage']['total_tokens'] == 7 * (2 + iterations)
        if iterations == 3:
            assert ('crossover' if variant == 'full' else 'reflective') in [call['recipe']['kind'] for call in calls]
        assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 38 * (2 + iterations)
        assert summary['details']['training_invocations'] == 1 + iterations
        assert summary['details']['controls_completed'] == 1
        assert summary['recorded_replay']['passed'] and summary['recorded_replay']['external_calls'] == 0
        from zoo.mle_bench_lite.m7_pilot_audit import audit_currency_receipts
        audit = audit_currency_receipts(workspace.parent / 'agent_artifacts/composed', ledger, expected_model='deepseek-flash')
        assert audit['total_tokens'] == summary['token_usage']['total_tokens']
        assert audit['construction']['provider_calls'] == 2 + iterations
        assert any(link['candidate_id'] == summary['selected_candidate_id'] and link['lane'] == 'main'
                   for link in audit['construction']['artifact_links'])
        assert audit['settled_micro_cny'] == 38 * (2 + iterations)
        response_file = next((workspace.parent / 'agent_artifacts/composed/.governed-cny').glob('*.response.json'))
        original_response = response_file.read_text()
        response_file.write_text(original_response.replace('deepseek-flash', 'other-model'))
        with pytest.raises(ValueError):
            audit_currency_receipts(workspace.parent / 'agent_artifacts/composed', ledger, expected_model='deepseek-flash')
        # Even a coherently rehashed local envelope must agree with the separately
        # anchored campaign journal; its usage cannot be silently rewritten.
        from core.x1.checkpoint import payload_digest
        forged = json.loads(original_response)
        forged['payload']['usage']['prompt_tokens'] += 1
        forged['payload']['usage']['total_tokens'] += 1
        forged['sha256'] = payload_digest(forged['payload'])
        response_file.write_text(json.dumps(forged))
        with pytest.raises(ValueError, match='usage differs'):
            audit_currency_receipts(workspace.parent / 'agent_artifacts/composed', ledger, expected_model='deepseek-flash')
        response_file.write_text(original_response)
        transcript = workspace.parent / 'agent_artifacts/composed/x1.jsonl'
        rows = [json.loads(line) for line in transcript.read_text().splitlines()]
        materialized = next(row for row in rows if row['kind'] == 'materialization_completed')
        materialized['payload']['construction_result']['artifact'] += '\n# altered'
        transcript.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with pytest.raises(ValueError):
            audit_currency_receipts(workspace.parent / 'agent_artifacts/composed', ledger, expected_model='deepseek-flash')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_m7_rejects_small_budget_before_provider_or_ledger(tmp_path):
    with pytest.raises(ValueError, match='hard'):
        run_governed_agent(workspace=tmp_path / 'run/workspace', task_id=TASK, model='deepseek-flash',
            api_base='http://127.0.0.1:1/v1', token_budget=60_000, seed=1, iterations=0,
            variant='baseline', max_completion_tokens=4, spending_ledger_path=tmp_path / 'missing',
            api_key='fixture-only')


@pytest.mark.parametrize('location', ['workspace', 'artifacts'])
def test_m7_rejects_private_ledger_inside_candidate_or_artifacts(tmp_path, location):
    workspace = tmp_path / 'run/workspace'
    ledger = (workspace if location == 'workspace' else workspace.parent / 'agent_artifacts') / 'ledger.db'
    with pytest.raises(ValueError, match='ledger must stay outside'):
        run_governed_agent(workspace=workspace, task_id=TASK, model='deepseek-flash',
            api_base='http://127.0.0.1:1/v1', token_budget=3_000_000, seed=1, iterations=0,
            variant='baseline', max_completion_tokens=4, spending_ledger_path=ledger,
            runner=TrustedFixtureRunner(), api_key='fixture-only')
    assert not ledger.exists()


def test_frozen_m7_profile_enforces_real_hard_call_bounds():
    from zoo.mle_bench_lite.composed_agent import build_governed_profile
    from zoo.mle_bench_lite.cny_budget import POLICY
    bound = POLICY['context_tokens'] + 16384
    with pytest.raises(ValueError, match='hard'):
        build_governed_profile(variant='full', token_budget=60000, seed=1, iterations=3,
                               max_completion_tokens=16384)
    profile = build_governed_profile(variant='full', token_budget=2 * bound, seed=1, iterations=3,
                                     max_completion_tokens=16384)
    assert profile['execution']['constructor']['options']['max_attempts'] == 1
    assert profile['budget']['options']['operation_reservations']['operator']['token'] == bound
    assert profile['governance']['controls']['reservations']['operator']['token'] == bound
    assert profile['policy']['name'] == 'population'
    assert any(operator['name'] == 'crossover' for operator in profile['operators'])
