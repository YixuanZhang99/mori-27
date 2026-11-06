"""The reference fixture must execute the pinned host worker, not a substitute loop."""
import json
import hashlib
import os
import subprocess
import sys
import threading

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
    best = root / 'host' / 'best' / 'best_program.py'
    info = json.loads((best.parent / 'best_program_info.json').read_text())
    assert report['selected_program'] == {
        'id': info['id'],
        'program_ref': 'sha256:' + hashlib.sha256(best.read_bytes()).hexdigest(),
        'metrics': info['metrics'],
    }
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


def test_stage_two_broker_failure_does_not_promote_stage_one_score(tmp_path, monkeypatch):
    import asyncio
    from core.llm import UsageError
    from core.openevolve_interop import ProgramDatabase  # loads pinned vendor
    from openevolve.config import EvaluatorConfig
    from openevolve.evaluator import Evaluator
    from zoo.circle_packing import reference_evaluator
    from zoo.circle_packing.host_transport import HostEvaluationClient
    from test_circle_packing_sandbox import GRID
    from test_openevolve_host_stage_budget import fake_result
    monkeypatch.setenv('MORI_CIRCLE_REFERENCE_ROOT', str(tmp_path))
    monkeypatch.setenv('MORI_CIRCLE_STAGE_BROKER', '1')
    monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(tmp_path / 'unused.sock'))
    monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
    def evaluate(self, program, *, stage, prior_id=None):
        if stage == 1:
            return 'a' * 32, fake_result(program, stage, score=.6)
        raise UsageError('fixture unresolved stage')
    monkeypatch.setattr(HostEvaluationClient, 'evaluate', evaluate)
    config = EvaluatorConfig(cascade_evaluation=True, cascade_thresholds=[.5, .75],
                             parallel_evaluations=1, max_retries=0, timeout=120)
    result = asyncio.run(Evaluator(config, reference_evaluator.__file__).evaluate_program(GRID, 'grid'))
    assert result['combined_score'] == 0.0 and result['fixture_unresolved'] == 1.0
    unresolved = (tmp_path / 'fixture-unresolved.jsonl').read_text().splitlines()
    assert json.loads(unresolved[0])['payload']['stage'] == 2


def test_measured_stage_two_timeout_does_not_promote_stage_one_score(tmp_path, monkeypatch):
    import asyncio
    from core.openevolve_interop import ProgramDatabase
    from openevolve.config import EvaluatorConfig
    from openevolve.evaluator import Evaluator
    from zoo.circle_packing import reference_evaluator
    from zoo.circle_packing.host_transport import HostEvaluationClient
    from test_circle_packing_sandbox import GRID
    from test_openevolve_host_stage_budget import fake_result
    monkeypatch.setenv('MORI_CIRCLE_REFERENCE_ROOT', str(tmp_path))
    monkeypatch.setenv('MORI_CIRCLE_STAGE_BROKER', '1')
    monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(tmp_path / 'unused.sock'))
    monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
    def evaluate(self, program, *, stage, prior_id=None):
        return ('a' if stage == 1 else 'b') * 32, fake_result(
            program, stage, score=.6, status='ok' if stage == 1 else 'timeout')
    monkeypatch.setattr(HostEvaluationClient, 'evaluate', evaluate)
    config = EvaluatorConfig(cascade_evaluation=True, cascade_thresholds=[.5, .75],
                             parallel_evaluations=1, max_retries=0, timeout=120)
    result = asyncio.run(Evaluator(config, reference_evaluator.__file__).evaluate_program(GRID, 'grid'))
    assert result['combined_score'] == 0.0 and result['fixture_stage_failed'] == 1.0


