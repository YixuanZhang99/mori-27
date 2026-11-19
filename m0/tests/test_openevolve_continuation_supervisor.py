"""Versioned Mori fixtures retain their original supervisor and deadline identity.

Portable routing tests replace OS clock readings, artifact I/O and process launch;
the frozen-worker integration exercises those actual Linux boundaries.
"""
import copy
from pathlib import Path

import pytest

from core.composition.recovery import ContinuationStore
from core.executor.process import ProcessJournal
from core.x1.checkpoint import payload_digest
from test_openevolve_continuation_event import fixture_pair_ledger
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.mori_supervisor import launch_fixture_controller
from zoo.mle_bench_lite.cny_budget import _continuation_artifact_receipt


@pytest.fixture
def launch_setup(tmp_path, monkeypatch):
    ledger, original_proof = fixture_pair_ledger(tmp_path)
    head = ledger.snapshot()['journal_head']
    draft = build_continuation_draft(ledger.circle_continuation_inventory(expected_head=head),
        experiment_id='circle-v2', source_commit='6' * 40, dependency_lock_sha256='7' * 64,
        method_changes=['supervised fixture'])
    event = {'kind': 'bind_circle_continuation', 'schema_version': 2, 'previous_head': head,
             'draft': draft, 'tree_ref': 'sha256:' + '8' * 64, 'runtime_ref': 'sha256:' + '9' * 64,
             'python_sha256': 'a' * 64, 'runtime_manifest_sha256': 'b' * 64}
    event['artifact_verification_sha256'] = _continuation_artifact_receipt(event)
    with ledger._transaction() as (db, _policy, state):
        ledger._append(db, state, event)
    now = [1_000_000_000]
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now[0])
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity',
                        lambda: '12345678-1234-1234-1234-123456789abc')
    ref = 'sha256:' + draft['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--mori-0', plan_ref=ref, seconds=draft['limits']['wallclock_seconds'])
    source, runtime = tmp_path / 'source-bundle/source/m0', tmp_path / 'runtime-bundle/runtime-test'
    source.mkdir(parents=True)
    runtime.mkdir(parents=True)
    config = {'plan': draft, 'ref': ref, 'runtime_manifest': {}, 'source_manifest': {},
              'source': str(source), 'runtime': str(runtime), 'ledger': str(ledger.path),
              'clock': str(clock._store.path), 'output': str(tmp_path / 'output'),
              'base_url': 'http://127.0.0.1:12345', 'campaign_id': draft['campaign_id'], 'seed': 0}
    checks, starts = [], []
    def verify(actual_ledger, actual_draft, **kwargs):
        assert actual_ledger.path == ledger.path and actual_draft == draft
        assert kwargs == {'source_directory': source.parent.parent, 'runtime_directory': runtime.parent,
                          'base_python': '/usr/bin/python3.12', 'expected_head': ledger.snapshot()['journal_head']}
        checks.append(kwargs['expected_head'])
        return {'source': str(source.parent), 'runtime': str(runtime)}
    monkeypatch.setattr('zoo.circle_packing.continuation_binding.verify_bound_fixture_continuation', verify)
    monkeypatch.setattr('zoo.circle_packing.mori_supervisor.sandbox_child_path', lambda: '/usr/bin:/bin')
    def launch(self, command, cwd, env, timeout, metadata, **kwargs):
        starts.append({'command': command, 'cwd': cwd, 'env': env, 'timeout': timeout,
                       'metadata': metadata, **kwargs})
        return None, {}
    monkeypatch.setattr(ProcessJournal, 'launch', launch)
    monkeypatch.setattr(ProcessJournal, 'wait', lambda *a, **k: {'returncode': 0, 'timeout': False})
    return ledger, original_proof, config, clock, now, checks, starts


