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
