"""Cell-clock evidence must coexist with the original governed currency bridge."""
from unittest.mock import patch

import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_bridge import setup
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle


def test_cell_clock_events_do_not_change_governed_call_or_recovery(setup, tmp_path):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    lifecycle = CellLifecycle(ledger)
    clock_store = ContinuationStore(tmp_path / 'clock.jsonl')
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 101]):
        clock = CellDeadline.start(clock_store, lifecycle=lifecycle, cell_id='vendor-0',
                                   plan_ref='sha256:' + 'a' * 64, seconds=5)
        clock.check()
        assert bridge.invoke(context, ('prompt',), {}) == 'answer'
        outcome = bridge.recover(context, context.argument_sha256)
        assert outcome.outcome == 'returned'
        assert len(calls) == 1
        assert ledger.snapshot()['pending_calls'] == []


def _bound_clock(ledger, bridge, tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    current = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: current['ns'])
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock-bound.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=plan['limits']['wallclock_seconds'])
    # The generic bridge fixture pre-populates a synthetic provider-start row;
    # install the deadline before that synthetic work to match real ordering.
    store = bridge._run.store
    if not isinstance(store, ContinuationStore):
        saved = list(store.rows)
        store.rows = []
        try:
            bridge.bind_cell_deadline(clock, plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'], cell_id='vendor-0')
        finally:
            store.rows = saved
    else:
        bridge.bind_cell_deadline(clock, plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'], cell_id='vendor-0')
    return current


def test_expired_deadline_blocks_provider_before_currency_admission(setup, tmp_path, monkeypatch):
    from zoo.circle_packing.cell_deadline import DeadlineExpired
    ledger, bridge, run, context, providers, calls, store, physical = setup
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    current['ns'] += 2700 * 1_000_000_000
    with pytest.raises(DeadlineExpired):
        bridge.invoke(context, ('prompt',), {})
    assert not calls and not ledger.snapshot()['pending_calls']
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 0


def test_late_provider_response_is_billed_but_not_returned(setup, tmp_path, monkeypatch):
    from zoo.circle_packing.cell_deadline import DeadlineExpired
    ledger, bridge, run, context, providers, calls, store, physical = setup
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    raw = providers['control-0000']
    perform = raw.perform_request
    def late(*args, **kwargs):
        response = perform(*args, **kwargs)
        current['ns'] += 2700 * 1_000_000_000
        return response
    monkeypatch.setattr(raw, 'perform_request', late)
    with pytest.raises(DeadlineExpired):
        bridge.invoke(context, ('prompt',), {})
    assert len(calls) == 1 and not ledger.snapshot()['pending_calls']
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 36
    with pytest.raises(DeadlineExpired):
        bridge.recover(context, context.argument_sha256)


def test_deadline_after_currency_admission_retains_pending_and_never_dispatches(setup, tmp_path, monkeypatch):
    from core.llm import UsageError
    from zoo.circle_packing.cell_deadline import DeadlineExpired
    ledger, bridge, run, context, providers, calls, store, physical = setup
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    admit = ledger.admit_call
    def expire_after_admission(*args, **kwargs):
        result = admit(*args, **kwargs)
        current['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(ledger, 'admit_call', expire_after_admission)
    with pytest.raises(DeadlineExpired):
        bridge.invoke(context, ('prompt',), {})
    assert not calls and len(ledger.snapshot()['pending_calls']) == 1
    with pytest.raises(UsageError):
        bridge.recover(context, context.argument_sha256)


def test_recovered_bridge_rebinds_existing_deadline_without_reset(setup, tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    ledger, bridge, run, context, providers, calls, store, physical = setup
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    assert bridge.invoke(context, ('prompt',), {}) == 'answer'
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    restored = CellDeadline.restore(ContinuationStore(tmp_path / 'clock-bound.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    replacement = CNYInvocationBridge(ledger)
    replacement.bind_run(run)
    replacement.bind_cell_deadline(restored, plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'], cell_id='vendor-0')
    assert replacement.recover(context, context.argument_sha256).outcome == 'returned'
    assert len(calls) == 1


def test_bound_bridge_cannot_disable_deadline_by_losing_live_reference(setup, tmp_path, monkeypatch):
    from core.llm import UsageError
    ledger, bridge, run, context, providers, calls, store, physical = setup
    _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    bridge._cell_deadline = None
    with pytest.raises(UsageError, match='deadline'):
        bridge.invoke(context, ('prompt',), {})
    assert not calls and not ledger.snapshot()['pending_calls']


def test_lost_binding_spool_cannot_disable_deadline_after_bridge_restart(setup, tmp_path, monkeypatch):
    from core.llm import UsageError
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    ledger, bridge, run, context, providers, calls, store, physical = setup
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    current['ns'] += 2700 * 1_000_000_000
    (bridge._spool / 'cell-deadline-binding.json').unlink()
    replacement = CNYInvocationBridge(ledger)
    replacement.bind_run(run)
    with pytest.raises(UsageError, match='deadline'):
        replacement.invoke(context, ('prompt',), {})
    assert not calls and not ledger.snapshot()['pending_calls']


def test_deadline_after_dispatch_marker_keeps_currency_pending(setup, tmp_path, monkeypatch):
    from core.llm import UsageError
    from zoo.circle_packing.cell_deadline import DeadlineExpired
    ledger, bridge, run, context, providers, calls, store, physical = setup
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    save = bridge._save
    def expire_after_marker(name, value):
        save(name, value)
        if name.endswith('.dispatch'):
            current['ns'] += 2700 * 1_000_000_000
    monkeypatch.setattr(bridge, '_save', expire_after_marker)
    with pytest.raises(DeadlineExpired):
        bridge.invoke(context, ('prompt',), {})
    assert not calls and len(ledger.snapshot()['pending_calls']) == 1
    with pytest.raises(UsageError):
        bridge.recover(context, context.argument_sha256)


def test_deadline_binding_recovers_after_campaign_anchor_before_spool(setup, tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    ledger, bridge, run, context, providers, calls, store, physical = setup
    save = bridge._save
    def crash(name, value):
        if name == 'cell-deadline-binding':
            raise SystemExit('fixture crash after campaign binding')
        return save(name, value)
    monkeypatch.setattr(bridge, '_save', crash)
    with pytest.raises(SystemExit):
        _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    clock = CellDeadline.restore(ContinuationStore(tmp_path / 'clock-bound.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    replacement = CNYInvocationBridge(ledger)
    replacement.bind_run(run)
    replacement.bind_cell_deadline(clock, plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'], cell_id='vendor-0')
    assert replacement.cell_deadline() is clock
    assert not calls and not ledger.snapshot()['pending_calls']


def test_timed_run_cannot_export_unqualified_recorded_replay(setup, tmp_path, monkeypatch):
    from core.llm import UsageError
    from test_governed_cny_bridge import complete
    ledger, bridge, run, context, providers, calls, store, physical = setup
    _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    assert bridge.invoke(context, ('prompt',), {}) == 'answer'
    complete(store)
    with pytest.raises(UsageError, match='deadline'):
        bridge.replay_bundle()


def test_recorded_bridge_rejects_unqualified_timed_run_bundle(setup, tmp_path, monkeypatch):
    from core.composition.external_provider import ExternalRunContext
    from core.llm import UsageError
    from test_governed_cny_bridge import complete
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    ledger, bridge, run, context, providers, calls, store, physical = setup
    _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    assert bridge.invoke(context, ('prompt',), {}) == 'answer'
    complete(store)
    bridge.audit()
    bundle = {'schema_version': 1, 'preparation': bridge._preparation, 'ready': bridge._ready.to_dict(),
              'calls': bridge._records(), 'terminals': [], 'currency_evidence': bridge._last_audit_evidence}
    recorded = CNYInvocationBridge(None)
    replay = ExternalRunContext(**{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': bundle},
        store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers)
    with pytest.raises(UsageError, match='deadline'):
        recorded.bind_run(replay)


def test_first_binding_rejects_existing_provider_start_without_fixture_rewrite(setup, tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    ledger, bridge, run, context, providers, calls, store, physical = setup
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: 100)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock-direct.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    with pytest.raises(ValueError, match='after work'):
        bridge.bind_cell_deadline(clock, plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'], cell_id='vendor-0')
    assert not calls and not ledger.snapshot()['pending_calls']


def test_public_currency_audit_rejects_unconsumed_replay_suffix(setup, monkeypatch):
    from core.llm import UsageError
    from test_governed_cny_bridge import complete
    ledger, bridge, run, context, providers, calls, store, physical = setup
    assert bridge.invoke(context, ('prompt',), {}) == 'answer'
    complete(store)
    monkeypatch.setattr(store, 'peek', lambda: {'kind': 'composed_provider_started', 'payload': {}}, raising=False)
    with pytest.raises(UsageError, match='replay'):
        bridge.audit()
    prefix = bridge._audit_replay_prefix()
    assert prefix['protection_valid'] and prefix['coverage_complete'] is False
