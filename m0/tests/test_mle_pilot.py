"""Real subprocess pilot protocol fixtures; no external benchmark measurement."""
import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from tests.test_benchmark_adapters import TASK, official_fixture
from zoo.mle_bench_lite import pilot

TASKS = pilot.DEFAULT_TASKS


def fixtures(root):
    official, data, manifest = official_fixture(root)
    metadata = json.loads(manifest.read_text())
    for task in TASKS:
        shutil.copytree(official / 'mlebench/competitions' / TASK,
                        official / 'mlebench/competitions' / task)
        shutil.copytree(data / TASK, data / task)
        for rel, digest in list(metadata['files'].items()):
            if f'/{TASK}/' in rel:
                metadata['files'][rel.replace(f'/{TASK}/', f'/{task}/')] = digest
    manifest.write_text(json.dumps(metadata))
    return official, data, manifest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    paths = fixtures(tmp_path)
    monkeypatch.setattr(pilot, '_profile', lambda variant, token_budget, seed, iterations: {
        'variant': variant, 'budget': token_budget, 'seed': seed, 'iterations': iterations})
    monkeypatch.setattr(pilot, '_dataset_manifest', lambda root, task, seed: {
        'task': task, 'seed': seed, 'test_fixture': True})
    return paths


def command(root, mode='normal'):
    path = root / f'agent_{mode}.py'
    path.write_text('''import json, os, pathlib, shutil, sys, time
sys.path.insert(0, REPO)
from zoo.mle_bench_lite.pilot import digest
from zoo.mle_bench_lite.agent_common import token_usage_summary
workspace = pathlib.Path(sys.argv[1])
task, seed, arm = sys.argv[2], int(sys.argv[3]), sys.argv[4]
run_dir = workspace.parent
spec = json.loads((workspace.parents[3] / 'pilot_spec.json').read_text())['spec']
# Enforce in the actual child process that hidden grading has not happened yet.
for audit in workspace.parents[3].rglob('audit.jsonl'):
    assert 'official_grading_report' not in audit.read_text()
if MODE == 'timeout':
    time.sleep(20)
artifacts = run_dir / 'agent_artifacts'
usage_dir = artifacts / 'token_usage'
usage_dir.mkdir(parents=True)
model = 'canonical-snapshot' if MODE == 'alias' else ('changed-model' if MODE == 'cross_run_model' and arm == 'full' else spec['model'])
usage_id = 'fixture-receipt'
usage = {'usage_id': usage_id, 'source': 'offline_protocol_fixture', 'model': model,
         'pid': os.getpid(), 'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10}
if MODE == 'missing_response_model':
    usage['model'] = ''
if MODE == 'overspend':
    usage.update(prompt_tokens=1001, completion_tokens=0, total_tokens=1001)
if MODE != 'missing_usage':
    (usage_dir / (usage_id + '.json')).write_text(json.dumps(usage))
profile = spec['profiles'][str(seed) + ':' + arm]
if MODE == 'profile':
    profile['variant'] = 'unrelated'
dataset_manifest = {'task': task, 'seed': seed, 'test_fixture': True}
if MODE == 'paired_dataset' and arm == 'full':
    dataset_manifest['seed'] = seed + 1
summary = {'task_id': task, 'seed': seed, 'variant': arm, 'protocol': 'mle-public-train-composed-v1',
           'actual_model': model, 'requested_model': spec['model'], 'token_budget': spec['budget']['token'],
           'token_usage': token_usage_summary(usage_dir, require_nonempty=False),
           'profile': profile, 'profile_sha256': digest(profile),
           'dataset_manifest': dataset_manifest, 'dataset_identity': digest(dataset_manifest),
           'public_data_sha256': os.environ['MLE_PILOT_PUBLIC_DATA_SHA256'],
           'details': {'iterations': spec['iterations'], 'solution_timeout': spec['solution_timeout'],
                       'temperature': 0.0, 'max_completion_tokens': 4096}}
if MODE == 'model': summary['actual_model'] = 'changed-summary-only'
if MODE == 'seed': summary['seed'] += 1
if MODE == 'budget': summary['token_budget'] += 1
if MODE == 'dataset_identity': summary['dataset_identity'] = 'sha256:wrong'
if MODE == 'public_identity': summary['public_data_sha256'] = 'sha256:wrong'
(artifacts / 'agent_run.json').write_text(json.dumps(summary))
if MODE == 'data_tamper':
    (workspace / 'data/train.csv').write_text('tampered')
if MODE != 'missing_submission':
    (workspace / 'submission.csv').write_text('id,prediction\\n1,' + ('0.8' if arm == 'full' else '0.4') + '\\n')
if MODE == 'failure': sys.exit(3)
'''.replace('REPO', repr(str(Path(__file__).resolve().parents[1]))).replace('MODE', repr(mode)))
    return shlex.join([sys.executable, str(path), '{workspace}', '{task}', '{seed}', '{arm}'])


