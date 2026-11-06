"""The named paired Mori fixture must never accept a real service endpoint."""
import os
import pytest


def config():
    return {'plan': {}, 'ref': 'sha256:' + 'a' * 64, 'runtime_manifest': {}, 'source_manifest': {},
            'source': '/fake/source/m0', 'runtime': '/fake/runtime', 'ledger': '/fake/campaign.db',
            'clock': '/fake/clock.jsonl', 'output': '/fake/output', 'base_url': 'http://127.0.0.1:1234/v1',
            'campaign_id': 'a' * 32, 'seed': 0}


@pytest.mark.parametrize('url', ['https://api.deepseek.com', 'http://localhost:1234/v1',
                                 'http://127.0.0.1:1234/v1?key=secret',
                                 'http://user:password@127.0.0.1/v1'])
def test_fixture_rejects_non_loopback_and_credentialed_urls_before_work(url):
    from zoo.circle_packing.mori_fixture_worker import validate_config
    with pytest.raises(ValueError, match='loopback'):
        validate_config({**config(), 'base_url': url})


def test_fixture_rejects_extra_fields_and_invalid_seed():
    from zoo.circle_packing.mori_fixture_worker import validate_config
    with pytest.raises(ValueError): validate_config({**config(), 'secret': 'fake'})
    with pytest.raises(ValueError): validate_config({**config(), 'seed': True})
    assert validate_config(config())['seed'] == 0


def test_shared_controller_rejects_empty_credential_before_setup(tmp_path):
    from zoo.circle_packing.mori_controller import build_controller
    with pytest.raises(ValueError, match='credential'):
        build_controller(config(), ledger=None, clock=None, runner=None, api_key='')
    assert not list(tmp_path.iterdir())


def test_shared_controller_rejects_credentials_in_persisted_config():
    from zoo.circle_packing.mori_controller import build_controller
    with pytest.raises(ValueError, match='configuration'):
        build_controller({**config(), 'api_key': 'fixture-only-secret'},
                         ledger=None, clock=None, runner=None, api_key='fixture-only-secret')


def test_final_measurement_only_exposes_completed_bound_metrics():
    from zoo.circle_packing.mori_fixture_worker import final_measurement
    metrics = {'test/score': 1.82 / 2.635, 'test/sum_radii': 1.82, 'test/validity': 1.0}
    final = {'state': 'completed', 'candidate_id': 'candidate',
             'evidence': {'evidence': {'candidate_id': 'candidate', 'eval_result': {
                 'status': 'ok', 'metrics': metrics,
                 'contract': {'binding': {'candidate_id': 'candidate', 'split_id': 'final_audit'}}}}}}
    assert final_measurement(final, 'candidate', 2.37) == {
        'validity': 1.0, 'sum_radii': 1.82, 'normalized_score': metrics['test/score'],
        'public_range_threshold': 2.37, 'public_range_condition_met': False}
    assert final_measurement({'state': 'skipped'}, 'candidate', 2.37) is None
    assert final_measurement({'state': 'evaluation_failed'}, 'candidate', 2.37) is None
    with pytest.raises(ValueError):
        final_measurement(final, 'other', 2.37)
    final['evidence']['evidence']['eval_result']['metrics']['test/sum_radii'] = float('nan')
    with pytest.raises(ValueError):
        final_measurement(final, 'candidate', 2.37)


def test_named_fixture_rejects_unmarked_campaign_before_source_or_work(tmp_path):
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.mori_fixture_worker import run
    ledger = campaign_fixture(tmp_path)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='fixture campaign'):
        run({**config(), 'ledger': str(ledger.path)})
    assert ledger.snapshot() == before


def test_fixture_supervisor_rejects_unmarked_campaign_before_creating_files(tmp_path):
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.mori_supervisor import launch_fixture_controller
    ledger = campaign_fixture(tmp_path)
    before = ledger.snapshot()
    output = tmp_path / 'controller'
    with pytest.raises(ValueError, match='fixture campaign'):
        launch_fixture_controller({**config(), 'ledger': str(ledger.path)}, deadline=None, directory=output)
    assert ledger.snapshot() == before
    assert not output.exists()


