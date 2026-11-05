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