def test_unrecordable_stage_failure_aborts_instead_of_reporting_success(tmp_path, monkeypatch):
    import asyncio
    from core.llm import UsageError
    from core.openevolve_interop import ProgramDatabase
    from core.x1.store import AppendOnlyStore
    from openevolve.config import EvaluatorConfig
    from openevolve.evaluator import Evaluator
    from zoo.circle_packing import reference_evaluator
    from zoo.circle_packing.host_transport import HostEvaluationClient
    from test_circle_packing_sandbox import GRID
    from test_openevolve_host_stage_budget import fake_result
    monkeypatch.setenv('MORI_CIRCLE_REFERENCE_ROOT', str(tmp_path))
    monkeypatch.setenv('MORI_CIRCLE_STAGE_BROKER', '1')
    monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(tmp_path / 'unused.sock'))
    monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
    original = AppendOnlyStore.append
    def write(self, kind, payload):
        if kind == 'unresolved':
            raise OSError('fixture evidence storage failure')
        return original(self, kind, payload)
    def evaluate(self, program, *, stage, prior_id=None):
        if stage == 1:
            return 'a' * 32, fake_result(program, stage, score=.6)
        raise UsageError('fixture unresolved stage')
    monkeypatch.setattr(AppendOnlyStore, 'append', write)
    monkeypatch.setattr(HostEvaluationClient, 'evaluate', evaluate)
    config = EvaluatorConfig(cascade_evaluation=True, cascade_thresholds=[.5, .75],
                             parallel_evaluations=1, max_retries=0, timeout=120)
    with pytest.raises(BaseException, match='cannot record unresolved stage'):
        asyncio.run(Evaluator(config, reference_evaluator.__file__).evaluate_program(GRID, 'grid'))


def test_actual_host_process_aborts_when_unresolved_marker_cannot_be_written(tmp_path):
    from core.llm import UsageError
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_transport import HostBroker
    path = tmp_path / 'failing-stage.sock'
    output = tmp_path / 'host'
    def dispatch(request_id, argument):
        if argument.get('stage') == 1:
            (output / 'fixture-unresolved.jsonl').mkdir()
            result = fake_result(argument['program'], 1, score=.6)
            return {'state': 'ok', 'result': json.dumps(result),
                    'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}
        raise UsageError('fixture unresolved stage')
    env = {key: value for key, value in os.environ.items() if 'API_KEY' not in key}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64)
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        thread = threading.Thread(target=lambda: [broker.serve_one() for _ in range(2)], daemon=True)
        thread.start()
        result = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(output), '--iterations', '1', '--fixture-broker', '--fixture-stage-broker'],
            env=env, capture_output=True, text=True, timeout=120)
        thread.join(timeout=5)
    assert result.returncode != 0 and 'cannot record unresolved stage' in result.stderr


def test_fixture_refuses_unsanitized_worker_environment(tmp_path, monkeypatch):
    from zoo.circle_packing.host_reference import run_fixture
    monkeypatch.setenv('PYTHONHASHSEED', '0')
    monkeypatch.setenv('PRIVATE_SENTINEL', 'fixture-only')
    with pytest.raises(ValueError, match='sanitized environment'):
        run_fixture(tmp_path / 'host')
    assert not (tmp_path / 'host').exists()


def test_actual_host_worker_uses_fixture_broker_without_credentials(tmp_path):
    from zoo.circle_packing.host_transport import HostBroker
    path = tmp_path / 'fixture.sock'
    requests = []
    def dispatch(request_id, argument):
        requests.append(argument)
        return {'state': 'ok', 'result': ('<<<<<<< SEARCH\n    n = 26\n=======\n'
            '    n = 26\n    # broker fixture\n>>>>>>> REPLACE\n'),
            'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}}
    env = {key: value for key, value in os.environ.items()
           if 'API_KEY' not in key and not key.startswith('KAGGLE_')}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64,
               OPENAI_API_KEY='fixture-api-secret-not-for-network')
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        result = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(tmp_path / 'host'), '--iterations', '1', '--fixture-broker'],
            env=env, capture_output=True, text=True, timeout=120, check=True)
        thread.join(timeout=5)
    report = json.loads(result.stdout)
    assert report['fixture_broker'] and report['stage_calls'] == 2
    assert report['provider_calls'] is None
    assert len(requests) == 1 and requests[0]['host_messages']['system']
    for item in (tmp_path / 'host').rglob('*'):
        if item.is_file():
            data = item.read_bytes()
            assert b'fixture-api-secret-not-for-network' not in data and b'a' * 64 not in data