def fixture_campaign(tmp_path):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    return ledger


def test_fixture_creation_cannot_convert_existing_campaign(tmp_path):
    from test_governed_cny_framework import campaign_fixture
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = campaign_fixture(tmp_path)
    before = ledger.snapshot()
    with pytest.raises(FileExistsError):
        CampaignBudget.create_fixture(ledger.path)
    assert ledger.snapshot() == before
    assert not ledger.is_fixture_campaign()
    assert not hasattr(ledger, 'mark_fixture_campaign')


def test_fixture_marker_is_durable_from_creation(tmp_path):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = fixture_campaign(tmp_path)
    assert CampaignBudget(ledger.path).is_fixture_campaign()
    assert not ledger.snapshot()['pending_calls']


def test_live_controller_preparation_rejects_fixture_before_work(tmp_path):
    from zoo.circle_packing.mori_live_controller import prepare_live_controller
    ledger = fixture_campaign(tmp_path)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='non-fixture'):
        prepare_live_controller({**config(), 'ledger': str(ledger.path)}, api_key='fixture-only-secret')
    assert ledger.snapshot() == before


def test_live_host_consumes_key_from_environment_before_preparation(monkeypatch):
    from zoo.circle_packing import mori_live_worker
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-only-secret')
    observed = []
    def prepare(value, *, api_key):
        assert 'DEEPSEEK_API_KEY' not in os.environ
        observed.append(api_key == 'fixture-only-secret')
        return 'prepared'
    monkeypatch.setattr(mori_live_worker, '_prepare', prepare)
    assert mori_live_worker.prepare(config()) == 'prepared'
    assert observed == [True]
    with pytest.raises(ValueError, match='credential'):
        mori_live_worker.prepare(config())
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-only-secret')
    def fail(*args, **kwargs):
        raise RuntimeError('preparation failed')
    monkeypatch.setattr(mori_live_worker, '_prepare', fail)
    with pytest.raises(RuntimeError, match='preparation failed'):
        mori_live_worker.prepare(config())
    assert 'DEEPSEEK_API_KEY' not in os.environ


def test_live_run_fails_closed_before_preparation_when_gate_is_incomplete(monkeypatch):
    from zoo.circle_packing import mori_live_worker
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-only-secret')
    monkeypatch.setattr(mori_live_worker, '_prepare',
                        lambda *args, **kwargs: pytest.fail('closed gate attempted preparation'))
    with pytest.raises(ValueError, match='pilot gate'):
        mori_live_worker.run(config())
    assert 'DEEPSEEK_API_KEY' not in os.environ


def test_live_supervisor_closed_gate_does_not_claim_or_create_files(tmp_path):
    from zoo.circle_packing.mori_supervisor import launch_live_controller
    target = tmp_path / 'controller'
    with pytest.raises(ValueError, match='pilot gate'):
        launch_live_controller(config(), deadline=None, directory=target, api_key='fixture-only-secret')
    assert not target.exists()


def test_reference_live_host_discards_environment_key_before_closed_gate(tmp_path, monkeypatch):
    from zoo.circle_packing import reference_live_worker
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-only-secret')
    monkeypatch.setattr(reference_live_worker, '_prepare',
                        lambda *args, **kwargs: pytest.fail('closed gate attempted preparation'))
    with pytest.raises(ValueError, match='pilot gate'):
        reference_live_worker.run({'output': str(tmp_path / 'reference')})
    assert 'DEEPSEEK_API_KEY' not in os.environ
    assert not (tmp_path / 'reference').exists()


def test_reference_live_supervisor_closed_gate_does_not_create_files(tmp_path):
    from zoo.circle_packing.mori_supervisor import launch_reference_live_controller
    target = tmp_path / 'reference-supervisor'
    with pytest.raises(ValueError, match='pilot gate'):
        launch_reference_live_controller(config(), deadline=None, directory=target, api_key='fixture-only-secret')
    assert not target.exists()


