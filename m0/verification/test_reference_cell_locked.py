"""Explicit locked-environment reference-cell integration; loopback HTTP only.

Run with MORI_TEST_OFFLINE_CACHE pointing to a populated uv cache and
PYTHONPATH=.:tests. This check is not collected by the default pytest suite.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from core.composition.recovery import ContinuationStore
from core.executor.process import ProcessJournal
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint, reply
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime, verify_frozen_runtime
from zoo.circle_packing.frozen_source import freeze_source_plan, verify_frozen_source
from zoo.circle_packing.host_runtime import build_reference_authorities
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.composed_domain import SandboxRunner


@pytest.fixture
def short_workspace():
    with tempfile.TemporaryDirectory(prefix='mori-worker-', dir='/tmp') as directory:
        yield Path(directory).resolve()


@pytest.mark.parametrize('tamper_selection', [False, True, 'artifact', 'process', 'terminal', 'terminal_type', 'path', 'race', 'race_dir', 'six_iterations', 'seal_race'])
def test_reference_cell_uses_production_authorities_with_shared_frozen_runtime(tmp_path, local_endpoint,
                                                                                monkeypatch, tamper_selection,
                                                                                short_workspace):
    iterations = 6 if tamper_selection == 'six_iterations' else 1
    cache = os.environ['MORI_TEST_OFFLINE_CACHE']
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger = campaign_fixture(tmp_path)
    ledger.mark_fixture_campaign()
    lock = hashlib.sha256((checkout / 'm0' / 'uv.lock').read_bytes()).hexdigest()
    plan = build_draft_plan(ledger.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)
    ref, campaign_id = 'sha256:' + plan['draft_sha256'], ledger.manifest_binding()['campaign_id']
    source, runtime = tmp_path / 'source', tmp_path / 'runtime'
    exported = freeze_source_plan(ledger, plan, checkout=checkout, destination=source,
        expected_plan_ref=ref, expected_campaign_id=campaign_id, require_runtime=True)
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=source, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    authority = build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=plan,
        expected_plan_ref=ref, expected_campaign_id=campaign_id, deadline=clock,
        snapshot=source, source_manifest=exported['manifest'], runner=runner,
        api_key='fixture-only-secret', base_url=local_endpoint.url)
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    local_endpoint.responses.extend(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}])
                                    for _ in range(iterations))
    workspace = short_workspace
    from zoo.circle_packing.host_runtime import run_reference_cell_fixture
    swapped = []
    if tamper_selection in ('race', 'race_dir'):
        original_open = os.open
        def replace_after_open(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            if path == 'stdout.txt' and kwargs.get('dir_fd') is not None and not swapped:
                directory = kwargs['dir_fd']
                if tamper_selection == 'race_dir':
                    original_directory = Path(os.readlink('/proc/self/fd/' + str(directory)))
                    original_directory.rename(original_directory.with_name(original_directory.name + '-old'))
                    original_directory.mkdir()
                else:
                    os.rename('stdout.txt', 'stdout-original.txt', src_dir_fd=directory, dst_dir_fd=directory)
                    replacement = original_open('stdout.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                                                dir_fd=directory)
                    try:
                        os.write(replacement, b'not the original worker report')
                    finally:
                        os.close(replacement)
                swapped.append(True)
            return fd
        monkeypatch.setattr(os, 'open', replace_after_open)
        with pytest.raises(ValueError, match='worker process.*changed'):
            run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
                source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
                expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
                base_python='/usr/bin/python3.12', iterations=iterations)
        assert swapped == [True]
        assert len(local_endpoint.requests) == iterations and not ledger.snapshot()['pending_calls']
        authority.close()
        return
    if tamper_selection in ('process', 'terminal', 'terminal_type', 'path'):
        original = ContinuationStore.read
        def changed_worker_start(self, kind=None):
            for row in original(self, kind):
                if kind == 'executor_process_started' and self.path.name == 'worker.jsonl' and any(
                        value['kind'] == 'executor_process_finished' for value in self.rows) and tamper_selection == 'process':
                    row['payload']['worker_ref'] = 'f' * 64
                if kind == 'executor_process_finished' and self.path.name == 'worker.jsonl' and tamper_selection == 'terminal':
                    row['payload']['execution_id'] = 'f' * 32
                if kind == 'executor_process_finished' and self.path.name == 'worker.jsonl' and tamper_selection == 'terminal_type':
                    row['payload']['returncode'] = False
                if kind == 'executor_process_started' and self.path.name == 'worker.jsonl' and tamper_selection == 'path' and any(
                        value['kind'] == 'executor_process_finished' for value in self.rows):
                    alias = tmp_path / 'alternate-worker-stdout'
                    alias.hardlink_to(Path(row['payload']['stdout_path']))
                    row['payload']['stdout_path'] = str(alias)
                yield row
        monkeypatch.setattr(ContinuationStore, 'read', changed_worker_start)
        with pytest.raises(ValueError, match='worker process.*(claim|terminal|path)'):
            run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
                source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
                expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
                base_python='/usr/bin/python3.12', iterations=iterations)
        assert len(local_endpoint.requests) == iterations and not ledger.snapshot()['pending_calls']
        authority.close()
        return
    if tamper_selection == 'artifact':
        from zoo.circle_packing import reference_selection
        original = reference_selection.read_reference_selection
        def change_artifact(path, selected):
            (path / 'host-run' / 'host' / 'best' / 'best_program.py').write_text('changed')
            return original(path, selected)
        monkeypatch.setattr(reference_selection, 'read_reference_selection', change_artifact)
        with pytest.raises(ValueError, match='differs from saved'):
            run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
                source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
                expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
                base_python='/usr/bin/python3.12', iterations=iterations)
        assert len(local_endpoint.requests) == iterations and not ledger.snapshot()['pending_calls']
        authority.close()
        return
    if tamper_selection is True:
        from zoo.circle_packing import host_runtime
        original = host_runtime._read_verified_worker_result
        def changed_report(directory, record):
            result = original(directory, record)
            report = json.loads(result['stdout'])
            report['selected_program']['program_ref'] = 'sha256:' + 'f' * 64
            return {**result, 'stdout': json.dumps(report)}
        monkeypatch.setattr(host_runtime, '_read_verified_worker_result', changed_report)
        with pytest.raises(ValueError, match='unique eligible stage'):
            run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
                source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
                expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
                base_python='/usr/bin/python3.12', iterations=iterations)
        assert len(local_endpoint.requests) == iterations and not ledger.snapshot()['pending_calls']
        authority.close()
        return
    if tamper_selection == 'seal_race':
        original_seal = authority._lease.seal
        def insert_completed_stage_before_seal(callback):
            program = (workspace / 'host-run' / 'host' / 'best' / 'best_program.py').read_text()
            authority.stages.execute('e' * 32, program, stage=1)
            return original_seal(callback)
        monkeypatch.setattr(authority._lease, 'seal', insert_completed_stage_before_seal)
    result = run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
        source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
        expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
        base_python='/usr/bin/python3.12', iterations=iterations)
    assert result['state'] == 'completed'
    assert result['mode'] == 'fixture' and result['performance_claim'] is False
    assert result['selected_program']['metrics']['validity'] == 1.0
    assert result['saved_program_ref'] == result['selected_program']['program_ref']
    assert len(local_endpoint.requests) == iterations and not ledger.snapshot()['pending_calls']
    assert all(b'mori_stage_request_id' not in request for request in local_endpoint.requests)
    assert authority.dispatch.audit()['currency']['protection_valid']
    assert authority.stages.audit()['stage_calls'] >= 3
    if iterations == 1:
        assert authority.stages.audit()['stage_calls'] == (4 if tamper_selection == 'seal_race' else 3)
    assert authority.budget.audit_governance()['physical_totals']['token'] == 7 * iterations
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.reference_selection import (audit_recorded_reference_cascade,
        audit_anchored_reference_physical, audit_anchored_reference_worker, audit_anchored_reference_cell)
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    run_id = authority.dispatch.ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, authority.dispatch.ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    recorded_clock = RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim('vendor-0'))
    request_id = result['stage_request_id']
    def stage_row(kind, request_id):
        return next(row['payload'] for row in authority.budget.store.read(kind)
                    if row['payload']['request_id'] == request_id)
    last = stage_row('host_stage_started', request_id)
    ids = [last['prior_id'], request_id] if last['stage'] == 2 else [request_id]
    recorded = [{kind: stage_row('host_stage_' + kind, item)
                 for kind in ('started', 'completed', 'eligibility')} for item in ids]
    audited = audit_recorded_reference_cascade(view, recorded_clock, run_id, recorded)
    assert audited['metrics'] == result['selected_program']['metrics']
    assert audited['evidence_ref'] == result['stage_evidence_ref']
    rows = list(authority.budget.store.read())
    if iterations == 6:
        assert sum(row['kind'] == 'host_stage_started' and row['payload']['stage'] == 1 and
                   row['payload']['program_ref'] == result['selected_program']['program_ref'] for row in rows) > 1
    snapshot_anchor = view.reference_physical_snapshot(run_id)
    selection_anchor = view.reference_selection(run_id)
    assert selection_anchor['cell_id'] == 'vendor-0'
    assert selection_anchor['selection_sha256'] == payload_digest(result['selected_program'])
    assert selection_anchor['rows_sha256'] == payload_digest(rows)
    assert selection_anchor['sequence'] > snapshot_anchor['sequence']
    with pytest.raises(RuntimeError, match='sealed'):
        authority.stages.execute('f' * 32, 'program', stage=1)
    assert snapshot_anchor['rows_sha256'] == payload_digest(rows)
    assert result['physical_snapshot_ref'] == 'sha256:' + snapshot_anchor['rows_sha256']
    worker_proof = result['worker_proof']
    assert snapshot_anchor['worker_proof_sha256'] == payload_digest(worker_proof)
    from zoo.circle_packing.host_runtime import _read_verified_worker_result
    process_output = _read_verified_worker_result(tmp_path / 'worker', worker_proof['started'])
    verified_worker = audit_anchored_reference_worker(view, recorded_clock, run_id, worker_proof,
        stdout=process_output['stdout'], stderr=process_output['stderr'], selected=result['selected_program'])
    assert verified_worker['worker_ref'] == snapshot_anchor['worker_ref']
    altered = dict(worker_proof, terminal={**worker_proof['terminal'], 'returncode': 3})
    with pytest.raises(ValueError):
        audit_anchored_reference_worker(view, recorded_clock, run_id, altered,
            stdout=process_output['stdout'], stderr=process_output['stderr'], selected=result['selected_program'])
    with pytest.raises(ValueError):
        audit_anchored_reference_worker(view, recorded_clock, run_id, worker_proof,
            stdout=process_output['stdout'] + 'changed', stderr=process_output['stderr'], selected=result['selected_program'])
    physical_audit = audit_anchored_reference_physical(view, recorded_clock, run_id,
        options=authority.budget.options, stamp=asdict(authority.budget.stamp),
        governance=authority.budget._governed.config, rows=rows,
        request_ids=ids)
    assert physical_audit['evidence_ref'] == result['stage_evidence_ref']
    assert physical_audit['stage_eval_count'] == len(ids)
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    def forbidden(*args, **kwargs):
        raise AssertionError('reference recorded audit performed live work')
    with monkeypatch.context() as guard:
        guard.setattr(GovernedCNYProvider, 'perform_request', forbidden)
        guard.setattr(CirclePackingDomain, 'evaluate', forbidden)
        guard.setattr('zoo.circle_packing.host_physical.run_stage', forbidden)
        joined = audit_anchored_reference_cell(view, recorded_clock, run_id, worker_proof=worker_proof,
            stdout=process_output['stdout'], stderr=process_output['stderr'], selected=result['selected_program'],
            options=authority.budget.options, stamp=asdict(authority.budget.stamp),
            governance=authority.budget._governed.config, rows=rows, request_ids=ids)
        from zoo.circle_packing.reference_final import recalculate_reference_snapshot
        final = recalculate_reference_snapshot(view, recorded_clock, run_id, plan=plan, expected_plan_ref=ref,
            worker_proof=worker_proof, stdout=process_output['stdout'], stderr=process_output['stderr'],
            selected=result['selected_program'], options=authority.budget.options, stamp=asdict(authority.budget.stamp),
            governance=authority.budget._governed.config, rows=rows, request_ids=ids)
        from zoo.circle_packing.reference_recovery import recover_reference_snapshot
        recovered = recover_reference_snapshot(view, recorded_clock, run_id, plan=plan, expected_plan_ref=ref,
            worker_directory=tmp_path / 'worker', options=authority.budget.options,
            stamp=asdict(authority.budget.stamp), governance=authority.budget._governed.config, rows=rows)
        assert recovered == final
        recovery_input = tmp_path / 'reference-recovery-input.json'
        recovery_input.write_text(json.dumps({'evidence': evidence, 'head': ledger.snapshot()['journal_head'],
            'run_id': run_id, 'clock': clock.export_evidence(), 'plan': plan, 'ref': ref,
            'worker': str(tmp_path / 'worker'), 'options': authority.budget.options,
            'stamp': asdict(authority.budget.stamp), 'governance': authority.budget._governed.config,
            'rows': rows}))
        recovery_script = r'''
import json, sys
from pathlib import Path
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.reference_recovery import recover_reference_snapshot
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
value = json.loads(Path(sys.argv[1]).read_text())
def forbidden(*args, **kwargs): raise AssertionError('recovery performed external work')
GovernedCNYProvider.perform_request = forbidden
CirclePackingDomain.evaluate = forbidden
from zoo.circle_packing import host_physical
host_physical.run_stage = forbidden
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
view = RecordedCurrencyView(value['evidence'], expected_run_id=value['run_id'], expected_head=value['head'])
clock = RecordedCellClock(value['clock'], view.cell_deadline_claim('vendor-0'))
print(json.dumps(recover_reference_snapshot(view, clock, value['run_id'], plan=value['plan'],
    expected_plan_ref=value['ref'], worker_directory=value['worker'], options=value['options'],
    stamp=value['stamp'], governance=value['governance'], rows=value['rows']), sort_keys=True))
'''
        child = subprocess.run([sys.executable, '-c', recovery_script, str(recovery_input)], check=True,
            text=True, capture_output=True, timeout=60,
            env={'PATH': os.defpath, 'PYTHONPATH': str(repository / 'm0'), 'PYTHONDONTWRITEBYTECODE': '1'})
        assert json.loads(child.stdout) == final
        journal = tmp_path / 'worker' / 'worker.jsonl'
        saved_journal = journal.read_bytes()
        try:
            records = [json.loads(line) for line in saved_journal.splitlines()]
            terminal = next(row for row in records if row['kind'] == 'executor_process_finished')
            terminal['payload']['returncode'] = 1
            journal.write_text(''.join(json.dumps(row) + '\n' for row in records))
            with pytest.raises(ValueError):
                recover_reference_snapshot(view, recorded_clock, run_id, plan=plan, expected_plan_ref=ref,
                    worker_directory=tmp_path / 'worker', options=authority.budget.options,
                    stamp=asdict(authority.budget.stamp), governance=authority.budget._governed.config, rows=rows)
        finally:
            journal.write_bytes(saved_journal)
        changed_plan = {**plan, 'public_range_sum_radii': 0}
        with pytest.raises(ValueError, match='plan'):
            recalculate_reference_snapshot(view, recorded_clock, run_id, plan=changed_plan, expected_plan_ref=ref,
                worker_proof=worker_proof, stdout=process_output['stdout'], stderr=process_output['stderr'],
                selected=result['selected_program'], options=authority.budget.options, stamp=asdict(authority.budget.stamp),
                governance=authority.budget._governed.config, rows=rows, request_ids=ids)
    assert final['scope'] == 'host_attested_reference_snapshot' and not final['performance_claim']
    assert final['selection_frozen'] is True
    assert final['metrics'] == result['selected_program']['metrics']
    assert final['stage_request_id'] == request_id and final['geometry_ref'] == joined['stage']['geometry_ref']
    assert final['public_range_threshold'] == plan['public_range_sum_radii']
    assert final['public_range_condition_met'] is False
    assert joined['scope'] == 'host_attested_reference_snapshot' and not joined['performance_claim']
    assert joined['stage']['evidence_ref'] == result['stage_evidence_ref']
    assert joined['stage']['all_stage_count'] == authority.stages.audit()['stage_calls']
    with pytest.raises(ValueError):
        audit_anchored_reference_physical(view, recorded_clock, run_id,
            options=authority.budget.options, stamp=asdict(authority.budget.stamp),
            governance=authority.budget._governed.config, rows=rows[:-1], request_ids=ids)
    with pytest.raises(ValueError):
        ledger.anchor_reference_physical_snapshot(run_id, 'vendor-0', snapshot_anchor['rows_sha256'],
            snapshot_anchor['worker_ref'], ids, snapshot_anchor['sequence'], snapshot_anchor['observation_sha256'])
    assert len(local_endpoint.requests) == iterations
    reference_limits = authority.budget.options['limits']['global']
    authority.close()
    # Mori starts in the same frozen source and Python runtime as the vendor
    # worker. The ordinary case uses one reference iteration; the six-iteration
    # case also exercises repeated code and failed patch construction. Both use
    # fake responses and make no performance comparison.
    mori_clock = CellDeadline.start(ContinuationStore(tmp_path / 'mori-clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                    cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    mori_output = tmp_path / 'mori'
    local_endpoint.responses.extend(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}])
                                    for _ in range(2 * plan['iterations']))
    setup_path = tmp_path / 'mori-fixture.json'
    setup_path.write_text(json.dumps({'plan': plan, 'ref': ref, 'runtime_manifest': frozen['manifest'],
        'source_manifest': exported['manifest'], 'campaign_id': campaign_id, 'seed': 0,
        'source': str(source / 'm0'), 'runtime': str(runtime), 'ledger': str(ledger.path),
        'clock': str(mori_clock._store.path), 'output': str(mori_output), 'base_url': local_endpoint.url}))
    journal = ProcessJournal(ContinuationStore(tmp_path / 'mori-coordinator.jsonl'))
    clock_record = mori_clock._record
    process, execution = journal.launch(
        [str(runtime / 'bin' / 'python'), '-m', 'zoo.circle_packing.mori_fixture_worker', str(setup_path)], tmp_path,
        {'PATH': os.defpath, 'PYTHONPATH': str(source / 'm0'), 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}, 240,
        {'candidate_id': 'fixture-coordinator', 'attempt': 1}, die_with_parent=True,
        absolute_deadline={'boot_id': clock_record['boot_id'],
            'deadline_ns': clock_record['start_ns'] + clock_record['seconds'] * 1_000_000_000})
    process_result = journal.wait(process, execution)
    assert process_result['returncode'] == 0 and not process_result['timeout'], process_result['stderr']
    assert process_result['wrapper_error'] is None
    mori = json.loads(process_result['stdout'])
    assert mori['mode'] == 'fixture' and mori['performance_claim'] is False
    assert mori['limits'] == reference_limits
    assert mori['candidate'] is not None and mori['final_state'] == 'completed' and mori['replay_passed']
    assert Path(mori['source']).resolve() == (source / 'm0' / 'core' / 'loop.py').resolve()
    assert Path(mori['governed_source']).resolve() == (source / 'm0' / 'zoo' / 'circle_packing' / 'governed.py').resolve()
    assert (source / 'm0' / 'vendor' / 'openevolve').resolve() in Path(mori['vendor_source']).resolve().parents
    assert mori['executable'] == str(runtime / 'bin' / 'python')
    verify_frozen_source(ledger, plan, snapshot=source, manifest=exported['manifest'],
                         expected_plan_ref=ref, expected_campaign_id=campaign_id)
    verify_frozen_runtime(ledger, runtime=runtime, manifest=frozen['manifest'], base_python='/usr/bin/python3.12')
    assert iterations + 1 <= len(local_endpoint.requests) <= iterations + 2 * plan['iterations']
    rows = [json.loads(line) for line in (mori_output / 'framework' / 'x1.jsonl').read_text().splitlines()]
    assert len([row for row in rows if row['kind'] == 'composed_evidence']) == plan['iterations'] + 1
    assert not ledger.snapshot()['pending_calls']
