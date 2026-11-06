"""Execute the pinned circle evaluator under the real Linux sandbox."""
from pathlib import Path

import pytest

from zoo.mle_bench_lite.composed_domain import SandboxRunner

SOURCE = Path(__file__).resolve().parents[1] / 'vendor/openevolve/examples/circle_packing/initial_program.py'
GRID = '''import numpy as np\ndef run_packing():\n    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n'''


def test_real_seed_and_grid_execute_pinned_stages(tmp_path):
    from zoo.circle_packing.stage import run_stage
    runner = SandboxRunner()
    seed = run_stage(SOURCE.read_text(), stage=1, runner=runner, workspace=tmp_path, timeout=60)
    assert seed['status'] == 'ok'
    assert seed['metrics']['combined_score'] == pytest.approx(.36423689449571406)
    assert seed['metrics']['combined_score'] < .5
    one = run_stage(GRID, stage=1, runner=runner, workspace=tmp_path, timeout=60)
    two = run_stage(GRID, stage=2, runner=runner, workspace=tmp_path, timeout=60)
    assert one['status'] == two['status'] == 'ok'
    assert one['metrics']['sum_radii'] == pytest.approx(1.82)
    assert one['metrics']['combined_score'] > .5
    assert two['metrics']['sum_radii'] == pytest.approx(1.82)
    assert all(item['wall_seconds'] > 0 for item in (seed, one, two))


def test_candidate_precreating_output_symlink_cannot_forge_geometry(tmp_path):
    from zoo.circle_packing.stage import run_stage
    attack = "import os\nos.symlink('/etc/passwd', 'geometry.json')\n" + GRID
    result = run_stage(attack, stage=1, runner=SandboxRunner(), workspace=tmp_path, timeout=60)
    assert result['status'] == 'failed_to_run'
    assert result.get('metrics') is None


def test_stage_timeout_is_physically_measured(tmp_path):
    from zoo.circle_packing.stage import run_stage
    slow = 'import time\ndef run_packing():\n    time.sleep(10)\n'
    result = run_stage(slow, stage=1, runner=SandboxRunner(), workspace=tmp_path, timeout=.3)
    assert result['status'] == 'timeout'
    assert result['wall_seconds'] > 0
    assert 'metrics' not in result


def test_candidate_cannot_modify_readonly_evaluator(tmp_path):
    from zoo.circle_packing.stage import run_stage
    attack = ("try:\n    open('data/evaluator.py', 'w').write('forged')\n"
              "except OSError:\n    pass\n" + GRID)
    result = run_stage(attack, stage=1, runner=SandboxRunner(), workspace=tmp_path, timeout=60)
    assert result['status'] == 'ok'
    assert result['metrics']['sum_radii'] == pytest.approx(1.82)


def test_real_cascade_stops_after_seed_and_runs_both_grid_stages(tmp_path):
    from zoo.circle_packing.stage import run_cascade
    runner = SandboxRunner()
    seed = run_cascade(SOURCE.read_text(), runner=runner, workspace=tmp_path, timeout=60)
    assert seed['status'] == 'ok' and [row['stage'] for row in seed['stages']] == [1]
    assert seed['eval_count'] == 1 and seed['metrics']['combined_score'] < .5
    grid = run_cascade(GRID, runner=runner, workspace=tmp_path, timeout=60)
    assert grid['status'] == 'ok' and [row['stage'] for row in grid['stages']] == [1, 2]
    assert grid['eval_count'] == 2 and grid['metrics']['sum_radii'] == pytest.approx(1.82)
    assert grid['wall_seconds'] == pytest.approx(sum(row['wall_seconds'] for row in grid['stages']))


def test_cascade_accounts_stage_two_timeout_and_does_not_claim_valid_result(monkeypatch, tmp_path):
    import zoo.circle_packing.stage as module
    calls = []
    def stage(program, *, stage, runner, workspace, timeout):
        calls.append(stage)
        if stage == 1:
            return {'stage': 1, 'status': 'ok', 'wall_seconds': 1.5,
                    'metrics': {'combined_score': .6}, 'geometry': {}}
        return {'stage': 2, 'status': 'timeout', 'wall_seconds': 2.5}
    monkeypatch.setattr(module, 'run_stage', stage)
    result = module.run_cascade('fixed', runner=object(), workspace=tmp_path, timeout=60)
    assert calls == [1, 2] and result['status'] == 'timeout'
    assert result['eval_count'] == 2 and result['wall_seconds'] == 4
    assert 'metrics' not in result


def test_domain_freezes_geometry_and_final_validation_never_reruns_candidate(tmp_path):
    import asyncio
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest, EvalStatus
    from zoo.circle_packing.domain import CirclePackingDomain
    runner = SandboxRunner()
    calls = []
    execute = runner.execute
    def count(*args, **kwargs):
        calls.append(1)
        return execute(*args, **kwargs)
    runner.execute = count
    domain = CirclePackingDomain(tmp_path, runner=runner)
    proposal = Proposal(Candidate('circle-seed', hypothesis='fixed'), SOURCE.read_text())
    dev = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
    assert dev.status == EvalStatus.OK and dev.cost.eval_count == 1 and len(calls) == 1
    assert dev.metrics['dev/score'] == pytest.approx(.36423689449571406)
    final = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='final_audit', split_id='final_audit')))
    assert final.status == EvalStatus.OK and len(calls) == 1
    assert final.metrics['test/score'] == pytest.approx(dev.metrics['dev/score'])
    assert final.contract.private.data['geometry_ref'] == dev.contract.private.data['geometry_ref']
    changed = Proposal(proposal.candidate, proposal.artifact + '\n# altered')
    with pytest.raises(ValueError, match='identity'):
        asyncio.run(domain.evaluate(changed, EvalRequest(fidelity='final_audit', split_id='final_audit')))