@pytest.mark.parametrize('arm', ['mori', 'vendor'])
def test_live_cell_coordinator_closed_gate_does_not_start_clock(tmp_path, monkeypatch, arm):
    from zoo.circle_packing.live_cell import start_live_cell
    monkeypatch.setattr('zoo.circle_packing.cell_deadline.CellDeadline.start',
                        lambda *args, **kwargs: pytest.fail('closed gate started a cell'))
    with pytest.raises(ValueError, match='pilot gate'):
        start_live_cell(arm, config(), directory=tmp_path / 'supervisor', api_key='fixture-only-secret')
    assert not (tmp_path / 'supervisor').exists()


@pytest.mark.parametrize('arm', ['mori', 'vendor'])
def test_later_seed_refuses_before_first_pair_is_verified(tmp_path, monkeypatch, arm):
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.live_cell import start_live_cell
    ledger = campaign_fixture(tmp_path)
    policy = ledger.manifest_binding()
    cfg = {**config(), 'seed': 1, 'ledger': str(ledger.path), 'campaign_id': policy['campaign_id'],
           'base_url': policy['provider_base_url'], 'clock': str(tmp_path / 'clock.jsonl')}
    if arm == 'vendor':
        cfg.update(worker_directory=str(tmp_path / 'worker'), workspace=str(tmp_path / 'workspace'))
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    monkeypatch.setattr('zoo.circle_packing.pilot_plan.validate_draft_cell',
                        lambda *args, **kwargs: {'wallclock_seconds': 30})
    monkeypatch.setattr('zoo.circle_packing.cell_deadline.CellDeadline.start',
                        lambda *args, **kwargs: pytest.fail('unverified seed started a clock'))
    with pytest.raises(ValueError, match='first pair'):
        start_live_cell(arm, cfg, directory=tmp_path / 'supervisor', api_key='fixture-only-secret')
    assert not (tmp_path / 'clock.jsonl').exists()


@pytest.mark.parametrize('failure', ['source', 'containment'])
def test_live_cell_preflight_failure_does_not_claim_deadline(tmp_path, monkeypatch, failure):
    from contextlib import contextmanager
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.live_cell import start_live_cell
    ledger = campaign_fixture(tmp_path)
    policy = ledger.manifest_binding()
    cfg = {**config(), 'ledger': str(ledger.path), 'campaign_id': policy['campaign_id'],
           'base_url': policy['provider_base_url'], 'clock': str(tmp_path / 'clock.jsonl')}
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.pilot_plan.validate_draft_cell',
                        lambda *args, **kwargs: {'wallclock_seconds': 30})
    if failure == 'containment':
        monkeypatch.setattr('zoo.circle_packing.mori_supervisor.preflight_live_controller', lambda *a, **k: None)
        @contextmanager
        def unavailable():
            raise ValueError('containment unavailable')
            yield
        monkeypatch.setattr('zoo.circle_packing.cell_containment.delegated_cell_group', unavailable)
    before = ledger.snapshot()['journal_head']
    with pytest.raises((ValueError, OSError)):
        start_live_cell('mori', cfg, directory=tmp_path / 'supervisor', api_key='fixture-only-secret')
    assert ledger.snapshot()['journal_head'] == before
    assert ledger.cell_deadline_claim('mori-0') is None
    assert not (tmp_path / 'clock.jsonl').exists()


def test_resume_unstarted_cell_uses_original_clock_and_refuses_started_worker(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from core.composition.recovery import ContinuationStore
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.live_cell import resume_unstarted_live_cell
    ledger = campaign_fixture(tmp_path)
    policy = ledger.manifest_binding()
    cfg = {**config(), 'ledger': str(ledger.path), 'campaign_id': policy['campaign_id'],
           'base_url': policy['provider_base_url'], 'clock': str(tmp_path / 'clock.jsonl')}
    clock = CellDeadline.start(ContinuationStore(cfg['clock']), lifecycle=CellLifecycle(ledger),
                               cell_id='mori-0', plan_ref=cfg['ref'], seconds=30)
    record = dict(clock._record)
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.pilot_plan.validate_draft_cell',
                        lambda *args, **kwargs: {'wallclock_seconds': 30})
    monkeypatch.setattr('zoo.circle_packing.mori_supervisor.preflight_live_controller', lambda *a, **k: None)
    monkeypatch.setattr('zoo.circle_packing.cell_containment.delegated_cell_group', lambda: nullcontext(tmp_path))
    launches = []
    def launch(_config, *, deadline, **kwargs):
        assert deadline._record == record
        launches.append(True)
        return {'returncode': 0}
    monkeypatch.setattr('zoo.circle_packing.mori_supervisor._launch_controller', launch)
    assert resume_unstarted_live_cell('mori', cfg, directory=tmp_path / 'supervisor',
                                      api_key='fixture-only-secret') == {'returncode': 0}
    assert launches == [True]
    ledger.claim_cell_worker('mori-0', record['record_sha256'], 'b' * 64)
    with pytest.raises(ValueError, match='already.*claim'):
        resume_unstarted_live_cell('mori', cfg, directory=tmp_path / 'other', api_key='fixture-only-secret')
    assert launches == [True]