def grader(task):
    def grade(path):
        return {'competition_id': task, 'valid_submission': True,
                'score': float(path.read_text().splitlines()[1].split(',')[1]),
                'above_median': False, 'any_medal': False}
    return grade


def run(root, setup, mode='normal', **kwargs):
    official, data, manifest = setup
    return pilot.run_pilot(official, data, root / ('output_' + mode), model='fixture-model',
        token_budget=1000, time_limit=5, solution_timeout=1, iterations=4,
        seeds=(1,), task_ids=list(TASKS), manifest_path=manifest,
        grader_factory=grader, _fixture_agent_command=command(root, mode), **kwargs)


def test_subprocess_matrix_freezes_every_submission_before_any_hidden_grading(tmp_path, setup):
    report = run(tmp_path, setup)
    assert report['pilot_complete'] and report['expected_runs'] == 6
    assert report['formal_benchmark_complete'] is False and report['subset_only']
    assert report['official_benchmark_measurement'] is False
    assert report['evidence_kind'] == 'protocol_fixture'
    assert report['statistical_significance_claimed'] is False
    assert report['host_parity_claimed'] is False
    assert all(row['status'] == 'graded' for row in report['runs'])
    assert all(pair['complete'] and pair['score_delta_full_minus_baseline'] == .4
               for pair in report['pairs'])
    assert report['arms']['full']['known_tokens'] == 30
    assert report['arms']['full']['unknown_token_runs'] == 0
    assert report['arms']['baseline']['valid_submissions'] == 3
    assert report['spec']['budget'] == {'token': 1000, 'wallclock': 5}
    assert [row['arm'] for row in report['runs']] == ['baseline', 'full', 'full', 'baseline', 'baseline', 'full']
    for row in report['runs']:
        path = Path(row['submission_ref'])
        assert pilot.file_digest(path) == row['submission_sha256']
        assert Path(row['audit_ref']).is_file()
    assert not list((tmp_path / 'output_normal').rglob('benchmark_run.json'))


@pytest.mark.parametrize('mode', ['model', 'profile', 'seed', 'budget', 'dataset_identity',
    'public_identity', 'overspend', 'data_tamper', 'missing_submission', 'missing_usage', 'failure'])
def test_contract_drift_and_failed_runs_keep_entire_failure_matrix(tmp_path, setup, mode):
    report = run(tmp_path, setup, mode)
    assert not report['pilot_complete'] and report['failure_count'] == 6
    assert len(report['runs']) == report['expected_runs'] == 6
    assert all(row['status'] == 'failed' for row in report['runs'])
    assert all(not pair['complete'] for pair in report['pairs'])
    assert report['arms']['full']['graded_runs'] == 0
    if mode == 'missing_usage':
        assert report['arms']['full']['unknown_token_runs'] == 3
    else:
        assert report['arms']['full']['known_tokens'] > 0
    assert not any('official_grading_report' in p.read_text()
                   for p in (tmp_path / ('output_' + mode)).rglob('audit.jsonl'))


