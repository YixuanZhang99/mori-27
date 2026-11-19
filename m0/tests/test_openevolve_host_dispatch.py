"""Join the real physical and currency authorities for a host call."""
import json

import pytest

from core.composition.budget import HierarchicalBudget
from core.llm import UsageError
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_governed_transport import host_prompt
from test_openevolve_host_control import control_authority


@pytest.fixture
def authority(control_authority):
    import asyncio
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    terminal = asyncio.run(HostSeedControl(budget, bridge, run, ready, domain).execute('control-0000'))
    assert terminal['status'] == 'evaluated'
    return ledger, budget, bridge, run, ready, run.provider_sessions['main']


@pytest.fixture
def timed_authority(control_authority, tmp_path, monkeypatch):
    import asyncio
    from test_openevolve_deadline_currency import _bound_clock
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    current = _bound_clock(ledger, bridge, tmp_path, monkeypatch)
    terminal = asyncio.run(HostSeedControl(budget, bridge, run, ready, domain).execute('control-0000'))
    assert terminal['status'] == 'evaluated'
    return ledger, budget, bridge, run, ready, run.provider_sessions['main'], current


def test_host_dispatch_reserves_physical_and_currency_and_settles_from_original_receipt(authority, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main = authority
    local_endpoint.responses.append(reply())
    perform = main.perform_request
    def observed(body, **kwargs):
        assert budget.state()['open_intents'] and ledger.snapshot()['pending_calls']
        return perform(body, **kwargs)
    monkeypatch.setattr(main, 'perform_request', observed)
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    outcome = dispatch('a' * 32, json.loads(host_prompt()))
    assert outcome['state'] == 'ok' and outcome['usage']['total_tokens'] == 7
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    assert budget.audit_governance()['physical_totals']['token'] == 7
    assert bridge.audit()['protection_valid']
    joined = dispatch.audit()
    assert joined['physical']['physical_totals']['token'] == 7
    assert joined['currency']['protection_valid']


def test_unknown_usage_retains_physical_and_currency_and_blocks_next_call(authority, local_endpoint):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main = authority
    local_endpoint.responses.append(reply(usage=None))
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    with pytest.raises(UsageError):
        dispatch('a' * 32, json.loads(host_prompt()))
    assert len(ledger.snapshot()['pending_calls']) == 1
    assert budget.state()['open_intents']
    with pytest.raises((ValueError, UsageError)):
        dispatch('b' * 32, json.loads(host_prompt()))
    with pytest.raises(ValueError):
        dispatch.audit()
    assert len(local_endpoint.requests) == 1


def test_host_refuses_underreserved_provider_before_dispatch(authority, local_endpoint):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main = authority
    budget.options['operation_reservations']['operator']['token'] -= 1
    with pytest.raises(ValueError, match='reservation'):
        HostDispatchCoordinator(budget, bridge, run, ready)
    assert not ledger.snapshot()['pending_calls'] and not local_endpoint.requests


def test_broker_preserves_proven_zero_cost_refusal(authority, local_endpoint, tmp_path, monkeypatch, short_socket_dir):
    import asyncio
    import threading
    from types import SimpleNamespace
    from core.llm import ProviderBudgetExhausted
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_transport import HostBroker, HostBridgeClient
    ledger, budget, bridge, run, ready, main = authority
    def refuse(*args, **kwargs):
        raise ValueError('fixture refusal')
    monkeypatch.setattr(main, 'validate_dispatch', refuse)
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    path = short_socket_dir / 'refused.sock'
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostBridgeClient(SimpleNamespace(name='fixture'))
        with pytest.raises(ProviderBudgetExhausted):
            asyncio.run(client.generate_with_context('host system', [{'role': 'user', 'content': 'host user'}]))
        thread.join(timeout=5)
    assert client.last_usage == {'total_tokens': 0}
    assert not ledger.snapshot()['pending_calls'] and not local_endpoint.requests
    assert not budget.state()['open_intents']
    assert dispatch.audit()['currency']['protection_valid']


def test_billed_provider_failure_settles_both_authorities(authority, local_endpoint):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main = authority
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'length',
                                                   'message': {'content': 'partial'}}]))
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    outcome = dispatch('a' * 32, json.loads(host_prompt()))
    assert outcome['state'] == 'known_failed' and outcome['usage']['total_tokens'] == 7
    assert not ledger.snapshot()['pending_calls'] and not budget.state()['open_intents']
    assert budget.audit_governance()['physical_totals']['token'] == 7
    assert dispatch.audit()['currency']['protection_valid']


