"""Reference-stage execution must consume the original physical budget."""
import hashlib

import pytest

from core.composition.budget import HierarchicalBudget
from test_governed_budget import STAMP, config, governance, plan


def stage_budget(tmp_path):
    from core.x1.store import AppendOnlyStore
    options = config()
    options['reservation'] = {'token': 0, 'node': 0, 'eval_count': 1}
    budget = HierarchicalBudget(options, STAMP, AppendOnlyStore(tmp_path / 'events.jsonl'), governance=governance())
    budget.protect_controls(plan())
    return budget


def fake_result(program, stage, score=.6, status='ok'):
    import json
    from zoo.circle_packing.geometry import validate_geometry
    radius = .04 if score < .5 else .07
    geometry = {'centers': [[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)],
                'radii': [radius] * 26}
    geometry_ref = 'sha256:' + hashlib.sha256(json.dumps(geometry, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'stage': stage, 'status': status, 'wall_seconds': 1.0,
            'program_ref': 'sha256:' + hashlib.sha256(program.encode()).hexdigest(),
            'evaluator_ref': 'sha256:' + __import__('zoo.circle_packing.stage', fromlist=['EVALUATOR_SHA256']).EVALUATOR_SHA256,
            **({'metrics': validate_geometry(geometry), 'geometry': geometry, 'geometry_ref': geometry_ref}
               if status == 'ok' else {})}


def test_stage_two_requires_qualifying_original_stage_and_charges_both(tmp_path, monkeypatch):
    from zoo.circle_packing.host_physical import HostStageAdmission
    import zoo.circle_packing.host_physical as module
    budget = stage_budget(tmp_path)
    monkeypatch.setattr(module, 'run_stage', lambda program, *, stage, **kwargs: fake_result(program, stage))
    stage = HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox')
    stage.execute('a' * 32, 'program', stage=1)
    result = stage.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)
    assert result['status'] == 'ok' and budget.audit_governance()['physical_totals']['eval_count'] == 2
    assert stage.audit()['stage_calls'] == 2
    with pytest.raises(ValueError):
        stage.execute('c' * 32, 'program', stage=2, prior_id='a' * 32)


def test_below_threshold_or_wrong_program_never_starts_stage_two(tmp_path, monkeypatch):
    from zoo.circle_packing.host_physical import HostStageAdmission
    import zoo.circle_packing.host_physical as module
    budget = stage_budget(tmp_path)
    monkeypatch.setattr(module, 'run_stage', lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    stage = HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox')
    stage.execute('a' * 32, 'program', stage=1)
    for program in ('program', 'different'):
        with pytest.raises(ValueError):
            stage.execute('b' * 32, program, stage=2, prior_id='a' * 32)
    assert budget.audit_governance()['physical_totals']['eval_count'] == 1


def test_rehashed_forged_score_cannot_authorize_stage_two(tmp_path, monkeypatch):
    import copy
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.host_physical import HostStageAdmission
    import zoo.circle_packing.host_physical as module
    budget = stage_budget(tmp_path)
    monkeypatch.setattr(module, 'run_stage', lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    host = HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox')
    host.execute('a' * 32, 'program', stage=1)
    original = budget.store.read
    def forged(kind=None):
        rows = copy.deepcopy(list(original(kind)))
        for row in rows:
            if row['kind'] == 'host_stage_completed':
                result = row['payload']['result']
                result['metrics']['combined_score'] = .8
                row['payload']['result_ref'] = 'sha256:' + payload_digest(result)
        return iter(rows)
    monkeypatch.setattr(budget.store, 'read', forged)
    with pytest.raises(ValueError):
        host.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)
    with pytest.raises(ValueError):
        host.audit()


def test_underreserved_stage_is_refused_before_execution(tmp_path, monkeypatch):
    from core.x1.store import AppendOnlyStore
    from zoo.circle_packing.host_physical import HostStageAdmission
    import zoo.circle_packing.host_physical as module
    options = config()
    options['reservation'] = {'token': 0, 'node': 0, 'eval_count': 0}
    budget = HierarchicalBudget(options, STAMP, AppendOnlyStore(tmp_path / 'events.jsonl'), governance=governance())
    budget.protect_controls(plan())
    monkeypatch.setattr(module, 'run_stage', lambda *args, **kwargs: pytest.fail('stage was executed'))
    with pytest.raises(ValueError, match='reservation'):
        HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox').execute('a' * 32, 'program', stage=1)
    assert not budget.state()['open_intents']


def test_stage_failure_cost_is_charged_and_unknown_exception_blocks_restored_budget(tmp_path, monkeypatch):
    from zoo.circle_packing.host_physical import HostStageAdmission
    import zoo.circle_packing.host_physical as module
    budget = stage_budget(tmp_path)
    monkeypatch.setattr(module, 'run_stage', lambda program, *, stage, **kwargs: fake_result(program, stage, status='timeout'))
    host = HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox')
    assert host.execute('a' * 32, 'program', stage=1)['status'] == 'timeout'
    assert budget.audit_governance()['physical_totals']['eval_count'] == 1
    def crash(*args, **kwargs):
        raise RuntimeError('unknown outcome')
    monkeypatch.setattr(module, 'run_stage', crash)
    with pytest.raises(RuntimeError):
        host.execute('b' * 32, 'program', stage=1)
    restored = HierarchicalBudget(budget.options, budget.stamp, budget.store, governance=budget._governed.config)
    restored.restore_from_journal()
    with pytest.raises(ValueError):
        HostStageAdmission(restored, runner=object(), workspace=tmp_path / 'sandbox').execute('c' * 32, 'program', stage=1)


def test_real_sandbox_stages_are_charged_to_physical_budget(tmp_path):
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from test_circle_packing_sandbox import SOURCE, GRID
    budget = stage_budget(tmp_path)
    host = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'sandbox')
    seed = host.execute('a' * 32, SOURCE.read_text(), stage=1)
    assert seed['status'] == 'ok' and seed['metrics']['combined_score'] < .5
    host.execute('b' * 32, GRID, stage=1)
    grid = host.execute('c' * 32, GRID, stage=2, prior_id='b' * 32)
    assert grid['status'] == 'ok' and grid['metrics']['sum_radii'] == pytest.approx(1.82)
    assert budget.audit_governance()['physical_totals']['eval_count'] == 3
