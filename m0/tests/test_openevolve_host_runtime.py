"""Reference authorities use the declared pilot limits and one original campaign."""
import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_provider import local_endpoint
from test_openevolve_frozen_runtime import fixture
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
from zoo.mle_bench_lite.composed_domain import SandboxRunner

pytestmark = pytest.mark.linux


def prepared_reference(tmp_path, local_endpoint):
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path, require_runtime=True)
    runtime = tmp_path / 'runtime'
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    return dict(ledger=ledger, plan=plan, expected_plan_ref=ref, expected_campaign_id=campaign_id,
                deadline=clock, snapshot=snapshot, source_manifest=exported['manifest'], runner=runner,
                api_key='fixture-only-secret', base_url=local_endpoint.url)


def test_reference_authorities_bind_frozen_plan_budget_clock_and_campaign(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path, require_runtime=True)
    runtime = tmp_path / 'runtime'
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    before = ledger.snapshot()['settled_upper_bound_micro_cny']
    authority = build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=plan,
        expected_plan_ref=ref, expected_campaign_id=campaign_id, deadline=clock,
        snapshot=snapshot, source_manifest=exported['manifest'], runner=runner,
        api_key='fixture-only-secret', base_url=local_endpoint.url)
    assert authority.bridge.cell_deadline() is clock
    assert authority.control.domain.runner.manifest_binding['runtime_ref'] == frozen['runtime_ref']
    assert authority.stages.runner.manifest_binding['runtime_ref'] == frozen['runtime_ref']
    assert authority.budget.options['limits']['global'] == {
        key: plan['limits'][key] for key in ('token', 'node', 'eval_count')}
    assert authority.run.main_provider_binding['call_bound']['units']['token'] == (
        ledger.manifest_binding()['context_tokens'] + plan['max_completion_tokens'])
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == before
    assert not ledger.snapshot()['pending_calls'] and not local_endpoint.requests


def test_reference_snapshot_requires_original_worker_and_anchored_stage(tmp_path, local_endpoint, monkeypatch):
    import asyncio
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    try:
        ledger, clock = options['ledger'], options['deadline']
        monkeypatch.setattr('zoo.circle_packing.stage.run_stage',
                            lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
        assert asyncio.run(authority.control.execute('control-0000'))['status'] == 'evaluated'
        monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                            lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
        authority.stages.execute('a' * 32, 'program', stage=1)
        worker_ref, rows_sha = 'b' * 64, 'c' * 64
        ledger.claim_cell_worker('vendor-0', clock._record['record_sha256'], worker_ref)
        run_id = authority.dispatch.ready.authority_binding['currency_run_id']
        def anchor(worker, requests):
            def record(observation):
                value = observation['observation']
                ledger.anchor_reference_physical_snapshot(run_id, 'vendor-0', rows_sha, worker,
                    requests, value['sequence'], value['sha256'])
            clock.observe_and_anchor(record)
        with pytest.raises(ValueError):
            anchor('d' * 64, ['a' * 32])
        with pytest.raises(ValueError):
            anchor(worker_ref, ['e' * 32])
        with pytest.raises(ValueError):
            anchor(worker_ref, ['a' * 32, 'a' * 32])
        anchor(worker_ref, ['a' * 32])
        assert ledger.reference_physical_snapshot(run_id)['rows_sha256'] == rows_sha
        from zoo.circle_packing.cell_deadline import RecordedCellClock
        from zoo.circle_packing.reference_selection import audit_anchored_reference_worker
        from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
        evidence = ledger.export_governance_evidence(run_id, authority.dispatch.ready.physical_plan_ref)
        view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
        recorded_clock = RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim('vendor-0'))
        assert 'worker_proof_sha256' not in view.reference_physical_snapshot(run_id)
        with pytest.raises(ValueError, match='worker evidence'):
            audit_anchored_reference_worker(view, recorded_clock, run_id, {}, stdout='', stderr='', selected={})
        with pytest.raises(ValueError):
            anchor(worker_ref, ['a' * 32])
    finally:
        authority.close()