@pytest.mark.parametrize('arm', ['mori', 'vendor'])
def test_later_seed_supervisor_refuses_before_any_launch(tmp_path, monkeypatch, arm):
    from zoo.circle_packing.mori_supervisor import launch_live_controller, launch_reference_live_controller
    cfg = {**config(), 'seed': 1}
    if arm == 'vendor':
        cfg.update(worker_directory=str(tmp_path / 'worker'), workspace=str(tmp_path / 'workspace'))
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    launch = launch_reference_live_controller if arm == 'vendor' else launch_live_controller
    with pytest.raises(ValueError, match='first pair'):
        launch(cfg, deadline=None, directory=tmp_path / 'supervisor', api_key='fixture-only-secret')


def test_recorded_only_currency_bridge_refuses_live_binding():
    from types import SimpleNamespace
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    bridge = CNYInvocationBridge(None, recorded_only=True)
    with pytest.raises(ValueError, match='recorded'):
        bridge.bind_run(SimpleNamespace(mode='live'))


def test_reference_recorded_bridge_cannot_be_constructed_for_live_work():
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    with pytest.raises(ValueError, match='recorded'):
        CNYInvocationBridge(None, recorded_reference=True)


def test_pair_audit_requires_reference_currency_evidence():
    from zoo.circle_packing.pair_audit import audit_pair_snapshot
    with pytest.raises(ValueError, match='pinned evidence'):
        audit_pair_snapshot(seed=0, plan={}, expected_plan_ref='', mori_rows=[], mori_rows_sha256='',
            mori_view=None, mori_clock=None, mori_run_id='', reference_rows=[], reference_view=None,
            reference_clock=None, reference_run_id='', reference_worker_directory='', reference_bundle={})


def test_reference_currency_prefix_accepts_later_campaign_events_and_rejects_changes():
    from zoo.circle_packing.pair_audit import _require_currency_prefix
    first = {'seq': 1, 'sha256': 'a' * 64, 'payload': 'first'}
    second = {'seq': 2, 'sha256': 'b' * 64, 'payload': 'second'}
    original = {'policy_json': 'same', 'events': [first], 'journal_head': {'seq': 1, 'sha256': 'a' * 64}}
    common = {'policy_json': 'same', 'events': [first, second]}
    _require_currency_prefix(original, common)
    with pytest.raises(ValueError, match='prefix'):
        _require_currency_prefix(original, {**common, 'events': [{**first, 'payload': 'changed'}, second]})


def test_recorded_replay_cli_removes_key_before_reading_config(tmp_path, monkeypatch):
    import sys
    from zoo.circle_packing import mori_recorded
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-only-secret')
    monkeypatch.setattr(sys, 'argv', ['mori_recorded', str(tmp_path / 'missing'), 'input', 'digest', '{}', 'output'])
    with pytest.raises(FileNotFoundError):
        mori_recorded.main()
    assert 'DEEPSEEK_API_KEY' not in os.environ


