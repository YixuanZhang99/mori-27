"""The reference fixture must execute the pinned host worker, not a substitute loop."""
import json
import os
import subprocess
import sys

import pytest


def test_offline_reference_runs_actual_host_worker_without_credentials(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if 'API_KEY' not in key and not key.startswith('KAGGLE_')}
    env['OPENAI_API_KEY'] = 'fixture-sentinel-secret-not-for-network'
    env['UNRELATED_PRIVATE_SECRET'] = 'fixture-sentinel-secret-not-for-network'
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
        '--output', str(tmp_path / 'host'), '--iterations', '1'], env=env,
        capture_output=True, text=True, timeout=120, check=True)
    report = json.loads(result.stdout)
    assert report['mode'] == 'fixture' and report['performance_claim'] is False
    assert report['controller'] == 'pinned_openevolve' and report['provider_calls'] == 1
    assert report['stage_calls'] == 2
    root = tmp_path / 'host'
    stages = [json.loads(line)['payload'] for line in (root / 'fixture-stages.jsonl').read_text().splitlines()]
    assert all(row['status'] == 'ok' and row['stage'] == 1 for row in stages)
    messages = json.loads((root / 'fixture-provider.jsonl').read_text())['payload']
    assert messages['system'] and messages['messages']
    for path in root.rglob('*'):
        if path.is_file():
            assert b'fixture-sentinel-secret-not-for-network' not in path.read_bytes()


def test_upstream_evaluator_runs_both_real_stages_for_grid(tmp_path, monkeypatch):
    import asyncio
    from core.openevolve_interop import ProgramDatabase  # loads pinned vendor
    from openevolve.config import EvaluatorConfig
    from openevolve.evaluator import Evaluator
    from zoo.circle_packing import reference_evaluator
    from test_circle_packing_sandbox import GRID
    monkeypatch.setenv('MORI_CIRCLE_REFERENCE_ROOT', str(tmp_path))
    config = EvaluatorConfig(cascade_evaluation=True, cascade_thresholds=[.5, .75],
                             parallel_evaluations=1, max_retries=0, timeout=120)
    evaluator = Evaluator(config, reference_evaluator.__file__)
    asyncio.run(evaluator.evaluate_program(GRID, 'grid'))
    stages = [json.loads(line)['payload'] for line in (tmp_path / 'fixture-stages.jsonl').read_text().splitlines()]
    assert [row['stage'] for row in stages] == [1, 2]
    assert all(row['status'] == 'ok' for row in stages)


def test_fixture_refuses_unsanitized_worker_environment(tmp_path, monkeypatch):
    from zoo.circle_packing.host_reference import run_fixture
    monkeypatch.setenv('PYTHONHASHSEED', '0')
    monkeypatch.setenv('PRIVATE_SENTINEL', 'fixture-only')
    with pytest.raises(ValueError, match='sanitized environment'):
        run_fixture(tmp_path / 'host')
    assert not (tmp_path / 'host').exists()
