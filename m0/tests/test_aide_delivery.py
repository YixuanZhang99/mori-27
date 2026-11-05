"""Task 2 draft: a real sandbox failure must reach the selected repair call."""
import json

import pytest

from test_aide_recipe import PlanProvider, assembly
from test_configured_construction import build, records
from test_mle_composed import fixture_public, program, TEST_ANONYMIZATION_KEY, TASK
from zoo.mle_bench_lite.composed_domain import PublicTrainDomain
from zoo.mle_bench_lite.public_train import PublicTrainBundle


@pytest.mark.linux
def test_public_aide_debug_consumes_actual_sandbox_traceback_and_generated_plan(tmp_path):
    bundle = PublicTrainBundle(fixture_public(tmp_path / 'public'), tmp_path / 'inputs',
                              TASK, 7, anonymization_key=TEST_ANONYMIZATION_KEY)
    broken = "exec('def AIDE_BROKEN_MARKER(: pass')"
    fixed = program(bundle, cycle=0)

    class RepairProvider(PlanProvider):
        def __call__(self, prompt):
            super().__call__(prompt)
            return json.dumps({'artifact': broken if self.generation_index == 1 else fixed,
                               'hypothesis': f'ACTUAL_PLAN_MARKER_{self.generation_index}'})

    configured = assembly(debug_probability=1)
    configured['execution']['spec']['context_projection'] = ['memory']
    configured['frontier']['options']['direction'] = 'minimize'
    configured['admission'] = {'name': 'metric', 'options': {'direction': 'minimize'}}
    configured['memory'] = {'name': 'scoped', 'options': {
        'context_scope': 'run', 'levels': ['L1'], 'trust_floor': 'ungated',
        'include_negative': True, 'include_imported': False, 'top_k': 10, 'max_chars': 160000}}
    provider = RepairProvider()
    domain = PublicTrainDomain(bundle, tmp_path / 'candidates')
    fw = build(tmp_path / 'run', assembly=configured, provider=provider, domain=domain, generations=3)
    fw.evolve('Repair code using the public runtime feedback and return complete predictions.')
    evidence = records(fw, 'composed_evidence')
    failed, repaired = evidence[0], evidence[-1]
    assert failed['evidence']['eval_result']['status'] == 'failed_to_run'
    assert 'SyntaxError' in failed['evidence']['eval_result']['text_feedback']
    assert repaired['evidence']['eval_result']['status'] == 'ok'
    assert repaired['proposal']['candidate']['operator'] == 'debug'
    request = json.loads(provider.prompts[3])
    assert request['recipe']['parent_artifacts'] == [{
        'candidate_id': failed['proposal']['candidate']['id'], 'artifact': broken}]
    rendered = json.dumps(request['context'])
    assert 'SyntaxError' in rendered and 'AIDE_BROKEN_MARKER' in rendered
    assert 'ACTUAL_PLAN_MARKER_1' in rendered
    assert 'prediction_sha256' not in rendered and 'training_execution' not in rendered
    assert all(e.level == 'L1' and e.scope == 'run' and e.state == 'active'
               for e in fw._composed.memory.entries.values())
    assert len(fw._composed.memory.entries) == 4
    assert domain.training_invocations == 4
    before = provider.calls, domain.training_invocations
    assert fw.replay('Repair code using the public runtime feedback and return complete predictions.')['replay_certificate']['passed']
    assert (provider.calls, domain.training_invocations) == before


