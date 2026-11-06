"""Frozen upstream reference cell, original fixture ledger, and loopback broker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest
from core.composition.recovery import ContinuationStore
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_continuation_event import fixture_pair_ledger
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.continuation_binding import bind_fixture_continuation
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
from zoo.mle_bench_lite.composed_domain import SandboxRunner

pytestmark = pytest.mark.linux


def assert_iteration_trace(report):
    """Check submitted and completed iteration identities without hiding failures."""
    trace = report['iteration_trace']
    controller = trace['controller_run']
    assert controller['start_iteration'] == 1 and controller['max_iterations'] == 6
    assert controller['reported_completed_iterations'] == 6 and controller['stop_reason'] == 'iteration_limit'
    rows = trace['iterations']
    assert [row['iteration'] for row in rows] == list(range(1, 7))
    assert all(row['state'] in {'candidate', 'worker_error'} for row in rows)
    requests = trace['request_bindings']
    assert [row['iteration'] for row in requests] == list(range(1, 7))
    assert len({row['request_id'] for row in requests}) == 6


def test_versioned_reference_six_iterations_use_original_fixture_budget(tmp_path, local_endpoint):
    cache = os.environ.get('MORI_TEST_OFFLINE_CACHE')
    if not cache:
        pytest.skip('requires an explicitly supplied offline uv cache')
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger, proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    draft = build_continuation_draft(ledger.circle_continuation_inventory(expected_head=before['journal_head']),
        experiment_id='circle-v2', source_commit=commit,
        dependency_lock_sha256=hashlib.sha256((checkout / 'm0/uv.lock').read_bytes()).hexdigest(),
        method_changes=['reference loopback fixture'])
    source, bundle = tmp_path / 'source-bundle', tmp_path / 'runtime-bundle'
    artifacts = prepare_continuation_runtime(ledger, draft, checkout=checkout, source_directory=source,
        directory=bundle, uv_cache=cache, base_python='/usr/bin/python3.12')
    bind_fixture_continuation(ledger, draft, checkout=checkout, source_directory=source,
                              runtime_directory=bundle, base_python='/usr/bin/python3.12')
    source_root = source / 'source'
    source_manifest = json.loads((source / 'source-manifest.json').read_text())
    runtime_manifest = json.loads((bundle / 'runtime-manifest.json').read_text())
    ref = 'sha256:' + draft['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--vendor-0', plan_ref=ref, seconds=draft['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_fixture_continuation(ledger, draft=draft, source_directory=source,
        runtime_directory=bundle, base_python='/usr/bin/python3.12')
    authority = build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=draft,
        expected_plan_ref=ref, expected_campaign_id=draft['campaign_id'], deadline=clock,
        snapshot=source_root, source_manifest=source_manifest, runner=runner,
        api_key='fixture-only-secret', base_url=local_endpoint.url)
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    local_endpoint.responses.extend(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}])
                                    for _ in range(6))
    try:
        with tempfile.TemporaryDirectory(prefix='mori-ref-', dir='/tmp') as directory:
            result = run_reference_cell_fixture(authority, clock, tmp_path / 'worker', Path(directory),
                snapshot=source_root, source_manifest=source_manifest, frozen_plan=draft,
                expected_plan_ref=ref, expected_campaign_id=draft['campaign_id'], runtime=artifacts['runtime'],
                runtime_manifest=runtime_manifest, base_python='/usr/bin/python3.12', iterations=6)
        assert result['state'] == 'completed' and result['mode'] == 'fixture' and not result['performance_claim']
        assert result['selected_program']['metrics']['validity'] == 1.0
        report_path = Path(result['worker_proof']['started']['stdout_path'])
        assert_iteration_trace(json.loads(report_path.read_text()))
        assert len(local_endpoint.requests) == 6
        assert all(json.loads(request)['thinking'] == {'type': 'disabled'} for request in local_endpoint.requests)
        assert authority.dispatch.audit()['currency']['protection_valid']
        assert authority.stages.audit()['stage_calls'] >= 3
        assert authority.budget.audit_governance()['physical_totals']['token'] == 42
        after = ledger.snapshot()
        assert not after['pending_calls'] and not after['protected_micro_cny'] and not after['protection_breaches']
        assert after['settled_upper_bound_micro_cny'] > before['settled_upper_bound_micro_cny']
        assert ledger.first_pair_audit() == proof
    finally:
        authority.close()