def test_supervisor_claims_versioned_worker_and_uses_original_absolute_deadline(tmp_path, launch_setup):
    ledger, proof, config, clock, now, checks, starts = launch_setup
    original_clock = copy.deepcopy(clock._record)
    now[0] += 17_000_000_000
    directory = tmp_path / 'supervisor'
    assert launch_fixture_controller(config, deadline=clock, directory=directory)['returncode'] == 0
    assert len(starts) == 1 and len(checks) == 2
    started = starts[0]
    binding = {'schema_version': 1, 'cell_id': 'circle-v2--mori-0',
        'deadline_ref': original_clock['record_sha256'], 'config_sha256': payload_digest(config),
        'directory': str(directory), 'entry': 'zoo.circle_packing.mori_fixture_worker'}
    assert ledger.cell_worker_claim(binding['cell_id']) == {
        'deadline_ref': original_clock['record_sha256'], 'worker_ref': payload_digest(binding)}
    assert started['metadata']['worker_ref'] == payload_digest(binding)
    assert started['command'] == [str(Path(config['runtime']) / 'bin/python'), '-m',
                                  binding['entry'], str(directory / 'config.json')]
    assert started['absolute_deadline'] == {'boot_id': original_clock['boot_id'],
        'deadline_ns': original_clock['start_ns'] + original_clock['seconds'] * 1_000_000_000}
    assert started['timeout'] == original_clock['seconds'] - 17 and started['die_with_parent'] is True
    assert 'DEEPSEEK_API_KEY' not in started['env']
    assert clock._record == original_clock and ledger.first_pair_audit() == proof
    with pytest.raises(ValueError, match='claimed'):
        launch_fixture_controller(config, deadline=clock, directory=tmp_path / 'duplicate')
    assert len(starts) == 1


def test_supervisor_verifies_continuation_artifacts_before_claim(tmp_path, monkeypatch, launch_setup):
    ledger, _, config, clock, _, _, starts = launch_setup
    def damaged(*args, **kwargs):
        raise ValueError('bound artifact was altered')
    monkeypatch.setattr('zoo.circle_packing.continuation_binding.verify_bound_fixture_continuation', damaged)
    before = ledger.snapshot()
    directory = tmp_path / 'supervisor'
    with pytest.raises(ValueError, match='bound artifact was altered'):
        launch_fixture_controller(config, deadline=clock, directory=directory)
    assert ledger.snapshot() == before and not directory.exists() and not starts


@pytest.mark.parametrize('overrun_ns', [0, 1])
def test_expired_original_clock_cannot_claim_or_launch_worker(tmp_path, launch_setup, overrun_ns):
    ledger, proof, config, clock, now, _, starts = launch_setup
    original_clock = copy.deepcopy(clock._record)
    now[0] = original_clock['start_ns'] + original_clock['seconds'] * 1_000_000_000 + overrun_ns
    directory = tmp_path / 'supervisor'
    with pytest.raises(ValueError, match='deadline has expired'):
        launch_fixture_controller(config, deadline=clock, directory=directory)
    assert ledger.cell_worker_claim(original_clock['cell_id']) is None
    assert not directory.exists() and not starts
    assert clock._record == original_clock and ledger.first_pair_audit() == proof


@pytest.mark.parametrize('field', ['source', 'runtime'])
def test_supervisor_rejects_substituted_verified_artifact_path(tmp_path, monkeypatch, launch_setup, field):
    ledger, _, config, clock, _, _, starts = launch_setup
    def substituted(*args, **kwargs):
        result = {'source': str(Path(config['source']).parent), 'runtime': config['runtime']}
        result[field] = str(tmp_path / 'different')
        return result
    monkeypatch.setattr('zoo.circle_packing.continuation_binding.verify_bound_fixture_continuation', substituted)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='bound continuation'):
        launch_fixture_controller(config, deadline=clock, directory=tmp_path / 'supervisor')
    assert ledger.snapshot() == before and not starts