def test_recorded_mori_setup_needs_no_provider_key_and_refuses_live_run(tmp_path):
    from core.loop import Framework, LoopConfig
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.circle_packing.governed import governed_setup
    ledger = fixture_campaign(tmp_path)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=ledger, api_key=None, seed=0,
        iterations=1, base_url='http://127.0.0.1:1234/v1', max_completion_tokens=4, recorded_only=True)
    assert provider._api_key is None
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    framework = Framework.from_profile(profile, provider, CirclePackingDomain(tmp_path / 'domain'), cfg,
                                       str(tmp_path / 'framework'), component_registry=registry)
    with pytest.raises(ValueError, match='recorded-only'):
        framework.evolve('test replay must not dispatch')
    assert not ledger.snapshot()['pending_calls']


@pytest.mark.linux
def test_live_supervisor_hands_key_only_to_child_environment(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from core.composition.recovery import ContinuationStore
    from core.executor.process import ProcessJournal
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.mori_supervisor import launch_live_controller
    ledger = campaign_fixture(tmp_path)
    policy = ledger.manifest_binding()
    ref = 'sha256:' + 'a' * 64
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='mori-0', plan_ref=ref, seconds=30)
    source, runtime = tmp_path / 'source' / 'm0', tmp_path / 'runtime'
    source.mkdir(parents=True)
    runtime.mkdir()
    cfg = {**config(), 'ledger': str(ledger.path), 'clock': str(clock._store.path),
           'source': str(source), 'runtime': str(runtime), 'output': str(tmp_path / 'output'),
           'campaign_id': policy['campaign_id'], 'base_url': policy['provider_base_url'], 'ref': ref}
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    (tmp_path / 'test-cgroup').mkdir()
    monkeypatch.setattr('zoo.circle_packing.cell_containment.delegated_cell_group',
                        lambda: nullcontext(tmp_path / 'test-cgroup'))
    monkeypatch.setattr('zoo.circle_packing.pilot_plan.validate_draft_cell',
                        lambda *a, **k: {'campaign_id': policy['campaign_id'], 'wallclock_seconds': 30})
    monkeypatch.setattr('zoo.circle_packing.frozen_source.verify_frozen_source', lambda *a, **k: None)
    monkeypatch.setattr('zoo.circle_packing.frozen_runtime.verify_frozen_runtime', lambda *a, **k: None)
    launches = []
    def launch(self, args, cwd, env, timeout, metadata, **kwargs):
        assert env['DEEPSEEK_API_KEY'] == 'fixture-only-secret'
        assert 'fixture-only-secret' not in repr(args) + repr(metadata)
        from core.x1.checkpoint import payload_digest
        binding = metadata['containment_binding']
        info = (tmp_path / 'test-cgroup').stat()
        assert binding['containment_identity'] == {'device': info.st_dev, 'inode': info.st_ino}
        assert binding['supervisor_pid'] == os.getpid()
        assert binding['boot_id'] == clock._record['boot_id']
        assert payload_digest(binding) == metadata['worker_ref']
        assert ledger.cell_worker_claim('mori-0')['worker_ref'] == metadata['worker_ref']
        launches.append(1)
        return None, {}
    monkeypatch.setattr(ProcessJournal, 'launch', launch)
    monkeypatch.setattr(ProcessJournal, 'wait', lambda *a, **k: {'returncode': 0})
    directory = tmp_path / 'controller'
    launch_live_controller(cfg, deadline=clock, directory=directory, api_key='fixture-only-secret')
    assert launches == [1] and ledger.cell_worker_claim('mori-0') is not None
    for path in directory.rglob('*'):
        if path.is_file() and not path.is_symlink():
            assert b'fixture-only-secret' not in path.read_bytes()


def test_shared_controller_rejects_mismatched_ledger_before_setup(tmp_path):
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.mori_controller import build_controller
    ledger = campaign_fixture(tmp_path)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='ledger'):
        build_controller({**config(), 'ledger': str(tmp_path / 'other.db')},
                         ledger=ledger, clock=None, runner=None, api_key='fixture-only-secret')
    assert ledger.snapshot() == before


def test_shared_controller_rejects_loopback_for_real_campaign(tmp_path):
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.mori_controller import build_controller
    ledger = campaign_fixture(tmp_path)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='campaign provider'):
        build_controller({**config(), 'ledger': str(ledger.path)},
                         ledger=ledger, clock=None, runner=None, api_key='fixture-only-secret')
    assert ledger.snapshot() == before


