"""The named paired Mori fixture must never accept a real service endpoint."""
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