@pytest.mark.parametrize('mode', ['large', 'symlink'])
def test_public_failure_feedback_is_bounded_dev_only_and_does_not_follow_worker_symlinks(tmp_path, mode):
    import asyncio
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest
    bundle = PublicTrainBundle(fixture_public(tmp_path / 'public'), tmp_path / 'inputs',
                              TASK, 7, anonymization_key=TEST_ANONYMIZATION_KEY)
    secret = tmp_path / 'private.txt'
    secret.write_text('PRIVATE_LOG_TARGET_CANARY')
    if mode == 'large':
        code = "import sys\nsys.stderr.write('HEAD_MARKER' + 'x'*100000 + 'TAIL_MARKER')\nsys.exit(1)"
    else:
        code = ("from pathlib import Path\nimport sys\nPath('stderr.log').unlink()\n"
                f"Path('stderr.log').symlink_to({str(secret)!r})\nsys.exit(1)")
    domain = PublicTrainDomain(bundle, tmp_path / 'candidates')
    proposal = Proposal(Candidate('bounded-log'), code)
    dev = asyncio.run(domain.evaluate(proposal, EvalRequest('dev')))
    final = asyncio.run(domain.evaluate(proposal, EvalRequest('final_audit', split_id='final_audit')))
    assert final.text_feedback is None
    assert 'PRIVATE_LOG_TARGET_CANARY' not in dev.text_feedback
    assert len(dev.text_feedback) <= 4608
    assert domain.training_invocations == 1
    if mode == 'large':
        assert 'TAIL_MARKER' in dev.text_feedback and 'HEAD_MARKER' not in dev.text_feedback
    assert domain.manifest_binding['public_dev_feedback']['stderr_tail_bytes'] == 4096


def test_named_cli_offline_default_runs_real_sandbox_and_resumes(tmp_path, capsys):
    from zoo.mle_bench_lite.aide_runner import main
    args = ['--output', str(tmp_path / 'run'), '--max-nodes', '4']
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['mode'] == 'fixture' and first['run_state'] == 'completed'
    assert first['final_score'] is not None
    assert main([*args, '--resume']) == 0
    second = json.loads(capsys.readouterr().out)
    assert second['final_score'] == first['final_score']
    report = json.loads((tmp_path / 'run/method-report.json').read_text())
    assert report['training_invocations_this_process'] == 0
    assert report['replay_certificate']['passed']


@pytest.mark.parametrize('unknown', [False, True])
def test_named_governed_run_binds_control_source_costs_and_unknown_stop(tmp_path, monkeypatch, unknown):
    from test_governed_currency import migrated
    from zoo.mle_bench_lite import aide_runner
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    from zoo.mle_bench_lite.cny_budget import POLICY
    from zoo.mle_bench_lite.provider_protocol import parse_response
    from core.llm import UsageError
    # Simulated transport returns stdlib-only priors; retain real sandbox preflight
    # without requiring the separate live MLE environment in the core test suite.
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    preflight = SandboxRunner.preflight
    monkeypatch.setattr(SandboxRunner, 'preflight', lambda self, **kw: preflight(self))
    ledger = migrated(tmp_path)
    calls = []
    def reply(self, body):
        calls.append(json.loads(body))
        if unknown:
            self.last_usage = None
            raise UsageError('fixture unknown usage')
        response = json.dumps({'model': POLICY['model'], 'choices': [{'message': {'content': json.dumps({
            'artifact': aide_runner.FIXTURE_PROGRAM, 'hypothesis': 'Fit public priors.'})}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}).encode()
        result = parse_response(response, self.protocol_binding())
        self.last_usage = result.usage
        return result
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', reply)
    monkeypatch.setattr(aide_runner, 'source_identity', lambda: {'commit': 'a' * 40, 'dirty': False})
    public = fixture_public(tmp_path / 'public')
    report = aide_runner.run(output=tmp_path / 'run', public_root=public, task_id=TASK,
        max_nodes=4, ledger=ledger, api_key='fixture-unused')
    if unknown:
        assert report['run_state'] == 'execution_failed'
        assert len(calls) == 1 and report['submission'] is None
        assert ledger.snapshot()['pending_calls']
    else:
        assert report['run_state'] == 'completed', report['error_type']
        assert len(calls) == 5  # four main nodes and one isolated control
        assert report['independent_currency_receipts']['total_tokens'] == 90
        assert report['independent_physical_submission']['physical_tokens'] == 90
        assert report['replay_certificate']['external_calls'] == 0
        assert not ledger.snapshot()['pending_calls']
        resumed = aide_runner.run(output=tmp_path / 'run', public_root=public, task_id=TASK,
            max_nodes=4, ledger=ledger, api_key='fixture-unused', resume=True)
        assert resumed['run_state'] == 'completed', resumed['error_type']
        assert len(calls) == 5
        assert resumed['training_invocations_this_process'] == 0
        assert resumed['replay_certificate']['passed']