def test_recorded_reference_snapshot_rejects_late_clock_observation(tmp_path, local_endpoint, monkeypatch):
    import asyncio
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_runtime import build_reference_authorities
    from zoo.circle_packing.reference_selection import audit_anchored_reference_physical
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    try:
        ledger, clock = options['ledger'], options['deadline']
        monkeypatch.setattr('zoo.circle_packing.stage.run_stage',
                            lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
        assert asyncio.run(authority.control.execute('control-0000'))['status'] == 'evaluated'
        monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                            lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
        authority.stages.execute('a' * 32, 'program', stage=1)
        worker_ref = 'b' * 64
        ledger.claim_cell_worker('vendor-0', clock._record['record_sha256'], worker_ref)
        run_id = authority.dispatch.ready.authority_binding['currency_run_id']
        rows = list(authority.budget.store.read())
        monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns',
            lambda: clock._record['start_ns'] + clock._record['seconds'] * 1_000_000_000)
        def anchor(observation):
            value = observation['observation']
            ledger.anchor_reference_physical_snapshot(run_id, 'vendor-0', payload_digest(rows), worker_ref,
                ['a' * 32], value['sequence'], value['sha256'])
        clock.observe_and_anchor(anchor)
        evidence = ledger.export_governance_evidence(run_id, authority.dispatch.ready.physical_plan_ref)
        view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
        recorded = RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim('vendor-0'))
        with pytest.raises(ValueError, match='late'):
            audit_anchored_reference_physical(view, recorded, run_id,
                options=authority.budget.options, stamp=asdict(authority.budget.stamp),
                governance=authority.budget._governed.config, rows=rows, request_ids=['a' * 32])
    finally:
        authority.close()


def test_reference_authorities_reject_mismatched_cell_before_protection(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path, require_runtime=True)
    runtime = tmp_path / 'runtime'
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='vendor'):
        build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=plan,
            expected_plan_ref=ref, expected_campaign_id=campaign_id, deadline=clock,
            snapshot=snapshot, source_manifest=exported['manifest'], runner=runner,
            api_key='fixture-only-secret', base_url=local_endpoint.url)
    assert ledger.snapshot() == before and not local_endpoint.requests