def test_shared_controller_rejects_remote_for_fixture_campaign(tmp_path):
    from zoo.circle_packing.mori_controller import build_controller
    ledger = fixture_campaign(tmp_path)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='loopback'):
        build_controller({**config(), 'ledger': str(ledger.path), 'base_url': 'https://api.deepseek.com'},
                         ledger=ledger, clock=None, runner=None, api_key='fixture-only-secret')
    assert ledger.snapshot() == before


def test_shared_controller_rejects_wrong_campaign_and_clock_before_setup(tmp_path):
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.mori_controller import build_controller
    ledger = campaign_fixture(tmp_path)
    policy, before = ledger.manifest_binding(), ledger.snapshot()
    cfg = {**config(), 'ledger': str(ledger.path), 'base_url': policy['provider_base_url']}
    with pytest.raises(ValueError, match='campaign'):
        build_controller(cfg, ledger=ledger, clock=None, runner=None, api_key='fixture-only-secret')
    with pytest.raises(ValueError, match='clock'):
        build_controller({**cfg, 'campaign_id': policy['campaign_id']}, ledger=ledger, clock=None,
                         runner=None, api_key='fixture-only-secret')
    assert ledger.snapshot() == before


def test_fixture_supervisor_rejects_missing_clock_before_creating_files(tmp_path):
    from zoo.circle_packing.mori_supervisor import launch_fixture_controller
    ledger = fixture_campaign(tmp_path)
    before = ledger.snapshot()
    output = tmp_path / 'controller'
    with pytest.raises(ValueError, match='cell deadline'):
        launch_fixture_controller({**config(), 'ledger': str(ledger.path)}, deadline=None, directory=output)
    assert ledger.snapshot() == before
    assert not output.exists()


@pytest.mark.linux
def test_fixture_supervisor_claims_cell_once_before_start(tmp_path, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.mori_supervisor import launch_fixture_controller
    ledger = fixture_campaign(tmp_path)
    ref = 'sha256:' + 'a' * 64
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'),
        lifecycle=CellLifecycle(ledger), cell_id='mori-0', plan_ref=ref, seconds=30)
    source = tmp_path / 'source' / 'm0'
    runtime = tmp_path / 'runtime'
    source.mkdir(parents=True)
    runtime.mkdir()
    campaign_id = ledger.manifest_binding()['campaign_id']
    cfg = {**config(), 'ledger': str(ledger.path), 'clock': str(deadline._store.path),
           'source': str(source), 'runtime': str(runtime), 'output': str(tmp_path / 'output'),
           'campaign_id': campaign_id, 'ref': ref}
    monkeypatch.setattr('zoo.circle_packing.pilot_plan.validate_draft_cell',
                        lambda *a, **k: {'campaign_id': campaign_id, 'wallclock_seconds': 30})
    monkeypatch.setattr('zoo.circle_packing.frozen_source.verify_frozen_source', lambda *a, **k: None)
    monkeypatch.setattr('zoo.circle_packing.frozen_runtime.verify_frozen_runtime', lambda *a, **k: None)
    starts = []
    monkeypatch.setattr(ProcessJournal, 'launch', lambda *a, **k: (starts.append(True), {}))
    monkeypatch.setattr(ProcessJournal, 'wait', lambda *a, **k: {'returncode': 0})
    launch_fixture_controller(cfg, deadline=deadline, directory=tmp_path / 'first')
    assert ledger.cell_worker_claim('mori-0') is not None
    with pytest.raises(ValueError, match='claimed'):
        launch_fixture_controller(cfg, deadline=deadline, directory=tmp_path / 'second')
    assert len(starts) == 1


def test_fixture_campaign_cannot_bind_real_provider(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_governed_cny_framework import framework, CountedProvider
    ledger = fixture_campaign(tmp_path)
    def forbidden(*args, **kwargs):
        raise RuntimeError('fixture would reach a real provider')
    monkeypatch.setattr(CountedProvider, 'perform_request', forbidden)
    with pytest.raises(ValueError, match='fixture.*loopback'):
        fw, *_ = framework(tmp_path / 'run', ledger, SimpleNamespace(url='https://api.deepseek.com'))
        fw.evolve('fixture task')