def test_supervisor_rechecks_artifacts_after_process_completion(tmp_path, monkeypatch, launch_setup):
    ledger, _, config, clock, _, checks, starts = launch_setup
    from zoo.circle_packing.continuation_binding import verify_bound_fixture_continuation as verify
    def changed_after_launch(*args, **kwargs):
        if starts:
            raise ValueError('bound artifact changed during process')
        return verify(*args, **kwargs)
    monkeypatch.setattr('zoo.circle_packing.continuation_binding.verify_bound_fixture_continuation', changed_after_launch)
    with pytest.raises(ValueError, match='changed during process'):
        launch_fixture_controller(config, deadline=clock, directory=tmp_path / 'supervisor')
    assert len(starts) == 1 and len(checks) == 1
    assert ledger.cell_worker_claim('circle-v2--mori-0') is not None


@pytest.mark.parametrize('bundle', ['source', 'runtime'])
def test_supervisor_cannot_write_inside_continuation_bundle(tmp_path, launch_setup, bundle):
    ledger, _, config, clock, _, _, starts = launch_setup
    root = Path(config['source']).parent.parent if bundle == 'source' else Path(config['runtime']).parent
    root.chmod(0o700)
    before = ledger.snapshot()
    directory = root / 'supervisor'
    with pytest.raises(ValueError, match='overlaps protected paths'):
        launch_fixture_controller(config, deadline=clock, directory=directory)
    assert ledger.snapshot() == before and not directory.exists() and not starts


@pytest.mark.parametrize('bundle', ['source', 'runtime'])
def test_supervisor_rejects_controller_output_inside_continuation_bundle(tmp_path, launch_setup, bundle):
    ledger, _, config, clock, _, _, starts = launch_setup
    root = Path(config['source']).parent.parent if bundle == 'source' else Path(config['runtime']).parent
    config = {**config, 'output': str(root / 'controller-output')}
    before = ledger.snapshot()
    directory = tmp_path / 'supervisor'
    with pytest.raises(ValueError, match='overlaps.*continuation'):
        launch_fixture_controller(config, deadline=clock, directory=directory)
    assert ledger.snapshot() == before and not directory.exists() and not starts


@pytest.mark.parametrize('change', ['seed', 'experiment', 'plan_ref', 'clock'])
def test_supervisor_rejects_changed_original_cell_without_claim(tmp_path, launch_setup, change):
    ledger, _, config, clock, _, _, starts = launch_setup
    altered = copy.deepcopy(config)
    if change == 'seed':
        altered['seed'] = 1
    elif change == 'experiment':
        altered['plan']['experiment_id'] = 'other'
    elif change == 'plan_ref':
        altered['ref'] = 'sha256:' + '0' * 64
    else:
        path = tmp_path / 'other-clock.jsonl'
        path.write_text('')
        altered['clock'] = str(path)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='original cell'):
        launch_fixture_controller(altered, deadline=clock, directory=tmp_path / 'supervisor')
    assert ledger.snapshot() == before and not starts


@pytest.mark.linux
@pytest.mark.parametrize('damage', ['source', 'runtime'])
def test_supervisor_rejects_changed_real_bound_artifacts_before_claim(tmp_path, monkeypatch, damage):
    from test_openevolve_continuation_controller import setup
    ledger, draft, clock, _, source, _, artifacts = setup(tmp_path, monkeypatch)
    config = {'plan': draft, 'ref': 'sha256:' + draft['draft_sha256'], 'runtime_manifest': {},
              'source_manifest': {}, 'source': str(source / 'source/m0'), 'runtime': artifacts['runtime'],
              'ledger': str(ledger.path), 'clock': str(clock._store.path), 'output': str(tmp_path / 'out'),
              'base_url': 'http://127.0.0.1:12345', 'campaign_id': draft['campaign_id'], 'seed': 0}
    path = source / 'source/m0/source.py' if damage == 'source' else Path(artifacts['runtime']) / 'package.py'
    path.write_text('changed after binding')
    before = ledger.snapshot()
    directory = tmp_path / 'supervisor'
    with pytest.raises(ValueError):
        launch_fixture_controller(config, deadline=clock, directory=directory)
    assert ledger.snapshot() == before and not directory.exists()