def test_final_validation_rejects_geometry_rejected_by_pinned_upstream(tmp_path, monkeypatch):
    import asyncio
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest, EvalStatus
    from zoo.circle_packing.domain import CirclePackingDomain
    domain = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    proposal = Proposal(Candidate('circle-seed', hypothesis='fixed'), SOURCE.read_text())
    dev = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
    assert dev.status == EvalStatus.OK
    monkeypatch.setattr('zoo.circle_packing.reference_final._validate_with_pinned_upstream', lambda _: False)
    with pytest.raises(ValueError, match='upstream'):
        asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='final_audit', split_id='final_audit')))


def test_domain_restore_requires_original_evidence_and_rejects_tampering(tmp_path):
    import asyncio
    from dataclasses import asdict
    from core.composition.contracts import Proposal
    from core.composition.evaluation import encode_evidence
    from core.executor.types import Candidate, EvalRequest, EvidenceRecord
    from zoo.circle_packing.domain import CirclePackingDomain
    proposal = Proposal(Candidate('original', hypothesis='fixed'), SOURCE.read_text())
    domain = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    result = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
    evidence = encode_evidence(EvidenceRecord('original', result))['evidence']
    rows = [{'payload': {'proposal': asdict(proposal), 'evidence': evidence}}]
    state = domain.checkpoint_state()
    resumed = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    resumed.restore_state(state)
    final_request = EvalRequest(fidelity='final_audit', split_id='final_audit')
    with pytest.raises(ValueError, match='evidence'):
        asyncio.run(resumed.evaluate(proposal, final_request))
    resumed.restore_evidence(rows)
    final = asyncio.run(resumed.evaluate(proposal, final_request))
    assert final.metrics['test/score'] == pytest.approx(result.metrics['dev/score'])
    forged = [{'payload': {'proposal': asdict(proposal), 'evidence': encode_evidence(EvidenceRecord('original', result))['evidence']}}]
    forged[0]['payload']['evidence']['eval_result']['contract']['private']['data']['geometry_ref'] = 'sha256:' + '0' * 64
    other = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    other.restore_state(state)
    with pytest.raises(ValueError):
        other.restore_evidence(forged)


def test_rehashed_forged_checkpoint_cannot_replace_original_geometry(tmp_path):
    import asyncio
    import copy
    from dataclasses import asdict
    from core.composition.contracts import Proposal
    from core.composition.evaluation import encode_evidence
    from core.executor.types import Candidate, EvalRequest, EvidenceRecord
    from zoo.circle_packing.domain import CirclePackingDomain, _ref
    from zoo.circle_packing.geometry import validate_geometry
    proposal = Proposal(Candidate('grid', hypothesis='fixed'), GRID)
    domain = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    result = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
    rows = [{'payload': {'proposal': asdict(proposal),
                        'evidence': encode_evidence(EvidenceRecord('grid', result))['evidence']}}]
    forged = copy.deepcopy(domain.checkpoint_state())
    record = forged['entries']['grid']
    geometry = copy.deepcopy(record['geometry'])
    geometry['radii'] = [r * .9 for r in geometry['radii']]
    changed_metrics = validate_geometry(geometry)
    record.update(geometry=geometry, geometry_ref=_ref(geometry), metrics=changed_metrics)
    record['stages'][-1].update(geometry=geometry, geometry_ref=_ref(geometry), metrics=changed_metrics)
    restored = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    restored.restore_state(forged)
    with pytest.raises(ValueError, match='original evidence'):
        restored.restore_evidence(rows)
    with pytest.raises(ValueError, match='evidence'):
        asyncio.run(restored.evaluate(proposal, EvalRequest(fidelity='final_audit', split_id='final_audit')))


def test_failed_stage_is_measured_and_cannot_be_finalized(tmp_path):
    import asyncio
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest, EvalStatus
    from zoo.circle_packing.domain import CirclePackingDomain
    proposal = Proposal(Candidate('bad', hypothesis='fixed'), 'def run_packing():\n    raise RuntimeError("bad")\n')
    domain = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    result = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
    assert result.status == EvalStatus.FAILED_TO_RUN
    assert result.metrics == {} and result.cost.eval_count == 1 and result.cost.wall_seconds > 0
    with pytest.raises(ValueError, match='no frozen geometry'):
        asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='final_audit', split_id='final_audit')))


def test_candidate_pickle_cannot_execute_code_inside_evaluator(tmp_path):
    from zoo.circle_packing.stage import run_stage
    attack = '''import os
import numpy as np
class Exploit:
    def __reduce__(self):
        return os.system, ("touch evaluator_compromised",)
def run_packing():
    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])
    return c, np.full(26, .07), Exploit()
'''
    result = run_stage(attack, stage=1, runner=SandboxRunner(), workspace=tmp_path, timeout=60)
    assert result['status'] == 'failed_to_run'
    assert 'metrics' not in result
