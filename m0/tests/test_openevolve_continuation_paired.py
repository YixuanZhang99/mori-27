"""A first paired continuation shares one fixture campaign and frozen identity."""
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
from test_openevolve_continuation_reference_evolve import assert_iteration_trace
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.continuation_binding import bind_fixture_continuation
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
from zoo.circle_packing.pilot_matrix import snapshot_continuation_matrix
from zoo.mle_bench_lite.composed_domain import SandboxRunner

pytestmark = pytest.mark.linux


def assert_mori_record(rows):
    final = [row['payload'] for row in rows if row['kind'] == 'metric_final_completed']
    assert len(final) == 1 and final[0]['state'] == 'completed'
    assert final[0]['evidence']['evidence']['eval_result']['metrics']['test/validity'] == 1.0
    assert [row['payload']['cycle'] for row in rows if row['kind'] == 'composed_cycle_started'] == list(range(7))
    decisions = [row for row in rows if row['kind'] == 'composed_decision']
    assert len(decisions) == 7 and len({row['payload']['candidate_id'] for row in decisions}) == 7


def test_frozen_continuation_pair_shares_campaign_and_preserves_both_arms(tmp_path, local_endpoint):
    cache = os.environ.get('MORI_TEST_OFFLINE_CACHE')
    if not cache:
        pytest.skip('requires an explicitly supplied offline uv cache')
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger, proof = fixture_pair_ledger(tmp_path)
    original = ledger.snapshot()
    draft = build_continuation_draft(ledger.circle_continuation_inventory(expected_head=original['journal_head']),
        experiment_id='circle-v2', source_commit=commit,
        dependency_lock_sha256=hashlib.sha256((checkout / 'm0/uv.lock').read_bytes()).hexdigest(),
        method_changes=['paired loopback fixture'])
    source, bundle = tmp_path / 'source-bundle', tmp_path / 'runtime-bundle'
    artifacts = prepare_continuation_runtime(ledger, draft, checkout=checkout, source_directory=source,
        directory=bundle, uv_cache=cache, base_python='/usr/bin/python3.12')
    bind_fixture_continuation(ledger, draft, checkout=checkout, source_directory=source,
                              runtime_directory=bundle, base_python='/usr/bin/python3.12')
    source_root = source / 'source'
    source_manifest = json.loads((source / 'source-manifest.json').read_text())
    runtime_manifest = json.loads((bundle / 'runtime-manifest.json').read_text())
    ref = 'sha256:' + draft['draft_sha256']
    diff = '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # fixture\n>>>>>>> REPLACE\n'
    local_endpoint.responses.extend(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}])
                                    for _ in range(16))
    mori_clock = CellDeadline.start(ContinuationStore(tmp_path / 'mori-clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--mori-0', plan_ref=ref, seconds=draft['limits']['wallclock_seconds'])
    ledger.claim_cell_worker('circle-v2--mori-0', mori_clock._record['record_sha256'], 'a' * 64)
    cfg = {'plan': draft, 'ref': ref, 'runtime_manifest': {}, 'source_manifest': {},
           'source': str(source_root / 'm0'), 'runtime': artifacts['runtime'], 'ledger': str(ledger.path),
           'clock': str(tmp_path / 'mori-clock.jsonl'), 'output': str(tmp_path / 'mori'),
           'base_url': local_endpoint.url, 'campaign_id': draft['campaign_id'], 'seed': 0}
    cfg_path = tmp_path / 'config.json'
    fd = os.open(cfg_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream: json.dump(cfg, stream)
    env = {'PATH': os.defpath, 'HOME': str(tmp_path), 'PYTHONPATH': cfg['source'],
           'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    executable = str(Path(artifacts['runtime']) / 'bin/python')
    process = subprocess.run([executable, '-m', 'zoo.circle_packing.mori_fixture_worker', str(cfg_path)],
                             cwd=cfg['source'], env=env, capture_output=True, text=True, timeout=900)
    assert process.returncode == 0, process.stderr[-4000:]
    mori = json.loads(process.stdout)
    assert mori['mode'] == 'fixture' and not mori['performance_claim'] and mori['replay_passed']
    assert mori['executable'] == executable and Path(cfg['source']) in Path(mori['source']).resolve().parents
    mori_rows = [json.loads(line) for line in (tmp_path / 'mori/framework/x1.jsonl').read_text().splitlines()]
    assert_mori_record(mori_rows)
    assert len(local_endpoint.requests) == 6
    mid = ledger.snapshot()
    assert not mid['pending_calls'] and not mid['protected_micro_cny'] and not mid['protection_breaches']
    vendor_clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--vendor-0', plan_ref=ref, seconds=draft['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_fixture_continuation(ledger, draft=draft, source_directory=source,
        runtime_directory=bundle, base_python='/usr/bin/python3.12')
    authority = build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=draft,
        expected_plan_ref=ref, expected_campaign_id=draft['campaign_id'], deadline=vendor_clock,
        snapshot=source_root, source_manifest=source_manifest, runner=runner,
        api_key='fixture-only-secret', base_url=local_endpoint.url)
    try:
        with tempfile.TemporaryDirectory(prefix='mori-pair-', dir='/tmp') as directory:
            vendor = run_reference_cell_fixture(authority, vendor_clock, tmp_path / 'worker', Path(directory),
                snapshot=source_root, source_manifest=source_manifest, frozen_plan=draft, expected_plan_ref=ref,
                expected_campaign_id=draft['campaign_id'], runtime=artifacts['runtime'],
                runtime_manifest=runtime_manifest, base_python='/usr/bin/python3.12', iterations=6)
        assert vendor['state'] == 'completed' and not vendor['performance_claim']
        report = json.loads(Path(vendor['worker_proof']['started']['stdout_path']).read_text())
        assert_iteration_trace(report)
        assert all(row['state'] == 'candidate' for row in report['iteration_trace']['iterations'])
        assert len(local_endpoint.requests) == 12
        assert all(json.loads(request)['thinking'] == {'type': 'disabled'} for request in local_endpoint.requests)
        assert authority.dispatch.audit()['currency']['protection_valid']
        after = ledger.snapshot()
        assert after['settled_upper_bound_micro_cny'] > mid['settled_upper_bound_micro_cny'] > original['settled_upper_bound_micro_cny']
        assert not after['pending_calls'] and not after['protected_micro_cny'] and not after['protection_breaches']
        assert ledger.first_pair_audit() == proof
        inventory = snapshot_continuation_matrix(ledger, draft, expected_plan_ref=ref, expected_head=after['journal_head'])
        assert {c['cell_id'] for c in inventory['cells'] if c['state'] == 'claimed_outcome_unverified'} == {
            'circle-v2--mori-0', 'circle-v2--vendor-0'}
        from zoo.circle_packing.cell_deadline import RecordedCellClock
        from zoo.circle_packing.pilot_matrix import report_continuation_currency
        from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
        clocks = {'circle-v2--mori-0': mori_clock, 'circle-v2--vendor-0': vendor_clock}
        with ledger._transaction() as (_db, _policy, state):
            runs = {binding['cell_id']: (run_id, state['governance']['runs'][run_id]['plan_ref'])
                    for run_id, binding in state['governance']['deadline_bindings'].items()
                    if binding['cell_id'] in clocks}
        assert set(runs) == set(clocks)
        evidence = {}
        for name, clock in clocks.items():
            run_id, physical_ref = runs[name]
            view = RecordedCurrencyView(ledger.export_governance_evidence(run_id, physical_ref),
                expected_run_id=run_id, expected_plan_ref=physical_ref, expected_head=after['journal_head'])
            evidence[name] = {'view': view, 'clock': RecordedCellClock(
                clock.export_evidence(), view.cell_deadline_claim(name))}
        report = report_continuation_currency(ledger, draft, expected_plan_ref=ref,
            expected_head=after['journal_head'], cell_evidence=evidence)
        costs = {cell['cell_id']: cell['currency']['settled_upper_bound_micro_cny']
                 for cell in report['cells'] if cell['currency'] is not None}
        assert costs == {'circle-v2--mori-0': 228, 'circle-v2--vendor-0': 228}
        assert ledger.snapshot() == after
    finally:
        authority.close()