def test_reference_setup_recovers_interruption_after_protection(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    options = prepared_reference(tmp_path, local_endpoint)
    original = CNYInvocationBridge.bind_cell_deadline
    def interrupted(*args, **kwargs):
        raise RuntimeError('fixture crash after currency protection')
    monkeypatch.setattr(CNYInvocationBridge, 'bind_cell_deadline', interrupted)
    with pytest.raises(RuntimeError, match='fixture crash'):
        build_reference_authorities(tmp_path / 'reference', **options)
    after_crash = options['ledger'].snapshot()
    assert after_crash['protected_micro_cny'] > 0 and not after_crash['pending_calls']
    monkeypatch.setattr(CNYInvocationBridge, 'bind_cell_deadline', original)
    resumed = build_reference_authorities(tmp_path / 'reference', **options)
    assert resumed.bridge.cell_deadline() is options['deadline']
    assert options['ledger'].snapshot()['protected_micro_cny'] == after_crash['protected_micro_cny']
    assert not local_endpoint.requests


def test_reference_setup_recovers_interruption_before_authority_claim(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    ledger = options['ledger']
    original = ledger.claim_reference_authority
    def interrupted(*args, **kwargs):
        raise RuntimeError('fixture crash before authority claim')
    monkeypatch.setattr(ledger, 'claim_reference_authority', interrupted)
    with pytest.raises(RuntimeError, match='fixture crash'):
        build_reference_authorities(tmp_path / 'reference', **options)
    assert ledger.reference_authority_claim('vendor-0') is None
    monkeypatch.setattr(ledger, 'claim_reference_authority', original)
    resumed = build_reference_authorities(tmp_path / 'reference', **options)
    resumed.close()
    assert not local_endpoint.requests


def test_reference_setup_recovers_interruption_after_authority_claim(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    options = prepared_reference(tmp_path, local_endpoint)
    original = CNYInvocationBridge.bind_run
    def interrupted(*args, **kwargs):
        raise RuntimeError('fixture crash after authority claim')
    monkeypatch.setattr(CNYInvocationBridge, 'bind_run', interrupted)
    with pytest.raises(RuntimeError, match='fixture crash'):
        build_reference_authorities(tmp_path / 'reference', **options)
    assert options['ledger'].reference_authority_claim('vendor-0') is not None
    monkeypatch.setattr(CNYInvocationBridge, 'bind_run', original)
    resumed = build_reference_authorities(tmp_path / 'reference', **options)
    resumed.close()
    assert not local_endpoint.requests


def test_reference_setup_recovers_before_first_physical_protection(tmp_path, local_endpoint, monkeypatch):
    from core.composition.budget import HierarchicalBudget
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    original = HierarchicalBudget.protect_controls
    def interrupted(*args, **kwargs):
        raise RuntimeError('fixture crash before physical protection')
    monkeypatch.setattr(HierarchicalBudget, 'protect_controls', interrupted)
    with pytest.raises(RuntimeError, match='fixture crash'):
        build_reference_authorities(tmp_path / 'reference', **options)
    assert options['ledger'].reference_authority_claim('vendor-0') is None
    monkeypatch.setattr(HierarchicalBudget, 'protect_controls', original)
    resumed = build_reference_authorities(tmp_path / 'reference', **options)
    resumed.close()
    assert not local_endpoint.requests


def test_reference_cell_cannot_claim_another_authority(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    ledger = options['ledger']
    build_reference_authorities(tmp_path / 'reference', **options)
    with pytest.raises(ValueError, match='cell.*authority'):
        build_reference_authorities(tmp_path / 'other-reference', **options)
    assert not local_endpoint.requests


def test_reference_factory_refuses_nonlocal_provider_without_mutating_ledger(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    ledger = options['ledger']
    before = ledger.snapshot()
    options['base_url'] = ledger.manifest_binding()['provider_base_url']
    with pytest.raises(ValueError, match='loopback'):
        build_reference_authorities(tmp_path / 'reference', **options)
    assert ledger.snapshot() == before


def test_reference_syncs_directories_before_campaign_claim(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing import host_runtime
    options = prepared_reference(tmp_path, local_endpoint)
    output, ledger = tmp_path / 'reference', options['ledger']
    synced = []
    original_sync, original_claim = host_runtime._sync_directory, ledger.claim_reference_authority
    def sync(path):
        synced.append(Path(path))
        return original_sync(path)
    def claim(*args, **kwargs):
        assert output.parent in synced and output in synced
        return original_claim(*args, **kwargs)
    from pathlib import Path
    monkeypatch.setattr(host_runtime, '_sync_directory', sync)
    monkeypatch.setattr(ledger, 'claim_reference_authority', claim)
    authority = host_runtime.build_reference_authorities(output, **options)
    authority.close()


def test_reference_same_run_has_one_live_owner_and_closed_owner_cannot_work(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    import asyncio
    options = prepared_reference(tmp_path, local_endpoint)
    first = build_reference_authorities(tmp_path / 'reference', **options)
    with pytest.raises(RuntimeError, match='owner'):
        build_reference_authorities(tmp_path / 'reference', **options)
    first.close()
    with pytest.raises(RuntimeError, match='closed'):
        asyncio.run(first.control.execute('control-0000'))
    second = build_reference_authorities(tmp_path / 'reference', **options)
    second.close()
    assert not local_endpoint.requests


def test_reference_owner_cannot_close_during_control_execution(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    import asyncio
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)

    async def active_control(slot):
        with pytest.raises(RuntimeError, match='active'):
            authority.close()
        return {'slot': slot}

    monkeypatch.setattr(authority.control, '_execute', active_control)
    assert asyncio.run(authority.control.execute('control-0000')) == {'slot': 'control-0000'}
    authority.close()


def test_reference_close_rejects_work_active_on_another_thread(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    import asyncio
    import threading
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    entered, release = threading.Event(), threading.Event()

    async def active_control(slot):
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return {'slot': slot}

    monkeypatch.setattr(authority.control, '_execute', active_control)
    thread = threading.Thread(target=lambda: asyncio.run(authority.control.execute('control-0000')))
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match='active'):
            authority.close()
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    authority.close()


def test_reference_cell_rejects_another_currency_run_binding(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    ledger, clock = options['ledger'], options['deadline']
    other_run = 'a' * 64
    ledger.protect_run(other_run, authority.run.physical_plan['plan_ref'],
                       authority.bridge._preparation['obligations'])
    with pytest.raises(ValueError, match='reference.*authority'):
        ledger.bind_run_deadline(other_run, 'vendor-0', options['expected_plan_ref'],
                                 clock._record['record_sha256'])
    authority.close()
    assert not local_endpoint.requests


def test_reference_cannot_recreate_deleted_physical_journal(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    output = tmp_path / 'reference'
    authority = build_reference_authorities(output, **options)
    authority.close()
    (output / 'events.jsonl').unlink()
    with pytest.raises(ValueError, match='lost its original physical journal'):
        build_reference_authorities(output, **options)
    assert not local_endpoint.requests


def test_reference_started_work_cannot_reopen_as_fresh_after_journal_loss(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    import asyncio
    options = prepared_reference(tmp_path, local_endpoint)
    output = tmp_path / 'reference'
    authority = build_reference_authorities(output, **options)
    async def measured_boundary(slot):
        return {'slot': slot}
    monkeypatch.setattr(authority.control, '_execute', measured_boundary)
    asyncio.run(authority.control.execute('control-0000'))
    authority.close()
    (output / 'events.jsonl').unlink()
    with pytest.raises(ValueError, match='started.*recovery'):
        build_reference_authorities(output, **options)
    assert not local_endpoint.requests


def test_reference_rechecks_started_state_after_acquiring_owner_lock(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities
    import asyncio
    import threading
    options = prepared_reference(tmp_path, local_endpoint)
    output, ledger = tmp_path / 'reference', options['ledger']
    first = build_reference_authorities(output, **options)
    seen, resume = threading.Event(), threading.Event()
    original = ledger.reference_authority_claim

    def delayed_claim(cell):
        result = original(cell)
        if not seen.is_set():
            seen.set()
            assert resume.wait(5)
        return result

    monkeypatch.setattr(ledger, 'reference_authority_claim', delayed_claim)
    outcomes = []
    def reopen():
        try:
            value = build_reference_authorities(output, **options)
        except Exception as error:
            outcomes.append(error)
        else:
            value.close()
            outcomes.append(None)
    thread = threading.Thread(target=reopen)
    thread.start()
    try:
        assert seen.wait(5)
        async def measured_boundary(slot):
            return {'slot': slot}
        monkeypatch.setattr(first.control, '_execute', measured_boundary)
        asyncio.run(first.control.execute('control-0000'))
        first.close()
    finally:
        resume.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(outcomes) == 1 and isinstance(outcomes[0], ValueError)
    assert 'started' in str(outcomes[0]) and 'recovery' in str(outcomes[0])
    assert not local_endpoint.requests


def test_reference_cell_rejects_worker_directory_inside_authority_before_control(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    workspace = tmp_path / 'worker-workspace'
    workspace.mkdir(mode=0o700)
    runner = options['runner']
    with pytest.raises(ValueError, match='isolated'):
        run_reference_cell_fixture(authority, options['deadline'], tmp_path / 'reference' / 'worker', workspace,
            snapshot=options['snapshot'], source_manifest=options['source_manifest'], frozen_plan=options['plan'],
            expected_plan_ref=options['expected_plan_ref'], expected_campaign_id=options['expected_campaign_id'],
            runtime=runner.runtime_root, runtime_manifest=runner._campaign_runtime[1],
            base_python=runner._campaign_runtime[2])
    assert not options['ledger'].reference_authority_claim('vendor-0')['work_started']
    assert not local_endpoint.requests
    authority.close()


def test_reference_cell_rejects_long_socket_path_before_control(tmp_path, local_endpoint):
    from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    workspace = tmp_path / ('w' * 90)
    workspace.mkdir(mode=0o700)
    runner = options['runner']
    with pytest.raises(ValueError, match='socket'):
        run_reference_cell_fixture(authority, options['deadline'], tmp_path / 'worker', workspace,
            snapshot=options['snapshot'], source_manifest=options['source_manifest'], frozen_plan=options['plan'],
            expected_plan_ref=options['expected_plan_ref'], expected_campaign_id=options['expected_campaign_id'],
            runtime=runner.runtime_root, runtime_manifest=runner._campaign_runtime[1],
            base_python=runner._campaign_runtime[2])
    assert not options['ledger'].reference_authority_claim('vendor-0')['work_started']
    assert authority.budget.audit_governance()['physical_totals']['eval_count'] == 0
    authority.close()


def test_reference_cell_keeps_owner_until_worker_returns(tmp_path, local_endpoint, short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
    from zoo.circle_packing import reference_worker
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    async def control(slot):
        return {'status': 'evaluated'}
    def worker(*args, **kwargs):
        with pytest.raises(RuntimeError, match='active'):
            authority.close()
        raise RuntimeError('fixture worker stopped')
    monkeypatch.setattr(authority.control, 'execute', control)
    monkeypatch.setattr(reference_worker, 'run_reference_fixture', worker)
    runner = options['runner']
    with pytest.raises(RuntimeError, match='fixture worker stopped'):
        run_reference_cell_fixture(authority, options['deadline'], tmp_path / 'worker', short_socket_dir,
            snapshot=options['snapshot'], source_manifest=options['source_manifest'], frozen_plan=options['plan'],
            expected_plan_ref=options['expected_plan_ref'], expected_campaign_id=options['expected_campaign_id'],
            runtime=runner.runtime_root, runtime_manifest=runner._campaign_runtime[1],
            base_python=runner._campaign_runtime[2])
    authority.close()


def test_reference_cell_reports_unresolved_broker_when_worker_raises(tmp_path, local_endpoint, short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
    from zoo.circle_packing import reference_worker
    from zoo.circle_packing.host_transport import HostBroker
    import threading
    import time
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    entered, release = threading.Event(), threading.Event()
    async def control(slot):
        return {'status': 'evaluated'}
    def blocked_broker(_broker):
        with authority._lease.operation():
            entered.set()
            release.wait(10)
    def worker(*args, **kwargs):
        assert entered.wait(5)
        raise RuntimeError('fixture worker stopped')
    monkeypatch.setattr(authority.control, 'execute', control)
    monkeypatch.setattr(HostBroker, 'serve_one', blocked_broker)
    monkeypatch.setattr(reference_worker, 'run_reference_fixture', worker)
    runner = options['runner']
    try:
        with pytest.raises(RuntimeError, match='broker has unresolved'):
            run_reference_cell_fixture(authority, options['deadline'], tmp_path / 'worker', short_socket_dir,
                snapshot=options['snapshot'], source_manifest=options['source_manifest'], frozen_plan=options['plan'],
                expected_plan_ref=options['expected_plan_ref'], expected_campaign_id=options['expected_campaign_id'],
                runtime=runner.runtime_root, runtime_manifest=runner._campaign_runtime[1],
                base_python=runner._campaign_runtime[2])
        with pytest.raises(RuntimeError, match='active'):
            authority.close()
    finally:
        release.set()
        limit = time.monotonic() + 5
        while authority._lease._active and time.monotonic() < limit:
            time.sleep(.01)
        authority.close()


def test_reference_cell_closes_broker_connection_waiting_for_frame(tmp_path, local_endpoint, short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_runtime import build_reference_authorities, run_reference_cell_fixture
    from zoo.circle_packing import reference_worker
    from zoo.circle_packing.host_transport import HostBroker
    import socket
    import threading
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    accepted, workers, clients = threading.Event(), [], []
    original_accept, original_serve = socket.socket.accept, HostBroker.serve_one
    def accept(sock):
        result = original_accept(sock)
        if sock.family == socket.AF_UNIX:
            accepted.set()
        return result
    def serve(broker):
        workers.append(threading.current_thread())
        return original_serve(broker)
    async def control(slot):
        return {'status': 'evaluated'}
    def worker(*args, **kwargs):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        clients.append(client)
        client.connect(str(kwargs['broker'].path))
        client.sendall(b'{')
        assert accepted.wait(5)
        raise RuntimeError('fixture worker stopped')
    monkeypatch.setattr(socket.socket, 'accept', accept)
    monkeypatch.setattr(HostBroker, 'serve_one', serve)
    monkeypatch.setattr(authority.control, 'execute', control)
    monkeypatch.setattr(reference_worker, 'run_reference_fixture', worker)
    runner = options['runner']
    try:
        with pytest.raises(RuntimeError, match='fixture worker stopped'):
            run_reference_cell_fixture(authority, options['deadline'], tmp_path / 'worker', short_socket_dir,
                snapshot=options['snapshot'], source_manifest=options['source_manifest'], frozen_plan=options['plan'],
                expected_plan_ref=options['expected_plan_ref'], expected_campaign_id=options['expected_campaign_id'],
                runtime=runner.runtime_root, runtime_manifest=runner._campaign_runtime[1],
                base_python=runner._campaign_runtime[2])
        assert workers and not workers[0].is_alive()
        authority.close()
    finally:
        for client in clients:
            client.close()
        if workers:
            workers[0].join(timeout=5)


def test_reference_owner_seals_once_and_rejects_later_work(tmp_path):
    from zoo.circle_packing.host_runtime import _AuthorityLease
    owner = _AuthorityLease(tmp_path)
    calls = []
    owner.bind_start(lambda: calls.append('started'))
    with owner.session():
        owner.seal(lambda: calls.append('sealed'))
        with pytest.raises(RuntimeError, match='sealed'):
            with owner.operation():
                pass
    assert calls == ['sealed']
    owner.close()


def test_reference_owner_does_not_seal_while_another_session_is_active(tmp_path):
    from zoo.circle_packing.host_runtime import _AuthorityLease
    owner = _AuthorityLease(tmp_path)
    owner.bind_start(lambda: None)
    called = []
    with owner.session(), owner.session():
        with pytest.raises(RuntimeError, match='active'):
            owner.seal(lambda: called.append(True))
    assert called == []
    owner.close()


def test_frozen_reference_selection_forbids_later_stage_and_provider_work(tmp_path, local_endpoint, monkeypatch):
    import asyncio
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_runtime import build_reference_authorities
    options = prepared_reference(tmp_path, local_endpoint)
    authority = build_reference_authorities(tmp_path / 'reference', **options)
    ledger, clock = options['ledger'], options['deadline']
    try:
        monkeypatch.setattr('zoo.circle_packing.stage.run_stage',
                            lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
        monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                            lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
        asyncio.run(authority.control.execute('control-0000'))
        authority.stages.execute('a' * 32, 'program', stage=1)
        ledger.claim_cell_worker('vendor-0', clock._record['record_sha256'], 'b' * 64)
        run_id = authority.dispatch.ready.authority_binding['currency_run_id']
        def anchor(observation):
            value = observation['observation']
            ledger.anchor_reference_physical_snapshot(run_id, 'vendor-0', 'c' * 64, 'b' * 64,
                ['a' * 32], value['sequence'], value['sha256'], worker_proof_sha256='d' * 64)
        clock.observe_and_anchor(anchor)
        selected = {'id': 'winner', 'program_ref': 'sha256:' + 'e' * 64, 'metrics': {'validity': 1.0}}
        def freeze():
            def record(observation):
                assert observation['eligible']
                value = observation['observation']
                ledger.freeze_reference_selection(run_id, 'vendor-0', payload_digest(selected),
                                                  value['sequence'], value['sha256'])
            clock.observe_and_anchor(record)
        with authority._lease.session():
            authority._lease.seal(freeze)
        assert ledger.reference_selection(run_id)['selection_sha256'] == payload_digest(selected)
        with pytest.raises(RuntimeError, match='sealed'):
            authority.stages.execute('f' * 32, 'program', stage=1)
        with pytest.raises(ValueError, match='sealed'):
            ledger.start_reference_authority_work('vendor-0', ledger.reference_authority_claim('vendor-0')['authority_ref'])
        bound = ledger.quote_call(1)
        with pytest.raises(ValueError, match='sealed'):
            ledger.admit_call(run_id, 'main', None,
                {'call_id': 'after-selection', 'request_sha256': '1' * 64, 'phase': 'operator', 'ordinal': 0}, bound)
        assert not local_endpoint.requests
    finally:
        authority.close()