def test_actual_host_worker_uses_both_real_budget_authorities(authority, local_endpoint, tmp_path, short_socket_dir):
    import os
    import subprocess
    import sys
    import threading
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_transport import HostBroker
    ledger, budget, bridge, run, ready, main = authority
    diff = ('<<<<<<< SEARCH\n    n = 26\n=======\n'
            '    n = 26\n    # physical and currency fixture\n>>>>>>> REPLACE\n')
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    path = short_socket_dir / 'governed-host.sock'
    env = {key: value for key, value in os.environ.items() if 'API_KEY' not in key}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64,
               OPENAI_API_KEY='fixture-only-secret')
    with HostBroker(path, 'a' * 64, HostDispatchCoordinator(budget, bridge, run, ready)) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        completed = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(tmp_path / 'host-run'), '--iterations', '1', '--fixture-broker'],
            env=env, capture_output=True, text=True, timeout=120, check=True)
        thread.join(timeout=5)
    assert json.loads(completed.stdout)['stage_calls'] == 2
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    assert budget.audit_governance()['physical_totals']['token'] == 7
    assert bridge.audit()['protection_valid']
    for item in (tmp_path / 'host-run').rglob('*'):
        if item.is_file():
            assert b'fixture-only-secret' not in item.read_bytes()


def test_actual_host_routes_provider_and_cascade_through_common_budget(authority, local_endpoint, tmp_path, short_socket_dir):
    import os
    import subprocess
    import sys
    import threading
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator, HostDispatchRouter
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main = authority
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    path = short_socket_dir / 'all-operations.sock'
    env = {key: value for key, value in os.environ.items() if 'API_KEY' not in key}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64,
               OPENAI_API_KEY='fixture-only-secret')
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'stage-work', control_authority=provider)
    with HostBroker(path, 'a' * 64, HostDispatchRouter(provider, stages)) as broker:
        thread = threading.Thread(target=lambda: [broker.serve_one() for _ in range(4)], daemon=True)
        thread.start()
        completed = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(tmp_path / 'host-run'), '--iterations', '1', '--fixture-broker',
            '--fixture-stage-broker'], env=env, capture_output=True, text=True, timeout=120, check=True)
        thread.join(timeout=5)
    assert json.loads(completed.stdout)['stage_calls'] == 3
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    totals = budget.audit_governance()['physical_totals']
    assert totals['token'] == 7 and totals['eval_count'] == 4
    assert provider.audit()['currency']['protection_valid']
    assert stages.audit() == {'schema_version': 1, 'stage_calls': 3, 'stage_one_calls': 2, 'stage_two_calls': 1}


def test_crash_after_currency_admission_blocks_new_work_after_budget_restore(authority, monkeypatch):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    ledger, budget, bridge, run, ready, main = authority
    def crash(*args, **kwargs):
        raise SystemExit('simulated crash after currency admission')
    monkeypatch.setattr(main, 'perform_request', crash)
    with pytest.raises(SystemExit):
        HostDispatchCoordinator(budget, bridge, run, ready)('a' * 32, json.loads(host_prompt()))
    assert len(ledger.snapshot()['pending_calls']) == 1
    restored = HierarchicalBudget(budget.options, budget.stamp, budget.store, governance=budget._governed.config)
    restored.restore_from_journal()
    with pytest.raises(ValueError, match='authority'):
        HostPhysicalAdmission(restored).begin('b' * 32)