def test_paired_split_mismatch_never_produces_complete_comparison(tmp_path, setup):
    report = run(tmp_path, setup, 'paired_dataset')
    assert not report['pilot_complete']
    assert sum(row['status'] == 'graded' for row in report['runs']) == 3
    assert all('independently frozen splits' in row['error'] for row in report['runs'] if row['arm'] == 'full')


def test_timeout_kills_real_child_and_keeps_unknown_costs(tmp_path, setup):
    official, data, manifest = setup
    report = pilot.run_pilot(official, data, tmp_path / 'timeouts', model='fixture-model',
        token_budget=1000, time_limit=.1, solution_timeout=.05, iterations=4,
        task_ids=list(TASKS), manifest_path=manifest, grader_factory=grader,
        _fixture_agent_command=command(tmp_path, 'timeout'))
    assert report['failure_count'] == 6
    assert all(row['timed_out'] and row['agent_returncode'] == -9 for row in report['runs'])
    assert report['arms']['full']['unknown_token_runs'] == 3


def test_snapshot_drift_stops_subsequent_agents_before_execution(tmp_path, setup):
    official, data, manifest = setup
    real_execute = pilot._execute_agent
    calls = []
    def execute(*args, **kwargs):
        result = real_execute(*args, **kwargs)
        calls.append(args[2])
        for task in TASKS:
            (data / task / 'prepared/public/train.csv').write_text('changed source')
        return result
    from unittest.mock import patch
    with patch.object(pilot, '_execute_agent', execute):
        result = run(tmp_path, setup)
    assert calls == [TASKS[0]]
    assert len(result['runs']) == 6 and not result['pilot_complete']
    assert sum('public dataset changed' in row.get('error', '') for row in result['runs']) == 5


def test_private_or_public_symlink_rejected_before_starting_any_run(tmp_path, setup):
    official, data, manifest = setup
    secret = tmp_path / 'secret.txt'; secret.write_text('PRIVATE')
    (data / TASKS[0] / 'prepared/public/link.txt').symlink_to(secret)
    with pytest.raises(ValueError, match='symbolic links'):
        run(tmp_path, setup)
    assert not (tmp_path / 'output_normal').exists()


@pytest.mark.parametrize('kwargs', [dict(task_ids=[TASKS[0]]), dict(seeds=(1, 1)),
    dict(iterations=2), dict(token_budget=True), dict(time_limit=float('nan')),
    dict(solution_timeout=50), dict(model='')])
def test_invalid_experiment_plan_is_rejected_before_files_or_agents(tmp_path, setup, kwargs):
    official, data, manifest = setup
    values = dict(model='fixture', token_budget=1000, time_limit=5, solution_timeout=1,
                  iterations=4, seeds=(1,), task_ids=list(TASKS))
    values.update(kwargs)
    with pytest.raises(ValueError):
        pilot.run_pilot(official, data, tmp_path / 'absent', manifest_path=manifest,
                       grader_factory=grader, _fixture_agent_command='never', **values)
    assert not (tmp_path / 'absent').exists()


def test_output_is_never_overwritten(tmp_path, setup):
    report = run(tmp_path, setup)
    path = tmp_path / 'output_normal/pilot.json'
    old = path.read_bytes()
    with pytest.raises(FileExistsError):
        run(tmp_path, setup)
    assert path.read_bytes() == old


def test_fixture_commands_cannot_be_used_for_real_benchmark_evidence(tmp_path, setup):
    official, data, manifest = setup
    with pytest.raises(ValueError, match='protocol fixtures'):
        pilot.run_pilot(official, data, tmp_path / 'absent', model='fixture', token_budget=10,
                        _fixture_agent_command='fake')


