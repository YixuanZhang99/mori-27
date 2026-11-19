"""Reference authority belongs to the new fixture experiment, not the old pilot."""
import copy
import json
from pathlib import Path
import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_provider import local_endpoint
from test_openevolve_continuation_binding import prepared, bind
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.mle_bench_lite.composed_domain import SandboxRunner

pytestmark = pytest.mark.linux


def setup(tmp_path, monkeypatch, local_endpoint):
    values = prepared(tmp_path, monkeypatch)
    ledger, proof, _, draft, _, source, runtime, artifacts = values
    bind(values)
    ref = 'sha256:' + draft['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock-vendor.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--vendor-0', plan_ref=ref, seconds=2700)
    runner = SandboxRunner.for_fixture_continuation(ledger, draft=draft, source_directory=source,
        runtime_directory=runtime, base_python='/usr/bin/python3.12')
    manifest = json.loads((source / 'source-manifest.json').read_text())
    options = dict(ledger=ledger, plan=draft, expected_plan_ref=ref, expected_campaign_id=draft['campaign_id'],
        deadline=clock, snapshot=source / 'source', source_manifest=manifest, runner=runner,
        api_key='fixture-only-secret', base_url=local_endpoint.url)
    return options, proof, artifacts


def test_reference_authority_uses_new_fixture_plan_and_protocol(tmp_path, monkeypatch, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options, proof, artifacts = setup(tmp_path, monkeypatch, local_endpoint)
    ledger, clock = options['ledger'], options['deadline']
    before = ledger.snapshot()
    with build_reference_authorities(tmp_path / 'reference', **options) as authority:
        assert authority.bridge.cell_deadline() is clock
        assert authority.control.domain.runner.manifest_binding['runtime_ref'] == artifacts['runtime_ref']
        assert authority.stages.runner.manifest_binding['runtime_ref'] == artifacts['runtime_ref']
        assert authority.budget.options['limits']['global'] == {
            key: options['plan']['limits'][key] for key in ('token', 'node', 'eval_count')}
        for provider in authority.run.provider_sessions.values():
            manifest = provider.manifest_binding()
            assert manifest['reasoning_effort'] == 'none' and manifest['thinking'] == {'type': 'disabled'}
        assert ledger.reference_authority_claim('circle-v2--vendor-0') is not None
        assert ledger.first_pair_audit() == proof
        assert not ledger.snapshot()['pending_calls'] and not local_endpoint.requests
        assert ledger.snapshot()['settled_upper_bound_micro_cny'] == before['settled_upper_bound_micro_cny']


@pytest.mark.parametrize('damage', ['plan', 'source', 'reference', 'runtime'])
def test_reference_rejects_other_version_or_tampered_artifacts_before_claim(tmp_path, monkeypatch, local_endpoint, damage):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options, _, artifacts = setup(tmp_path, monkeypatch, local_endpoint)
    ledger = options['ledger']
    if damage == 'plan':
        options['plan'] = copy.deepcopy(options['plan']); options['plan']['reasoning_effort'] = 'low'
    elif damage == 'source': options['source_manifest'] = {}
    elif damage == 'reference': options['expected_plan_ref'] = 'sha256:' + '0' * 64
    else: (Path(artifacts['runtime']) / 'package.py').write_text('tampered')
    before = ledger.snapshot()
    with pytest.raises(ValueError): build_reference_authorities(tmp_path / 'reference', **options)
    assert ledger.snapshot() == before and not (tmp_path / 'reference').exists() and not local_endpoint.requests


def test_reference_runtime_rejects_mori_clock_or_unrelated_bridge(tmp_path, monkeypatch, local_endpoint):
    from types import SimpleNamespace
    from zoo.circle_packing.host_control import _require_campaign_runtime
    options, _, _ = setup(tmp_path, monkeypatch, local_endpoint)
    ledger, runner, draft = options['ledger'], options['runner'], options['plan']
    mori = CellDeadline.start(ContinuationStore(tmp_path / 'mori-clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--mori-0', plan_ref='sha256:' + draft['draft_sha256'], seconds=2700)
    before = ledger.snapshot()
    bridge = SimpleNamespace(ledger=ledger, cell_deadline=lambda: mori)
    with pytest.raises(ValueError, match='vendor clock'):
        _require_campaign_runtime(ledger, runner, bridge=bridge)
    with pytest.raises(ValueError, match='fixture authority'):
        _require_campaign_runtime(ledger, runner)
    assert ledger.snapshot() == before and not local_endpoint.requests
