"""The versioned fixture worker executes against its original frozen authorities."""
import json
from pathlib import Path
import pytest

from test_governed_cny_provider import local_endpoint
from test_openevolve_continuation_reference import setup

pytestmark = pytest.mark.linux


def arguments(tmp_path, monkeypatch, local_endpoint):
    options, _, artifacts = setup(tmp_path, monkeypatch, local_endpoint)
    source = options['snapshot']
    runtime = Path(artifacts['runtime'])
    runtime_manifest = json.loads((runtime.parent / 'runtime-manifest.json').read_text())
    workspace = tmp_path / 'workspace'
    workspace.mkdir(mode=0o700)
    kwargs = dict(readonly_source=source / 'm0', readonly_runtime=runtime,
        frozen_plan=options['plan'], snapshot=source, source_manifest=options['source_manifest'],
        expected_plan_ref=options['expected_plan_ref'], expected_campaign_id=options['expected_campaign_id'],
        runtime_manifest=runtime_manifest, base_python='/usr/bin/python3.12')
    return options, artifacts, workspace, kwargs


def test_versioned_reference_worker_executes_once_under_bound_cell(tmp_path, monkeypatch, local_endpoint):
    from zoo.circle_packing.cell_worker import run_cell_worker
    options, _, workspace, kwargs = arguments(tmp_path, monkeypatch, local_endpoint)
    ledger, clock = options['ledger'], options['deadline']
    result = run_cell_worker(clock, tmp_path / 'worker', workspace, ['/bin/sh', '-c', 'printf fixture'], **kwargs)
    assert result['state'] == 'completed' and result['returncode'] == 0
    claim = ledger.cell_worker_claim('circle-v2--vendor-0')
    assert claim is not None and claim['deadline_ref'] == clock._record['record_sha256']
    assert not ledger.snapshot()['pending_calls'] and not local_endpoint.requests
    with pytest.raises(ValueError):
        run_cell_worker(clock, tmp_path / 'second', workspace, ['/bin/true'], **kwargs)


@pytest.mark.parametrize('damage', ['source_manifest', 'runtime_manifest', 'runtime', 'source', 'campaign'])
def test_versioned_worker_rejects_changed_authority_before_claim(tmp_path, monkeypatch, local_endpoint, damage):
    from zoo.circle_packing.cell_worker import run_cell_worker
    options, artifacts, workspace, kwargs = arguments(tmp_path, monkeypatch, local_endpoint)
    ledger, clock = options['ledger'], options['deadline']
    if damage == 'source_manifest': kwargs['source_manifest'] = []
    elif damage == 'runtime_manifest': kwargs['runtime_manifest'] = {}
    elif damage == 'runtime': (Path(artifacts['runtime']) / 'package.py').write_text('tampered')
    elif damage == 'source': (options['snapshot'] / 'm0/source.py').write_text('tampered')
    else: kwargs['expected_campaign_id'] = 'wrong'
    before = ledger.snapshot()
    with pytest.raises(ValueError):
        run_cell_worker(clock, tmp_path / 'worker', workspace, ['/bin/true'], **kwargs)
    assert ledger.snapshot() == before and not (tmp_path / 'worker').exists()
    assert ledger.cell_worker_claim('circle-v2--vendor-0') is None and not local_endpoint.requests


def test_reference_fixture_preflight_uses_continuation_bundle(tmp_path, monkeypatch, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
    options, artifacts, workspace, kwargs = arguments(tmp_path, monkeypatch, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    try:
        # The tiny source fixture has no named upstream worker. Reaching this
        # check proves both version-specific source and runtime preflight passed.
        with pytest.raises(ValueError, match='named frozen worker'):
            run_reference_cell_fixture(authority, options['deadline'], tmp_path / 'worker', workspace,
                snapshot=options['snapshot'], source_manifest=options['source_manifest'],
                frozen_plan=options['plan'], expected_plan_ref=options['expected_plan_ref'],
                expected_campaign_id=options['expected_campaign_id'], runtime=artifacts['runtime'],
                runtime_manifest=kwargs['runtime_manifest'], base_python='/usr/bin/python3.12')
        assert options['ledger'].cell_worker_claim('circle-v2--vendor-0') is None
        assert not local_endpoint.requests
    finally:
        authority.close()