def test_returned_value_must_match_durable_currency_outcome(authority, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main = authority
    local_endpoint.responses.append(reply())
    invoke = bridge.invoke
    def changed(*args, **kwargs):
        invoke(*args, **kwargs)
        return 'forged result'
    monkeypatch.setattr(bridge, 'invoke', changed)
    with pytest.raises(UsageError):
        HostDispatchCoordinator(budget, bridge, run, ready)('a' * 32, json.loads(host_prompt()))
    assert not ledger.snapshot()['pending_calls']
    assert budget.state()['open_intents'] and len(local_endpoint.requests) == 1


def test_host_does_not_return_late_billed_response(timed_authority, local_endpoint, tmp_path, monkeypatch):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main, current = timed_authority
    local_endpoint.responses.append(reply())
    perform = main.perform_request
    def late(*args, **kwargs):
        response = perform(*args, **kwargs)
        current['ns'] += 2700 * 1_000_000_000
        return response
    monkeypatch.setattr(main, 'perform_request', late)
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    with pytest.raises(TimeoutError):
        dispatch('a' * 32, json.loads(host_prompt()))
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    assert budget.audit_governance()['physical_totals']['token'] == 7
    assert not budget.state()['open_intents']
    assert dispatch.audit()['currency']['protection_valid']


def test_expired_host_rejects_before_main_physical_reservation(timed_authority, local_endpoint, tmp_path, monkeypatch):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, main, current = timed_authority
    current['ns'] += 2700 * 1_000_000_000
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    with pytest.raises(TimeoutError):
        dispatch('a' * 32, json.loads(host_prompt()))
    assert not local_endpoint.requests and not budget.state()['open_intents']
    assert not any(row['payload'].get('event') == 'reserve' and
                   row['payload']['data']['intent'].get('lane') == 'main'
                   for row in budget.store.read('hierarchical_budget'))


def test_host_stage_rejects_late_result_after_measured_settlement(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def late(program, *, stage, **kwargs):
        result = fake_result(program, stage, score=.4)
        current['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', late)
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage', control_authority=provider)
    with pytest.raises(TimeoutError):
        stages.execute('a' * 32, 'program', stage=1)
    assert budget.audit_governance()['physical_totals']['eval_count'] == 2
    assert not budget.state()['open_intents']
    anchor = ledger.stage_eligibility(ready.authority_binding['currency_run_id'], 'a' * 32)
    assert anchor is not None
    proof = list(budget.store.read('host_stage_eligibility'))[0]['payload']
    assert proof['observation']['eligible'] is False
    assert stages.audit()['ontime_stage_observations'] == 0


def test_host_stage_anchors_ontime_eligibility_to_original_result(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    assert stages.execute('a' * 32, 'program', stage=1)['status'] == 'ok'
    proof = list(budget.store.read('host_stage_eligibility'))[0]['payload']
    assert proof['observation']['eligible'] is True
    assert ledger.stage_eligibility(ready.authority_binding['currency_run_id'], 'a' * 32)['proof_sha256'] == __import__(
        'core.x1.checkpoint', fromlist=['payload_digest']).payload_digest(proof)
    assert stages.audit()['ontime_stage_observations'] == 1


def test_detached_currency_view_reads_original_host_stage_anchor(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    anchor = ledger.stage_eligibility(run_id, 'a' * 32)
    assert view.stage_eligibility(run_id, 'a' * 32) == anchor
    assert view.stage_eligibility(run_id, 'b' * 32) is None
    with pytest.raises(ValueError):
        view.stage_eligibility('f' * 64, 'a' * 32)
    anchor['cell_id'] = 'tampered'
    assert view.stage_eligibility(run_id, 'a' * 32)['cell_id'] != 'tampered'


def test_detached_reference_stage_audit_recomputes_original_eligible_geometry(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_stage
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    start = list(budget.store.read('host_stage_started'))[0]['payload']
    terminal = list(budget.store.read('host_stage_completed'))[0]['payload']
    proof = list(budget.store.read('host_stage_eligibility'))[0]['payload']
    result = audit_recorded_reference_stage(view, clock, run_id, start, terminal, proof)
    assert result['metrics'] == terminal['result']['metrics']
    assert result['geometry_ref'] == terminal['result']['geometry_ref']
    altered = dict(terminal, evidence_ref='sha256:' + 'f' * 64)
    with pytest.raises(ValueError):
        audit_recorded_reference_stage(view, clock, run_id, start, altered, proof)
    altered_proof = dict(proof, fingerprint='sha256:' + 'f' * 64)
    with pytest.raises(ValueError):
        audit_recorded_reference_stage(view, clock, run_id, start, terminal, altered_proof)
    unpinned = RecordedCurrencyView(evidence, expected_run_id=run_id)
    with pytest.raises(ValueError, match='pinned'):
        audit_recorded_reference_stage(unpinned, clock, run_id, start, terminal, proof)


def test_detached_reference_stage_audit_rejects_late_measured_result(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_stage
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def late(program, *, stage, **kwargs):
        result = fake_result(program, stage, score=.4)
        current['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', late)
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    with pytest.raises(TimeoutError):
        stages.execute('a' * 32, 'program', stage=1)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    start = list(budget.store.read('host_stage_started'))[0]['payload']
    terminal = list(budget.store.read('host_stage_completed'))[0]['payload']
    proof = list(budget.store.read('host_stage_eligibility'))[0]['payload']
    assert proof['observation']['eligible'] is False
    with pytest.raises(ValueError, match='eligibility'):
        audit_recorded_reference_stage(view, clock, run_id, start, terminal, proof)


def test_detached_reference_cascade_requires_matching_qualified_predecessor(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_cascade
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.7))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    stages.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    def bundle(request_id):
        return {kind: next(row['payload'] for row in budget.store.read('host_stage_' + kind)
                           if row['payload']['request_id'] == request_id)
                for kind in ('started', 'completed', 'eligibility')}
    first, second = bundle('a' * 32), bundle('b' * 32)
    result = audit_recorded_reference_cascade(view, clock, run_id, [first, second])
    assert result['stage_count'] == 2
    assert result['evidence_ref'] == second['completed']['evidence_ref']
    assert result['metrics'] == second['completed']['result']['metrics']
    with pytest.raises(ValueError):
        audit_recorded_reference_cascade(view, clock, run_id, [first])
    with pytest.raises(ValueError):
        audit_recorded_reference_cascade(view, clock, run_id, [second, first])
    changed = dict(second, started=dict(second['started'], prior_id='c' * 32))
    with pytest.raises(ValueError):
        audit_recorded_reference_cascade(view, clock, run_id, [first, changed])


def test_detached_reference_cascade_accepts_one_below_threshold_stage(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_cascade
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    row = {kind: list(budget.store.read('host_stage_' + kind))[0]['payload']
           for kind in ('started', 'completed', 'eligibility')}
    result = audit_recorded_reference_cascade(view, clock, run_id, [row])
    assert result['stage_count'] == 1
    assert result['metrics']['combined_score'] < .5
    with pytest.raises(ValueError):
        audit_recorded_reference_cascade(view, clock, run_id, [row, row])


def test_detached_reference_physical_audit_rebuilds_stage_settlements_and_order(timed_authority, tmp_path, monkeypatch):
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_physical
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.7))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    stages.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    rows = list(budget.store.read())
    options, stamp, governance = budget.options, asdict(budget.stamp), budget._governed.config
    def audit(transcript, ref):
        return audit_recorded_reference_physical(view, clock, run_id, options=options, stamp=stamp,
            governance=governance, rows=transcript, expected_rows_ref=ref,
            request_ids=['a' * 32, 'b' * 32])
    reference = 'sha256:' + payload_digest(rows)
    result = audit(rows, reference)
    assert result['stage_count'] == 2
    assert result['stage_eval_count'] == 2
    assert result['physical']['protection_valid']
    with pytest.raises(ValueError):
        audit(rows[:-1], reference)
    moved = list(rows)
    first = next(i for i, row in enumerate(moved) if row['kind'] == 'host_stage_eligibility' and
                 row['payload']['request_id'] == 'a' * 32)
    proof = moved.pop(first)
    second = next(i for i, row in enumerate(moved) if row['kind'] == 'host_stage_started' and
                  row['payload']['request_id'] == 'b' * 32)
    moved.insert(second + 1, proof)
    with pytest.raises(ValueError, match='order'):
        audit(moved, 'sha256:' + payload_digest(moved))


def test_detached_physical_audit_cannot_omit_a_failed_stage(timed_authority, tmp_path, monkeypatch):
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_physical
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', lambda program, *, stage, **kwargs:
                        fake_result(program, stage, score=.7, status='failed_to_run' if program == 'bad' else 'ok'))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    stages.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)
    earlier_rows = list(budget.store.read())
    assert stages.execute('c' * 32, 'bad', stage=1)['status'] == 'failed_to_run'
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    rows = list(budget.store.read())
    def audit(transcript):
        return audit_recorded_reference_physical(view, clock, run_id, options=budget.options,
            stamp=asdict(budget.stamp), governance=budget._governed.config, rows=transcript,
            expected_rows_ref='sha256:' + payload_digest(transcript), request_ids=['a' * 32, 'b' * 32])
    missing = [row for row in rows if not (row['kind'].startswith('host_stage_') and
                                          row['payload'].get('request_id') == 'c' * 32)]
    with pytest.raises(ValueError, match='stage.*coverage'):
        audit(missing)
    with pytest.raises(ValueError, match='stage.*coverage'):
        audit(earlier_rows)
    duplicate = rows + [next(row for row in rows if row['kind'] == 'host_stage_started' and
                             row['payload']['request_id'] == 'c' * 32)]
    with pytest.raises(ValueError, match='stage.*coverage'):
        audit(duplicate)
    result = audit(rows)
    assert result['all_stage_count'] == 3
    assert result['failed_stage_count'] == 1


def test_detached_physical_audit_distinguishes_failed_and_unattempted_cascades(timed_authority, tmp_path, monkeypatch):
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_physical
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def measure(program, *, stage, **kwargs):
        status = 'failed_to_run' if program == 'fails-second' and stage == 2 else 'ok'
        return fake_result(program, stage, score=.7, status=status)
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', measure)
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'winner', stage=1)
    stages.execute('b' * 32, 'winner', stage=2, prior_id='a' * 32)
    stages.execute('c' * 32, 'fails-second', stage=1)
    assert stages.execute('d' * 32, 'fails-second', stage=2, prior_id='c' * 32)['status'] == 'failed_to_run'
    stages.execute('e' * 32, 'unattempted', stage=1)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    rows = list(budget.store.read())
    result = audit_recorded_reference_physical(view, clock, run_id, options=budget.options,
        stamp=asdict(budget.stamp), governance=budget._governed.config, rows=rows,
        expected_rows_ref='sha256:' + payload_digest(rows), request_ids=['a' * 32, 'b' * 32])
    assert result['all_stage_count'] == 5 and result['failed_stage_count'] == 1
    assert result['unattempted_first_stages'] == ['e' * 32]
    assert result['cascade_issues'] == [{'first_request_id': 'c' * 32, 'second_request_id': 'd' * 32,
                                         'reason': 'failed'}]


@pytest.mark.parametrize('failed', [False, True])
def test_detached_physical_audit_reports_late_second_stage(timed_authority, tmp_path, monkeypatch, failed):
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_physical
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def measure(program, *, stage, **kwargs):
        late = program == 'late' and stage == 2
        value = fake_result(program, stage, score=.7, status='failed_to_run' if late and failed else 'ok')
        if late:
            current['ns'] += 2700 * 1_000_000_000
        return value
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', measure)
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'winner', stage=1)
    stages.execute('b' * 32, 'winner', stage=2, prior_id='a' * 32)
    stages.execute('c' * 32, 'late', stage=1)
    with pytest.raises(TimeoutError):
        stages.execute('d' * 32, 'late', stage=2, prior_id='c' * 32)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    rows = list(budget.store.read())
    result = audit_recorded_reference_physical(view, clock, run_id, options=budget.options,
        stamp=asdict(budget.stamp), governance=budget._governed.config, rows=rows,
        expected_rows_ref='sha256:' + payload_digest(rows), request_ids=['a' * 32, 'b' * 32])
    assert result['late_stage_count'] == 1
    assert result['failed_stage_count'] == int(failed)
    assert result['unattempted_first_stages'] == []
    assert result['cascade_issues'] == [{'first_request_id': 'c' * 32, 'second_request_id': 'd' * 32,
                                         'reason': 'failed_and_late' if failed else 'late'}]


