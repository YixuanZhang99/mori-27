"""A fixture continuation uses its own plan, clock, runtime and protocol."""
import copy
from pathlib import Path
import pytest

from core.composition.recovery import ContinuationStore
from test_openevolve_continuation_binding import prepared, bind
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle

pytestmark = pytest.mark.linux


def setup(tmp_path, monkeypatch):
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, _, source, runtime, artifacts = values
    bind(values)
    ref = 'sha256:' + draft['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--mori-0', plan_ref=ref, seconds=2700)
    runner = SandboxRunner.for_fixture_continuation(ledger, draft=draft, source_directory=source,
        runtime_directory=runtime, base_python='/usr/bin/python3.12')
    return ledger, draft, clock, runner, source, runtime, artifacts


def test_versioned_cell_validation_is_bound_to_fixture_and_first_seed(tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_plan import validate_draft_cell
    ledger, draft, _, _, _, _, _ = setup(tmp_path, monkeypatch)
    ref = 'sha256:' + draft['draft_sha256']
    cell = validate_draft_cell(ledger, draft, 'circle-v2--mori-0', expected_plan_ref=ref)
    assert cell['cell_id'] == 'circle-v2--mori-0' and cell['campaign_id'] == draft['campaign_id']
    for name in ('circle-v2--mori-1', 'circle-v2--vendor-2', 'other--mori-0', 'mori-0'):
        with pytest.raises(ValueError): validate_draft_cell(ledger, draft, name, expected_plan_ref=ref)
    altered = copy.deepcopy(draft); altered['cells'][0]['seed'] = False
    with pytest.raises(ValueError): validate_draft_cell(ledger, altered, 'circle-v2--mori-0', expected_plan_ref=ref)
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    real = CampaignBudget.create(tmp_path / 'real.db')
    with pytest.raises(ValueError): validate_draft_cell(real, draft, 'circle-v2--mori-0', expected_plan_ref=ref)


def test_controller_and_control_share_continuation_protocol_and_runtime(tmp_path, monkeypatch):
    from zoo.circle_packing.governed import governed_setup
    ledger, draft, clock, runner, _, _, artifacts = setup(tmp_path, monkeypatch)
    before = ledger.snapshot()
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=ledger, api_key='fixture-only-secret',
        seed=0, iterations=draft['iterations'], base_url='http://127.0.0.1:12345',
        max_completion_tokens=draft['max_completion_tokens'], total_token_ceiling=draft['limits']['token'],
        cell_deadline=clock, draft_plan=draft, expected_plan_ref='sha256:' + draft['draft_sha256'], runner=runner)
    control = registry._entries[('provider', 'circle-control')].factory(None, {})
    for instance in (provider, control):
        manifest = instance.manifest_binding()
        assert manifest['reasoning_effort'] == 'none' and manifest['thinking'] == {'type': 'disabled'}
    assert runner.manifest_binding['runtime_ref'] == artifacts['runtime_ref']
    assert runner.independent_runner().manifest_binding['runtime_ref'] == artifacts['runtime_ref']
    assert ledger.snapshot() == before
    (Path(artifacts['runtime']) / 'package.py').write_text('tampered')
    with pytest.raises(ValueError): runner.independent_runner()
    with pytest.raises(ValueError): runner.manifest_binding


def test_real_controller_composition_accepts_bound_versioned_fixture(tmp_path, monkeypatch):
    from zoo.circle_packing.mori_controller import build_controller
    ledger, draft, clock, runner, source, runtime, artifacts = setup(tmp_path, monkeypatch)
    config = {'plan': draft, 'ref': 'sha256:' + draft['draft_sha256'], 'runtime_manifest': {},
              'source_manifest': {}, 'source': str(source / 'source/m0'), 'runtime': artifacts['runtime'],
              'ledger': str(ledger.path), 'clock': str(tmp_path / 'clock.jsonl'),
              'output': str(tmp_path / 'controller'), 'base_url': 'http://127.0.0.1:12345',
              'campaign_id': draft['campaign_id'], 'seed': 0}
    before = ledger.snapshot()
    framework, provider, _profile, _adapters = build_controller(config, ledger=ledger, clock=clock,
        runner=runner, api_key='fixture-only-secret')
    assert framework is not None and provider.manifest_binding()['reasoning_effort'] == 'none'
    assert ledger.snapshot() == before


@pytest.mark.parametrize('changed', ['iterations', 'max_completion_tokens', 'total_token_ceiling'])
def test_continuation_controller_rejects_unfrozen_limits(tmp_path, monkeypatch, changed):
    from zoo.circle_packing.governed import governed_setup
    ledger, draft, clock, runner, *_ = setup(tmp_path, monkeypatch)
    before = ledger.snapshot()
    options = {'ledger': ledger, 'api_key': 'fixture-only-secret', 'seed': 0,
        'iterations': draft['iterations'], 'base_url': 'http://127.0.0.1:12345',
        'max_completion_tokens': draft['max_completion_tokens'], 'total_token_ceiling': draft['limits']['token'],
        'cell_deadline': clock, 'draft_plan': draft, 'expected_plan_ref': 'sha256:' + draft['draft_sha256'],
        'runner': runner}
    options[changed] -= 1
    with pytest.raises(ValueError, match='frozen plan'):
        governed_setup(tmp_path / 'run', **options)
    assert ledger.snapshot() == before