def test_preflight_reports_missing_requirements_without_network_or_secret_values(tmp_path, setup, monkeypatch):
    official, data, manifest = setup
    monkeypatch.setattr(pilot.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(pilot.shutil, 'which', lambda _: None)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(pilot.importlib.util, 'find_spec', lambda _: None)
    report = pilot.preflight_pilot(official, data, model='fixture', token_budget=1000,
                                  manifest_path=manifest)
    assert not report['ready'] and not report['benchmark_execution']
    assert {row['requirement'] for row in report['missing']} == {
        'execution_host', 'bubblewrap', 'model_credentials', 'official_grader'}
    assert report['plan']['public_data']
    assert not (tmp_path / 'output').exists()
    monkeypatch.setenv('OPENAI_API_KEY', 'DO-NOT-PRINT-THIS')
    result = pilot.preflight_pilot(official, data, model='fixture', token_budget=1000,
                                  manifest_path=manifest)
    assert 'DO-NOT-PRINT-THIS' not in json.dumps(result)


def test_inherited_credentials_never_enter_pilot_evidence(tmp_path, setup, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'NEVER-PERSIST-THIS-KEY')
    report = run(tmp_path, setup)
    assert report['pilot_complete']
    for path in (tmp_path / 'output_normal').rglob('*.json*'):
        assert 'NEVER-PERSIST-THIS-KEY' not in path.read_text()


def _provider_call(root, call_id, *, model='fixture-model', completed=True, total=10):
    import hashlib
    usage_dir = root / 'token_usage'
    calls_dir = root / 'token_usage_calls'
    usage_dir.mkdir(exist_ok=True); calls_dir.mkdir(exist_ok=True)
    start = {'call_id': call_id, 'request_sha256': 'a' * 64,
             'provider': {'requested_model': 'fixture-model'}}
    (calls_dir / (call_id + '.started.json')).write_text(json.dumps(start))
    if completed:
        receipt = {'usage_id': call_id, 'model': model, 'requested_model': 'fixture-model',
                   'source': 'fixture', 'request_sha256': 'a' * 64, 'total_tokens': total}
        path = usage_dir / (call_id + '.json'); path.write_text(json.dumps(receipt))
        (calls_dir / (call_id + '.completed.json')).write_text(json.dumps({
            'call_id': call_id, 'usage_receipt_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
    return usage_dir


def test_usage_audit_preserves_first_bill_and_unknown_second_operation(tmp_path):
    from zoo.mle_bench_lite.usage_audit import audit_usage
    path = _provider_call(tmp_path, 'first')
    _provider_call(tmp_path, 'second', completed=False)
    report = audit_usage(path)
    assert report['known_tokens'] == 10
    assert not report['complete'] and not report['costs_complete']
    assert report['unresolved_calls'] == ['second']


def test_usage_audit_retains_known_cost_when_response_model_is_missing(tmp_path):
    from zoo.mle_bench_lite.usage_audit import audit_usage
    path = _provider_call(tmp_path, 'first', model='')
    report = audit_usage(path)
    assert report['known_tokens'] == 10 and report['costs_complete']
    assert not report['complete'] and not report['unresolved_calls']
    assert any(error['kind'] == 'identity' for error in report['errors'])


def test_usage_audit_hash_tamper_is_not_a_completed_bill(tmp_path):
    from zoo.mle_bench_lite.usage_audit import audit_usage
    path = _provider_call(tmp_path, 'first')
    receipt_path = path / 'first.json'
    receipt = json.loads(receipt_path.read_text()); receipt['total_tokens'] = 1
    receipt_path.write_text(json.dumps(receipt))
    report = audit_usage(path)
    assert not report['complete'] and not report['costs_complete']
    assert any(error['kind'] == 'integrity' for error in report['errors'])


def test_successful_usage_audit_binds_every_call_and_receipt(tmp_path):
    from zoo.mle_bench_lite.usage_audit import audit_usage
    path = _provider_call(tmp_path, 'first')
    _provider_call(tmp_path, 'second', total=20)
    report = audit_usage(path)
    assert report['complete'] and report['costs_complete']
    assert report['known_tokens'] == report['usage']['total_tokens'] == 30
    assert report['started_calls'] == report['completed_calls'] == report['receipt_count'] == 2


def test_legacy_receipts_allowed_only_in_explicit_fixture_audit(tmp_path):
    from zoo.mle_bench_lite.usage_audit import audit_usage
    usage = tmp_path / 'token_usage'; usage.mkdir()
    (usage / 'one.json').write_text(json.dumps({'usage_id': 'one', 'source': 'fixture',
                                             'model': 'fixture-model', 'total_tokens': 10}))
    strict = audit_usage(usage)
    assert not strict['complete'] and not strict['costs_complete']
    fixture = audit_usage(usage, allow_fixture_receipts=True)
    assert fixture['complete'] and fixture['fixture_legacy_receipts']


def test_requested_alias_is_valid_when_every_run_returns_same_snapshot(tmp_path, setup):
    report = run(tmp_path, setup, 'alias')
    assert report['pilot_complete'] and report['backbone_evidence_complete']
    assert report['requested_model'] == 'fixture-model'
    assert report['actual_models'] == ['canonical-snapshot']


def test_model_drift_blocks_remaining_paid_runs_and_preserves_measured_costs(tmp_path, setup):
    report = run(tmp_path, setup, 'cross_run_model')
    assert not report['pilot_complete'] and not report['backbone_evidence_complete']
    assert report['observed_response_models'] == ['changed-model', 'fixture-model']
    assert sum(row.get('blocked_before_execution', False) for row in report['runs']) == 4
    assert sum(row.get('usage_audit', {}).get('known_tokens', 0) for row in report['runs']) == 20
    assert all(not pair['complete'] for pair in report['pairs'])


@pytest.mark.parametrize('path', ['/usr/local/share/mle/data', '/bin/mle/graders', '/lib/mle/results'])
def test_real_pilot_refuses_data_or_graders_visible_through_system_mounts(path):
    with pytest.raises(ValueError, match='sandbox-visible system'):
        pilot._protected_host_path(Path(path))


@pytest.mark.linux
def test_linux_pilot_runs_all_three_real_composed_clis_http_and_sandboxed_candidates(tmp_path, monkeypatch):
    from tests.test_mle_composed import CodeService, fixture_public
    official, data, manifest = fixtures(tmp_path)
    for task in TASKS:
        public = data / task / 'prepared/public'
        shutil.rmtree(public)
        fixture_public(public, task)
    code = '''import csv, json
from pathlib import Path
protocol = json.loads(Path('data/protocol.json').read_text())
with open('data/train.csv') as stream: train = list(csv.DictReader(stream))
with open('data/predict.csv') as stream: rows = list(csv.DictReader(stream))
columns = protocol['output_columns'][1:]
if protocol['kind'] == 'classification':
    values = [sum(row['target'] == name for row in train) / len(train) for name in columns]
else:
    values = [sum(float(row[name]) for row in train) / len(train) for name in columns]
with open('predictions.csv', 'w', newline='') as stream:
    writer = csv.writer(stream); writer.writerow(protocol['output_columns'])
    for row in rows: writer.writerow([row['row_id'], *values])
'''
    service = CodeService([code])
    monkeypatch.setenv('OPENAI_API_KEY', 'LOCAL-FIXTURE-NO-REAL-API')
    monkeypatch.setenv('OPENAI_API_BASE', service.url)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1]))
    try:
        report = pilot.run_pilot(official, data, tmp_path / 'real-pipeline', model='fixture-alias',
            token_budget=10000, time_limit=30, solution_timeout=5, iterations=3,
            task_ids=list(TASKS), manifest_path=manifest, grader_factory=grader)
    finally:
        service.close()
    assert report['pilot_complete'], json.dumps(report['runs'], indent=2)
    assert report['actual_models'] == ['fixture-snapshot']
    assert report['official_benchmark_measurement'] is False
    assert report['evidence_kind'] == 'protocol_fixture'
    assert len(service.requests) == 24
    for row in report['runs']:
        assert row['usage_audit']['complete']
        assert not row['usage_audit']['fixture_legacy_receipts']
        assert row['actual_costs']['token'] == 72
        run_dir = Path(row['submission_ref']).parents[1]
        summary = json.loads((run_dir / 'agent_artifacts/agent_run.json').read_text())
        assert summary['dataset_identity'] == pilot.digest(report['spec']['datasets'][f"{row['task_id']}:1"])
        if row['arm'] == 'full':
            assert summary['profile']['policy']['name'] == 'population'
            assert summary['details']['result']['proxy_validity']['mode'] == 'degraded'
            assert summary['details']['result']['population']['rng_state']['calls'] == 2


def test_provider_invocation_settings_are_checked_against_frozen_plan(tmp_path):
    spec = pilot._plan('fixture-model', 1000, 60, 5, 3, (1,), list(TASKS))
    call_dir = tmp_path / 'agent_artifacts/token_usage_calls'; call_dir.mkdir(parents=True)
    provider = {'requested_model': 'fixture-model', 'base_url': spec['provider_base_url'],
                'temperature': 0.0, 'max_completion_tokens': 4096, 'timeout': 30.0,
                'token_budget': 1000, 'retry_policy': 'never', 'response_model_required': True}
    call = call_dir / 'one.started.json'; call.write_text(json.dumps({'provider': provider}))
    pilot._validate_provider_settings(tmp_path, spec, fixture=False)
    provider['temperature'] = 1.0
    call.write_text(json.dumps({'provider': provider}))
    with pytest.raises(ValueError, match='actual provider temperature'):
        pilot._validate_provider_settings(tmp_path, spec, fixture=False)


@pytest.mark.parametrize('endpoint', ['https://user:secret@api.example.com/v1',
    'https://api.example.com/v1?api_key=secret', 'http://api.example.com/v1'])
def test_provider_endpoint_cannot_persist_credentials_or_use_remote_plaintext(monkeypatch, endpoint):
    monkeypatch.setenv('OPENAI_API_BASE', endpoint)
    with pytest.raises(ValueError, match='without credentials'):
        pilot._plan('model', 1000, 60, 5, 3, (1,), list(TASKS))


def test_missing_response_model_preserves_known_bill_and_blocks_all_remaining_paid_runs(tmp_path, setup):
    report = run(tmp_path, setup, 'missing_response_model')
    assert not report['pilot_complete'] and report['failure_count'] == 6
    executed = [row for row in report['runs'] if not row.get('blocked_before_execution')]
    assert len(executed) == 1
    assert executed[0]['usage_audit']['known_tokens'] == 10
    assert executed[0]['usage_audit']['costs_complete']
    assert not executed[0]['usage_audit']['complete']
    assert executed[0]['actual_costs']['token'] == 10
    blocked = [row for row in report['runs'] if row.get('blocked_before_execution')]
    assert len(blocked) == 5
    assert all(row['actual_costs'] == {'token': 0, 'wallclock': 0} for row in blocked)
    assert all(row['usage_audit']['not_executed'] for row in blocked)
    assert all(report['arms'][arm]['unknown_token_runs'] == 0 for arm in pilot.ARMS)
    assert sum(report['arms'][arm]['known_tokens'] for arm in pilot.ARMS) == 10
    assert len(list((tmp_path / 'output_missing_response_model').rglob('stdout.log'))) == 1


def official_package_fixture(setup, monkeypatch):
    """Explicit in-memory official-package fixture; no real benchmark result."""
    import hashlib
    import importlib.machinery
    import types
    import yaml
    official, data, manifest = setup
    metadata = json.loads(manifest.read_text())
    for task in TASKS:
        private = data / task / 'prepared/private'; private.mkdir(parents=True)
        (private / 'test.csv').write_text('id,answer\n1,PRIVATE_ANSWER_CANARY\n')
        checksums = {split: {path.name: hashlib.md5(path.read_bytes()).hexdigest()
            for path in (data / task / 'prepared' / split).glob('*.csv')}
            for split in ('public', 'private')}
        rel = f'mlebench/competitions/{task}/checksums.yaml'
        (official / rel).write_text(yaml.safe_dump(checksums))
        metadata['files'][rel] = hashlib.sha256((official / rel).read_bytes()).hexdigest()
    manifest.write_text(json.dumps(metadata))
    modules = {}
    for name, filename in [('mlebench', '__init__.py'), ('mlebench.registry', 'registry.py'),
                           ('mlebench.data', 'data.py'), ('mlebench.grade', 'grade.py')]:
        path = official / 'mlebench' / filename; path.write_text('# explicit test fixture\n')
        module = types.ModuleType(name); module.__file__ = str(path)
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
        if name == 'mlebench': module.__path__ = [str(path.parent)]
        monkeypatch.setitem(sys.modules, name, module); modules[name] = module
    class Registry:
        def __init__(self, data_root): self.data_root = Path(data_root)
        def get_competition(self, task):
            root = self.data_root / task / 'prepared'
            return types.SimpleNamespace(id=task, public_dir=root / 'public', private_dir=root / 'private',
                answers=root / 'private/test.csv', gold_submission=root / 'private/test.csv',
                sample_submission=root / 'public/sample_submission.csv',
                checksums=official / f'mlebench/competitions/{task}/checksums.yaml')
    modules['mlebench.registry'].Registry = Registry
    modules['mlebench.data'].is_dataset_prepared = lambda competition: True
    grades = []
    def grade_csv(path, competition):
        grades.append(competition.id)
        return grader(competition.id)(path)
    modules['mlebench.grade'].grade_csv = grade_csv
    monkeypatch.setattr(pilot, '_verify_official_checkout', lambda path: None)
    monkeypatch.setattr(pilot.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(pilot.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(pilot.shutil, 'which', lambda _: '/usr/bin/bwrap')
    monkeypatch.setenv('OPENAI_API_KEY', 'EXPLICIT-LOCAL-FIXTURE')
    return modules, grades


def test_official_preflight_freezes_hashes_without_exposing_private_answers(tmp_path, setup, monkeypatch):
    official_package_fixture(setup, monkeypatch)
    official, data, manifest = setup
    report = pilot.preflight_pilot(official, data, model='fixture-model', token_budget=1000,
                                  manifest_path=manifest)
    assert report['ready'] and not report['benchmark_execution']
    identity = report['plan']['official_prepared_identity']
    assert len(identity['prepared_tasks']) == 3
    assert identity['prepared_tasks'][TASKS[0]]['files']['private/test.csv']['sha256'].startswith('sha256:')
    assert 'PRIVATE_ANSWER_CANARY' not in json.dumps(report)


@pytest.mark.parametrize('problem', ['missing_private', 'private_drift', 'public_drift',
                                    'wrong_package', 'not_prepared', 'private_symlink', 'wrong_gold'])
def test_missing_or_unverified_official_environment_rejects_before_any_paid_call(tmp_path, setup, monkeypatch, problem):
    modules, _ = official_package_fixture(setup, monkeypatch)
    official, data, manifest = setup
    private = data / TASKS[0] / 'prepared/private/test.csv'
    if problem == 'missing_private': private.unlink()
    elif problem == 'private_drift': private.write_text('changed private answer')
    elif problem == 'public_drift': (data / TASKS[0] / 'prepared/public/train.csv').write_text('changed public input')
    elif problem == 'wrong_package': modules['mlebench.registry'].__file__ = str(tmp_path / 'wrong-registry.py')
    elif problem == 'not_prepared': modules['mlebench.data'].is_dataset_prepared = lambda competition: False
    elif problem == 'private_symlink':
        target = tmp_path / 'answers.csv'; private.rename(target); private.symlink_to(target)
    elif problem == 'wrong_gold':
        original = modules['mlebench.registry'].Registry.get_competition
        def changed(self, task):
            value = original(self, task); value.gold_submission = value.private_dir / 'missing-gold.csv'; return value
        monkeypatch.setattr(modules['mlebench.registry'].Registry, 'get_competition', changed)
    calls = []
    monkeypatch.setattr(pilot, '_execute_agent', lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match='preflight failed'):
        pilot.run_pilot(official, data, tmp_path / 'must-not-run', model='fixture-model',
                        token_budget=1000, manifest_path=manifest)
    assert not calls and not (tmp_path / 'must-not-run').exists()


@pytest.mark.parametrize('after_calls', [1, 6])
def test_private_drift_blocks_further_calls_and_all_final_scoring(tmp_path, setup, monkeypatch, after_calls):
    import hashlib
    _, grades = official_package_fixture(setup, monkeypatch)
    official, data, manifest = setup
    actual_execute = pilot._execute_agent
    fixture_command = command(tmp_path)
    calls = []
    def execute(_command, workspace, task, seed, arm, time_limit, run_dir, env):
        result = actual_execute(fixture_command, workspace, task, seed, arm, time_limit, run_dir, env)
        calls.append((task, arm))
        usage_dir = run_dir / 'agent_artifacts/token_usage'
        calls_dir = run_dir / 'agent_artifacts/token_usage_calls'; calls_dir.mkdir()
        receipt_path = usage_dir / 'fixture-receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt.update(requested_model='fixture-model', request_sha256='a' * 64)
        receipt_path.write_text(json.dumps(receipt))
        spec = json.loads((workspace.parents[3] / 'pilot_spec.json').read_text())['spec']
        provider = {'requested_model': 'fixture-model', 'base_url': spec['provider_base_url'],
                    'temperature': 0.0, 'max_completion_tokens': 4096, 'timeout': 30.0,
                    'token_budget': 1000, 'retry_policy': 'never', 'response_model_required': True}
        (calls_dir / 'fixture-receipt.started.json').write_text(json.dumps({
            'call_id': 'fixture-receipt', 'request_sha256': 'a' * 64, 'provider': provider}))
        (calls_dir / 'fixture-receipt.completed.json').write_text(json.dumps({
            'call_id': 'fixture-receipt', 'usage_receipt_sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest()}))
        summary_path = run_dir / 'agent_artifacts/agent_run.json'
        summary = json.loads(summary_path.read_text())
        from zoo.mle_bench_lite.agent_common import token_usage_summary
        summary['token_usage'] = token_usage_summary(usage_dir)
        summary_path.write_text(json.dumps(summary))
        if len(calls) == after_calls:
            (data / TASKS[0] / 'prepared/private/test.csv').write_text('CHANGED-PRIVATE')
        return result
    monkeypatch.setattr(pilot, '_execute_agent', execute)
    result = pilot.run_pilot(official, data, tmp_path / 'blocked', model='fixture-model',
        token_budget=1000, time_limit=5, solution_timeout=1, iterations=4,
        task_ids=list(TASKS), manifest_path=manifest)
    assert len(calls) == after_calls and not grades
    assert not result['pilot_complete'] and result['failure_count'] == 6
    assert result['official_benchmark_measurement'] is False
    assert sum(row.get('usage_audit', {}).get('known_tokens', 0) for row in result['runs']) == after_calls * 10
    assert all(row['actual_costs'] == {'token': 0, 'wallclock': 0}
               for row in result['runs'] if row.get('blocked_before_execution'))


@pytest.mark.parametrize('condition', ['wrong_revision', 'dirty_tracked'])
def test_official_checkout_requires_locked_head_and_clean_tracked_sources(tmp_path, monkeypatch, condition):
    from types import SimpleNamespace
    def git(command, **kwargs):
        output = str(tmp_path) if command[-1] == '--show-toplevel' else (
            'wrong' if condition == 'wrong_revision' else pilot.REVISION) if command[-1] == 'HEAD' else ' M mlebench/grade.py'
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(pilot.subprocess, 'run', git)
    with pytest.raises(ValueError, match='clean checkout'):
        pilot._verify_official_checkout(tmp_path)
