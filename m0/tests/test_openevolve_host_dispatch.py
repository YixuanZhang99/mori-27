"""Join the real physical and currency authorities for a host call."""
import json

import pytest

from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget
from core.composition.external_provider import ExternalRunContext
from core.llm import UsageError
from core.x1.checkpoint import payload_digest
from core.x1.store import AppendOnlyStore
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_governed_transport import host_prompt
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


@pytest.fixture
def authority(tmp_path, local_endpoint):
    ledger = campaign_fixture(tmp_path)
    campaign = ledger.manifest_binding()
    def provider():
        return GovernedCNYProvider('deepseek-flash', local_endpoint.url, campaign_binding=campaign,
            max_completion_tokens=4, api_key='fixture-only-secret', message_mode='openevolve_host_v1')
    main, control = provider(), provider()
    bound = main.governance_binding()['call_bound']['units']['token']
    controls = {'after_main_cycles': [0], 'seed': 0,
        'provider': {'name': 'control'}, 'domain': {'name': 'control'}, 'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': {'operator': {'token': bound, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 1}}}
    limits = {'token': bound * 3, 'node': 8, 'eval_count': 8}
    options = {'limits': {level: dict(limits) for level in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'operator': {'token': bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}
    store = AppendOnlyStore(tmp_path / 'events.jsonl')
    budget = HierarchicalBudget(options, AccountingStamp('offline', 'fixture-v1', 'tokens-v1', 'price-v1', 'today'),
                                store, governance={'schema_version': 1, 'controls': controls})
    slots = [{'slot_id': 'control-0000', 'after_main_cycles': 0, 'request': controls['request'],
              'reservations': controls['reservations']}]
    plan = {'plan_ref': 'sha256:' + payload_digest({'slots': slots}), 'slots': slots}
    budget.protect_controls(plan)
    context = ExternalRunContext(logical_run_id='a' * 32, runtime_id='composed-v8-governed-external',
        workdir=str(tmp_path), physical_plan=plan, main_provider_binding=main.governance_binding(),
        control_provider_bindings={'control-0000': control.governance_binding()}, mode='live', recorded_bundle=None,
        store=store, physical_identity_lookup=budget.invocation_identity,
        provider_sessions={'main': main, 'control-0000': control})
    bridge = CNYInvocationBridge(ledger)
    ready = bridge.bind_run(context)
    return ledger, budget, bridge, context, ready, main


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
    with pytest.raises(ValueError, match='unresolved'):
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
