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
