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


def test_broker_preserves_proven_zero_cost_refusal(authority, local_endpoint, tmp_path, monkeypatch):
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
    path = tmp_path / 'refused.sock'
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


def test_actual_host_worker_uses_both_real_budget_authorities(authority, local_endpoint, tmp_path):
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
    path = tmp_path / 'governed-host.sock'
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


def test_actual_host_routes_provider_and_cascade_through_common_budget(authority, local_endpoint, tmp_path):
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
    path = tmp_path / 'all-operations.sock'
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