def test_detached_physical_audit_rejects_metrics_on_failed_stage(timed_authority, tmp_path, monkeypatch):
    from dataclasses import asdict
    from core.x1.checkpoint import payload_digest
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.reference_selection import audit_recorded_reference_physical
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def measure(program, *, stage, **kwargs):
        value = fake_result(program, stage, score=.4, status='failed_to_run' if program == 'bad' else 'ok')
        if program == 'bad':
            value['metrics'] = {'combined_score': 99}
        return value
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', measure)
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    from zoo.circle_packing import host_physical
    validate = host_physical._validate_stage_result
    monkeypatch.setattr(host_physical, '_validate_stage_result', lambda *args, **kwargs: None)
    stages.execute('a' * 32, 'program', stage=1)
    stages.execute('b' * 32, 'bad', stage=1)
    monkeypatch.setattr(host_physical, '_validate_stage_result', validate)
    run_id = ready.authority_binding['currency_run_id']
    evidence = ledger.export_governance_evidence(run_id, ready.physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
    clock = RecordedCellClock(bridge.cell_deadline().export_evidence(), view.cell_deadline_claim('vendor-0'))
    rows = list(budget.store.read())
    with pytest.raises(ValueError, match='failed.*metrics'):
        audit_recorded_reference_physical(view, clock, run_id, options=budget.options,
            stamp=asdict(budget.stamp), governance=budget._governed.config, rows=rows,
            expected_rows_ref='sha256:' + payload_digest(rows), request_ids=['a' * 32])


def test_host_stage_rejects_failed_result_with_metrics(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def malformed(program, *, stage, **kwargs):
        value = fake_result(program, stage, status='failed_to_run')
        value['metrics'] = {'combined_score': 99}
        return value
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', malformed)
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    with pytest.raises(ValueError, match='failed.*metrics'):
        stages.execute('a' * 32, 'program', stage=1)
    assert budget.state()['open_intents']


def test_host_stage_rejects_boolean_metric_equal_to_numeric_value(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    def malformed(program, *, stage, **kwargs):
        value = fake_result(program, stage, score=.4)
        value['metrics']['validity'] = True
        return value
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', malformed)
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    with pytest.raises(ValueError, match='geometry.*metrics'):
        stages.execute('a' * 32, 'program', stage=1)
    assert budget.state()['open_intents']


def test_host_stage_audit_rejects_changed_eligibility(timed_authority, tmp_path, monkeypatch):
    import copy
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    original = budget.store.read
    def altered(kind=None):
        rows = copy.deepcopy(list(original(kind)))
        for row in rows:
            if row['kind'] == 'host_stage_eligibility':
                row['payload']['observation']['eligible'] = False
        return iter(rows)
    monkeypatch.setattr(budget.store, 'read', altered)
    with pytest.raises(ValueError, match='eligibility'):
        stages.audit()


def test_host_stage_audit_requires_prior_eligibility_before_second_stage(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    stages.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)
    assert stages.audit()['stage_calls'] == 2
    original = budget.store.read
    def reordered(kind=None):
        rows = list(original(kind))
        if kind is None:
            proof_index = next(i for i, row in enumerate(rows) if row['kind'] == 'host_stage_eligibility'
                               and row['payload']['request_id'] == 'a' * 32)
            proof = rows.pop(proof_index)
            second = next(i for i, row in enumerate(rows) if row['kind'] == 'host_stage_started'
                          and row['payload']['request_id'] == 'b' * 32)
            rows.insert(second + 1, proof)
        return iter(rows)
    monkeypatch.setattr(budget.store, 'read', reordered)
    with pytest.raises(ValueError, match='eligibility'):
        stages.audit()


def test_host_stage_two_rejects_prior_proof_before_settlement(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    stages.execute('a' * 32, 'program', stage=1)
    original = budget.store.read
    def reordered(kind=None):
        rows = list(original(kind))
        if kind is None:
            index = next(i for i, row in enumerate(rows) if row['kind'] == 'host_stage_eligibility')
            proof = rows.pop(index)
            settle = next(i for i, row in enumerate(rows) if row['kind'] == 'hierarchical_budget'
                          and row['payload'].get('event') == 'settle'
                          and row['payload'].get('data', {}).get('intent_id') == 'host-stage:' + 'a' * 32)
            rows.insert(settle, proof)
        return iter(rows)
    monkeypatch.setattr(budget.store, 'read', reordered)
    with pytest.raises(ValueError, match='eligibility'):
        stages.execute('b' * 32, 'program', stage=2, prior_id='a' * 32)


def test_host_stage_anchor_crash_keeps_cost_and_blocks_audit(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage',
                        lambda program, *, stage, **kwargs: fake_result(program, stage, score=.4))
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage',
                                control_authority=authority)
    def crash(*args, **kwargs):
        raise RuntimeError('fixture anchor failure')
    monkeypatch.setattr(ledger, 'anchor_stage_eligibility', crash)
    with pytest.raises(RuntimeError, match='anchor failure'):
        stages.execute('a' * 32, 'program', stage=1)
    assert budget.audit_governance()['physical_totals']['eval_count'] == 2
    assert not budget.state()['open_intents']
    with pytest.raises(ValueError, match='eligibility'):
        stages.audit()


def test_host_stage_uses_remaining_cell_time_as_sandbox_timeout(timed_authority, tmp_path, monkeypatch):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    current['ns'] += 2699 * 1_000_000_000
    timeouts = []
    def stage(program, *, stage, timeout, **kwargs):
        timeouts.append(timeout)
        return fake_result(program, stage, score=.4)
    monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', stage)
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage', control_authority=provider)
    assert stages.execute('a' * 32, 'program', stage=1)['status'] == 'ok'
    assert timeouts == [1.0]


def test_cannot_first_bind_clock_after_independent_control(authority, tmp_path, monkeypatch):
    from test_openevolve_deadline_currency import _bound_clock
    ledger, budget, bridge, run, ready, main = authority
    with pytest.raises(ValueError, match='after work'):
        _bound_clock(ledger, bridge, tmp_path, monkeypatch)


def test_host_deadline_refusal_after_physical_start_is_not_capacity_refusal(timed_authority, monkeypatch):
    ledger, budget, bridge, run, ready, main, current = timed_authority
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    original = bridge.invoke
    def expire_before_bridge(*args, **kwargs):
        current['ns'] += 2700 * 1_000_000_000
        return original(*args, **kwargs)
    monkeypatch.setattr(bridge, 'invoke', expire_before_bridge)
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    with pytest.raises(TimeoutError):
        dispatch('a' * 32, json.loads(host_prompt()))
    records = bridge._records()
    assert len(records) == 1 and records[0]['outcome']['integrity_reason'] == 'deadline_refused'
    assert not ledger.snapshot()['pending_calls'] and not budget.state()['open_intents']


def test_host_sandbox_timeout_is_bounded_by_remaining_cell_time(timed_authority, tmp_path):
    import time
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, budget, bridge, run, ready, main, current = timed_authority
    current['ns'] += 2_699_500_000_000
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'host-stage', control_authority=provider)
    started = time.monotonic()
    result = stages.execute('a' * 32, 'while True:\n    pass\n', stage=1)
    assert result['status'] == 'timeout'
    assert time.monotonic() - started < 5
    assert budget.audit_governance()['physical_totals']['eval_count'] == 2


def test_settled_failure_then_next_request_share_original_authorities(authority, local_endpoint, monkeypatch, short_socket_dir):
    import asyncio
    import threading
    from types import SimpleNamespace
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_transport import HostBridgeClient, HostBroker, SettledProviderFailure
    ledger, budget, bridge, run, ready, main = authority
    local_endpoint.responses.extend([
        reply(choices=[{'finish_reason': 'length', 'message': {'content': 'partial'}}]),
        reply(),
    ])
    path = short_socket_dir / 'settled-authority.sock'
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    with HostBroker(path, 'a' * 64, dispatch, continue_settled_failures=True) as broker:
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostBridgeClient(SimpleNamespace(name='fixture'), continue_settled_failures=True)
        thread = threading.Thread(target=lambda: (broker.serve_one(), broker.serve_one()), daemon=True)
        thread.start()
        with pytest.raises(SettledProviderFailure):
            asyncio.run(client.generate_with_context('system', [{'role': 'user', 'content': 'first'}]))
        assert client.last_usage['total_tokens'] == 7
        assert not ledger.snapshot()['pending_calls'] and not budget.state()['open_intents']
        assert asyncio.run(client.generate_with_context('system', [{'role': 'user', 'content': 'second'}]))
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(local_endpoint.requests) == 2
    assert not ledger.snapshot()['pending_calls'] and not budget.state()['open_intents']
    assert budget.audit_governance()['physical_totals']['token'] == 14
    assert dispatch.audit()['currency']['protection_valid']


def test_upstream_fixture_can_continue_after_settled_failure(authority, local_endpoint, tmp_path, short_socket_dir):
    import os
    import subprocess
    import sys
    import threading
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_transport import HostBroker
    ledger, budget, bridge, run, ready, main = authority
    diff = ('<<<<<<< SEARCH\n    n = 26\n=======\n'
            '    n = 26\n    # subsequent fixture iteration\n>>>>>>> REPLACE\n')
    local_endpoint.responses.extend([
        reply(choices=[{'finish_reason': 'length', 'message': {'content': 'partial'}}]),
        reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]),
    ])
    path = short_socket_dir / 'continue-host.sock'
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64)
    with HostBroker(path, 'a' * 64, HostDispatchCoordinator(budget, bridge, run, ready),
                    continue_settled_failures=True) as broker:
        thread = threading.Thread(target=lambda: (broker.serve_one(), broker.serve_one()), daemon=True)
        thread.start()
        completed = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(tmp_path / 'host-run'), '--iterations', '2', '--fixture-broker',
            '--fixture-continue-settled-failures'], env=env, capture_output=True, text=True, timeout=120)
        assert completed.returncode == 0, completed.stderr[-2000:]
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(local_endpoint.requests) == 2
    assert not ledger.snapshot()['pending_calls'] and not budget.state()['open_intents']
    assert budget.audit_governance()['physical_totals']['token'] == 14
    report = json.loads(completed.stdout)
    assert report['mode'] == 'fixture' and report['performance_claim'] is False
    states = [item['state'] for item in report['iteration_trace']['iterations']]
    assert 'worker_error' in states and 'candidate' in states


def test_upstream_fixture_does_not_retry_unknown_usage(authority, local_endpoint, tmp_path, short_socket_dir):
    import os
    import subprocess
    import sys
    import threading
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_transport import HostBroker
    ledger, budget, bridge, run, ready, main = authority
    local_endpoint.responses.append(reply(usage=None))
    path = short_socket_dir / 'unknown-host.sock'
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64)
    with HostBroker(path, 'a' * 64, HostDispatchCoordinator(budget, bridge, run, ready),
                    continue_settled_failures=True) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        completed = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(tmp_path / 'host-run'), '--iterations', '2', '--fixture-broker',
            '--fixture-continue-settled-failures'], env=env, capture_output=True, text=True, timeout=120)
        assert completed.returncode != 0
        assert 'unresolved operation' in completed.stderr
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(local_endpoint.requests) == 1
    assert len(ledger.snapshot()['pending_calls']) == 1
    assert budget.state()['open_intents']
    assert not completed.stdout.strip()
