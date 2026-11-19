"""Dual admission, durable response adoption and portable CNY bridge proofs."""
import hashlib
import json

import pytest

from core.composition.external_provider import ExternalRunContext, GovernedCallContext, external_session_id
from core.llm import UsageError
from core.x1.checkpoint import payload_digest
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.provider_protocol import parse_response
from test_governed_cny_provider import local_endpoint, reply


class Store:
    restoring = False
    def __init__(self): self.rows = []
    def read(self, kind=None):
        return iter([r for r in self.rows if kind is None or r['kind'] == kind])
    def append(self, kind, payload): self.rows.append({'kind': kind, 'payload': payload})


@pytest.fixture
def setup(tmp_path, request):
    mode = getattr(request, 'param', 'single_user_v1')
    no_thinking = mode == 'no_thinking'
    if no_thinking:
        mode = 'single_user_v1'
    loopback = mode == 'openevolve_host_loopback'
    endpoint = request.getfixturevalue('local_endpoint') if loopback else None
    if loopback:
        mode = 'openevolve_host_v1'
    if mode == 'openevolve_v1':
        from test_openevolve_governed_transport import prompt
        argument = prompt()
    elif mode == 'openevolve_host_v1':
        from test_openevolve_governed_transport import host_prompt
        argument = host_prompt()
    else:
        argument = 'prompt'
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
        expected_head=ledger.snapshot()['journal_head'])
    providers = {key: GovernedCNYProvider('deepseek-flash', endpoint.url if loopback else 'http://127.0.0.1:1',
        campaign_binding=ledger.manifest_binding(), max_completion_tokens=4, api_key='fixture-only-secret', message_mode=mode,
        reasoning_effort='none' if no_thinking else 'high')
        for key in ('main', 'control-0000')}
    calls = []
    for key, provider in (() if loopback else providers.items()):
        def transport(body, provider=provider, key=key, **_kwargs):
            assert ledger.snapshot()['pending_calls']
            calls.append((key, body))
            return parse_response(json.dumps({'model': 'deepseek-flash',
                'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12},
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'answer'}}]}).encode(),
                provider.protocol_binding())
        provider.perform_request = transport
    store = Store()
    physical = {'intent_id': 'intent', 'physical_fingerprint': 'sha256:' + 'd' * 64,
        'candidate_id': 'candidate', 'lane': 'control', 'slot_id': 'control-0000',
        'account': 'control', 'operation': 'operator', 'phase': 'operator', 'status': 'started',
        'amounts': {'token': 1048580}}
    def lookup(intent, *, fingerprint):
        assert intent == physical['intent_id'] and fingerprint == physical['physical_fingerprint']
        return dict(physical)
    plan = {'schema_version': 1, 'slots': [{'slot_id': 'control-0000',
        'reservations': {'operator': {'token': 1048580}, 'evaluation': {'token': 0}}}]}
    plan['plan_ref'] = 'sha256:' + payload_digest(plan)
    run = ExternalRunContext(logical_run_id='a' * 32, runtime_id='composed-v8-governed-external',
        workdir=str(tmp_path), physical_plan=plan, main_provider_binding=providers['main'].governance_binding(),
        control_provider_bindings={'control-0000': providers['control-0000'].governance_binding()},
        mode='live', recorded_bundle=None, store=store, physical_identity_lookup=lookup,
        provider_sessions=providers)
    bridge = CNYInvocationBridge(ledger)
    ready = bridge.bind_run(run)
    args_sha = payload_digest({'args': (argument,), 'kwargs': {}})
    authority = ready.authority_binding
    context = GovernedCallContext(schema_version=1, runtime_id=run.runtime_id,
        logical_run_id=run.logical_run_id, currency_run_id=authority['currency_run_id'],
        campaign_id=authority['campaign_id'], policy_sha256=authority['policy_sha256'],
        physical_plan_ref=ready.physical_plan_ref, bridge_plan_ref=ready.bridge_plan_ref,
        **{k: v for k, v in physical.items() if k not in {'amounts', 'status'}}, ordinal=0,
        adapter_binding_sha256=payload_digest(run.control_provider_bindings['control-0000']),
        session_id=authority['session_ids']['control-0000'], argument_sha256=args_sha)
    inv = {'schema_version': 2, 'external_context': context.to_dict(), 'intent_id': context.intent_id,
        'fingerprint': context.physical_fingerprint, 'lane': context.lane, 'slot_id': context.slot_id,
        'run_id': context.logical_run_id, 'adapter_binding_sha256': context.adapter_binding_sha256, 'ordinal': 0}
    binding = payload_digest({'request_sha256': args_sha, 'invocation': inv})
    store.append('composed_provider_started', {'binding': binding, 'request_sha256': args_sha, 'invocation': inv})
    return ledger, bridge, run, context, providers, calls, store, physical


def complete(store):
    store.append('composed_provider_completed', {'binding': store.rows[-1]['payload']['binding'],
        'result': 'answer', 'tokens': 12, 'state': None,
        'observed_binding_sha256': store.rows[-1]['payload']['invocation']['adapter_binding_sha256']})


def test_bridge_admits_before_transport_and_replays_without_ledger(setup, monkeypatch):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    assert bridge.invoke(context, ('prompt',), {}) == 'answer'
    assert len(calls) == 1
    complete(store)
    bundle = bridge.replay_bundle()
    expected = bridge.audit()
    ledger.path.unlink()
    recorded = CNYInvocationBridge(None)
    recorded.bind_run(ExternalRunContext(**{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': bundle},
        store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers))
    assert recorded.audit() == expected
    assert recorded.recover(context, context.argument_sha256).result == 'answer'
    assert len(calls) == 1


@pytest.mark.parametrize('setup', ['openevolve_v1'], indirect=True)
def test_two_role_unknown_usage_keeps_campaign_reservation(setup):
    from test_openevolve_governed_transport import prompt
    ledger, bridge, run, context, providers, calls, store, physical = setup
    def missing_usage(body, **kwargs):
        return parse_response(json.dumps({'model': 'deepseek-flash',
            'choices': [{'finish_reason': 'stop', 'message': {'content': 'answer'}}]}).encode(),
            providers['control-0000'].protocol_binding())
    providers['control-0000'].perform_request = missing_usage
    with pytest.raises(UsageError):
        bridge.invoke(context, (prompt(),), {})
    assert ledger.snapshot()['pending_calls']
    assert bridge.recover(context, context.argument_sha256).outcome == 'unknown'
    assert ledger.snapshot()['pending_calls']


@pytest.mark.parametrize('setup', ['openevolve_host_v1'], indirect=True)
def test_host_role_bridge_preserves_exact_messages_and_audits_record(setup):
    from test_openevolve_governed_transport import host_prompt
    ledger, bridge, run, context, providers, calls, store, physical = setup
    assert bridge.invoke(context, (host_prompt(),), {}) == 'answer'
    assert json.loads(calls[0][1])['messages'] == [
        {'role': 'system', 'content': 'host system'}, {'role': 'user', 'content': 'host user'}]
    complete(store)
    assert bridge.audit()['protection_valid']
    assert bridge.replay_bundle()['calls'][0]['prepared']['argument'] == host_prompt()


@pytest.mark.parametrize('setup', ['openevolve_host_v1'], indirect=True)
def test_host_socket_calls_existing_currency_bridge_after_physical_admission(setup, tmp_path, monkeypatch, short_socket_dir):
    import asyncio
    import threading
    from types import SimpleNamespace
    from zoo.circle_packing.host_transport import HostBroker, HostBridgeClient
    ledger, bridge, run, context, providers, calls, store, physical = setup
    def dispatch(request_id, argument):
        result = bridge.invoke(context, (json.dumps(argument),), {})
        return {'state': 'ok', 'result': result, 'usage': providers['control-0000'].last_usage}
    path = short_socket_dir / 'host.sock'
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        worker = threading.Thread(target=broker.serve_one, daemon=True)
        worker.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostBridgeClient(SimpleNamespace(name='fixture'))
        assert asyncio.run(client.generate_with_context('host system',
            [{'role': 'user', 'content': 'host user'}])) == 'answer'
        worker.join(timeout=5)
    complete(store)
    assert bridge.audit()['protection_valid'] and len(calls) == 1
    assert not ledger.snapshot()['pending_calls']


@pytest.mark.parametrize('setup', ['openevolve_host_v1'], indirect=True)
def test_host_broker_stops_after_unknown_currency_usage(setup, tmp_path, monkeypatch, short_socket_dir):
    import asyncio
    import threading
    from types import SimpleNamespace
    from zoo.circle_packing.host_transport import HostBroker, HostBridgeClient
    ledger, bridge, run, context, providers, calls, store, physical = setup
    def missing_usage(body, **kwargs):
        calls.append(body)
        return parse_response(json.dumps({'model': 'deepseek-flash',
            'choices': [{'finish_reason': 'stop', 'message': {'content': 'answer'}}]}).encode(),
            providers['control-0000'].protocol_binding())
    providers['control-0000'].perform_request = missing_usage
    def dispatch(request_id, argument):
        result = bridge.invoke(context, (json.dumps(argument),), {})
        return {'state': 'ok', 'result': result, 'usage': providers['control-0000'].last_usage}
    path = short_socket_dir / 'unknown.sock'
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        thread = threading.Thread(target=lambda: [broker.serve_one() for _ in range(2)], daemon=True)
        thread.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        for _ in range(2):
            client = HostBridgeClient(SimpleNamespace(name='fixture'))
            with pytest.raises(UsageError):
                asyncio.run(client.generate_with_context('host system',
                    [{'role': 'user', 'content': 'host user'}]))
        thread.join(timeout=5)
    assert len(calls) == 1 and len(ledger.snapshot()['pending_calls']) == 1


@pytest.mark.parametrize('setup', ['openevolve_host_loopback'], indirect=True)
def test_actual_host_worker_routes_to_currency_bridge_over_loopback(setup, tmp_path, local_endpoint, short_socket_dir):
    import os
    import subprocess
    import sys
    import threading
    from core.composition.external_provider import GovernedCallContext
    from zoo.circle_packing.host_transport import HostBroker
    ledger, bridge, run, initial, providers, calls, store, physical = setup
    diff = ('<<<<<<< SEARCH\n    n = 26\n=======\n'
            '    n = 26\n    # bridged host fixture\n>>>>>>> REPLACE\n')
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    invoked = []
    def dispatch(request_id, argument):
        raw = json.dumps(argument)
        argument_sha = payload_digest({'args': (raw,), 'kwargs': {}})
        context = GovernedCallContext(**{**initial.to_dict(), 'argument_sha256': argument_sha})
        inv = {'schema_version': 2, 'external_context': context.to_dict(), 'intent_id': context.intent_id,
            'fingerprint': context.physical_fingerprint, 'lane': context.lane, 'slot_id': context.slot_id,
            'run_id': context.logical_run_id, 'adapter_binding_sha256': context.adapter_binding_sha256, 'ordinal': 0}
        binding = payload_digest({'request_sha256': argument_sha, 'invocation': inv})
        store.rows.clear()
        store.append('composed_provider_started', {'binding': binding, 'request_sha256': argument_sha, 'invocation': inv})
        result = bridge.invoke(context, (raw,), {})
        store.append('composed_provider_completed', {'binding': binding, 'result': result, 'tokens': 7,
            'state': None, 'observed_binding_sha256': context.adapter_binding_sha256})
        invoked.append(context)
        return {'state': 'ok', 'result': result, 'usage': providers['control-0000'].last_usage}
    path = short_socket_dir / 'real-host.sock'
    env = {key: value for key, value in os.environ.items() if 'API_KEY' not in key}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path),
               MORI_CIRCLE_BROKER_SOCKET=str(path), MORI_CIRCLE_BROKER_TOKEN='a' * 64,
               OPENAI_API_KEY='fixture-only-secret')
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        result = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.host_reference',
            '--output', str(tmp_path / 'host-run'), '--iterations', '1', '--fixture-broker'],
            env=env, capture_output=True, text=True, timeout=120, check=True)
        thread.join(timeout=5)
    assert json.loads(result.stdout)['stage_calls'] == 2
    assert len(invoked) == len(local_endpoint.requests) == 1
    assert bridge.audit()['protection_valid'] and not ledger.snapshot()['pending_calls']
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 38
    wire = json.loads(local_endpoint.requests[0])
    assert [message['role'] for message in wire['messages']] == ['system', 'user']
    for item in (tmp_path / 'host-run').rglob('*'):
        if item.is_file():
            assert b'fixture-only-secret' not in item.read_bytes()


@pytest.mark.parametrize('setup', ['openevolve_v1'], indirect=True)
def test_two_role_bridge_binds_original_argument_and_replays_without_dispatch(setup):
    from test_openevolve_governed_transport import prompt
    ledger, bridge, run, context, providers, calls, store, physical = setup
    assert bridge.invoke(context, (prompt(),), {}) == 'answer'
    assert [item['role'] for item in json.loads(calls[0][1])['messages']] == ['system', 'user']
    complete(store)
    bundle = bridge.replay_bundle()
    prepared = bundle['calls'][0]['prepared']
    assert prepared['schema_version'] == 2 and prepared['argument'] == prompt()
    import copy
    damaged = copy.deepcopy(bundle)
    damaged['calls'][0]['prepared']['argument'] += ' '
    with pytest.raises(ValueError):
        CNYInvocationBridge(None).bind_run(ExternalRunContext(
            **{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': damaged},
            store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers))
    expected = bridge.audit()
    recorded = CNYInvocationBridge(None)
    recorded.bind_run(ExternalRunContext(**{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': bundle},
        store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers))
    assert recorded.audit() == expected
    assert recorded.recover(context, context.argument_sha256).result == 'answer'
    assert len(calls) == 1


def test_recovery_settles_durable_response_without_redispatch(setup, monkeypatch):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    settle = ledger.settle
    def crash(*args, **kwargs): raise SystemExit('crash after response fsync')
    monkeypatch.setattr(ledger, 'settle', crash)
    with pytest.raises(SystemExit): bridge.invoke(context, ('prompt',), {})
    assert len(calls) == 1 and ledger.snapshot()['pending_calls']
    monkeypatch.setattr(ledger, 'settle', settle)
    restored = CNYInvocationBridge(ledger)
    restored.bind_run(run)
    assert restored.recover(context, context.argument_sha256).result == 'answer'
    assert restored.recover(context, context.argument_sha256).result == 'answer'
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 36
    assert len(calls) == 1


def test_admitted_missing_response_is_unknown_not_free_retry(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    def crash(body): raise SystemExit('crash after admission')
    providers['control-0000'].perform_request = crash
    with pytest.raises(SystemExit): bridge.invoke(context, ('prompt',), {})
    with pytest.raises(UsageError): bridge.recover(context, context.argument_sha256)
    assert ledger.snapshot()['pending_calls']


def test_context_tampering_and_ordinal_drift_fail_before_admission(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    for change in ({'candidate_id': 'other'}, {'ordinal': 1}, {'argument_sha256': '0' * 64}):
        with pytest.raises((ValueError, UsageError)):
            bridge.invoke(GovernedCallContext(**{**context.to_dict(), **change}), ('prompt',), {})
    assert not calls and not ledger.snapshot()['pending_calls']


def test_bad_model_retains_known_tokens_but_currency_pending(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    provider = providers['control-0000']
    provider.perform_request = lambda body: parse_response(json.dumps({'model': 'changed',
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12},
        'choices': [{'finish_reason': 'stop', 'message': {'content': 'answer'}}]}).encode(), provider.protocol_binding())
    with pytest.raises(UsageError): bridge.invoke(context, ('prompt',), {})
    assert provider.last_usage['total_tokens'] == 12
    assert ledger.snapshot()['pending_calls']


def test_terminal_must_be_root_authoritative_before_release(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    with pytest.raises(ValueError): bridge.finish_control('control-0000', 'sha256:' + '0' * 64)
    payload = {'slot_id': 'control-0000', 'plan_ref': run.physical_plan['plan_ref'], 'status': 'failed'}
    store.append('governed_control_terminal', payload)
    bridge.finish_control('control-0000', 'sha256:' + payload_digest(payload))
    assert ledger.audit_run(context.currency_run_id, context.physical_plan_ref)['outstanding_micro_cny'] == 0


def test_recovery_before_preparation_proves_zero_and_missing_preparation_after_admission_stops(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    zero = bridge.recover(context, context.argument_sha256)
    assert zero.outcome == 'known_refused' and zero.usage == {'total_tokens': 0}
    assert not ledger.snapshot()['pending_calls'] and not calls


def test_deleted_preparation_does_not_turn_real_charge_into_zero(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    bridge.invoke(context, ('prompt',), {})
    for path in bridge._spool.glob('call-*.json'):
        path.unlink()
    with pytest.raises(UsageError, match='without its local preparation'):
        bridge.recover(context, context.argument_sha256)
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 36


def test_binding_drift_survives_crash_and_fresh_provider_session(setup, monkeypatch):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    raw = providers['control-0000']
    perform = raw.perform_request
    original_binding = raw.governance_binding
    def changed(body):
        response = perform(body)
        raw.governance_binding = lambda: {**original_binding(), 'drift': True}
        return response
    raw.perform_request = changed
    settle = ledger.settle
    monkeypatch.setattr(ledger, 'settle', lambda *a: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): bridge.invoke(context, ('prompt',), {})
    monkeypatch.setattr(ledger, 'settle', settle)
    raw.governance_binding = original_binding
    restored = CNYInvocationBridge(ledger)
    restored.bind_run(run)
    outcome = restored.recover(context, context.argument_sha256)
    assert outcome.outcome == 'known_failed'
    assert outcome.integrity_reason == 'provider_binding_changed'
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 36
    store.append('composed_provider_completed', {'binding': store.rows[-1]['payload']['binding'],
        'result': 'provider invocation failed (RuntimeError)', 'tokens': 12, 'state': None,
        'outcome': 'failed', 'observed_binding_sha256': None})
    assert restored.audit()['protection_valid'] is False
    assert len(calls) == 1


def test_fixed_main_cap_survives_control_savings_and_rebind(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    cap = bridge._ready.authority_binding['main_currency_cap_micro_cny']
    bridge.invoke(context, ('prompt',), {})
    resumed = CNYInvocationBridge(ledger)
    assert resumed.bind_run(run).authority_binding['main_currency_cap_micro_cny'] == cap
    assert ledger.snapshot()['remaining_micro_cny'] > cap


def test_rehashed_changed_main_cap_rejected_by_original_prefix(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    store.rows.clear()
    bundle = bridge.replay_bundle()
    bundle['preparation']['main_currency_cap_micro_cny'] += 1
    bundle['ready']['authority_binding']['main_currency_cap_micro_cny'] += 1
    bundle['ready']['bridge_plan_ref'] = 'sha256:' + payload_digest(bundle['preparation'])
    recorded = CNYInvocationBridge(None)
    with pytest.raises(ValueError, match='original campaign capacity'):
        recorded.bind_run(ExternalRunContext(**{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': bundle},
            store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers))


def test_offline_missing_extra_or_changed_local_outcome_rejected(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    bridge.invoke(context, ('prompt',), {})
    complete(store)
    bundle = bridge.replay_bundle()
    for tamper in ('missing', 'extra', 'response', 'wire'):
        changed = json.loads(json.dumps(bundle))
        if tamper == 'missing': changed['calls'].clear()
        elif tamper == 'extra': changed['calls'].append(changed['calls'][0])
        elif tamper == 'response': changed['calls'][0]['response']['result'] = 'changed'
        else: changed['calls'][0]['prepared']['wire_body'] += ' '
        with pytest.raises((ValueError, UsageError)):
            CNYInvocationBridge(None).bind_run(ExternalRunContext(
                **{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': changed},
                store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers))


def test_missing_key_persists_zero_cost_refusal_without_dispatch(setup):
    from core.llm import ProviderBudgetExhausted
    ledger, bridge, run, context, providers, calls, store, physical = setup
    providers['control-0000']._api_key = None
    with pytest.raises(ProviderBudgetExhausted):
        bridge.invoke(context, ('prompt',), {})
    outcome = bridge.recover(context, context.argument_sha256)
    assert outcome.outcome == 'known_refused'
    assert outcome.integrity_reason == 'dispatch_refused'
    assert outcome.usage == {'total_tokens': 0}
    assert not calls and not ledger.snapshot()['pending_calls']
    store.append('composed_provider_completed', {'binding': store.rows[-1]['payload']['binding'],
        'result': 'provider readiness refused before dispatch', 'tokens': 0, 'state': None,
        'outcome': 'budget_exhausted', 'observed_binding_sha256': context.adapter_binding_sha256})
    assert bridge.audit()['protection_valid'] is True


def test_post_call_provider_state_is_durable_before_settlement(setup, monkeypatch):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    raw = providers['control-0000']
    raw.counter = 0
    raw.checkpoint_state = lambda: {'counter': raw.counter}
    perform = raw.perform_request
    def counted(body):
        raw.counter += 1
        return perform(body)
    raw.perform_request = counted
    settle = ledger.settle
    monkeypatch.setattr(ledger, 'settle', lambda *a: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): bridge.invoke(context, ('prompt',), {})
    raw.counter = 0  # Fresh adapter state after process death.
    monkeypatch.setattr(ledger, 'settle', settle)
    restored = CNYInvocationBridge(ledger)
    restored.bind_run(run)
    outcome = restored.recover(context, context.argument_sha256)
    assert outcome.provider_state == {'counter': 1}
    assert raw.counter == 0  # Core adoption owns restoring it into the provider.
    assert len(calls) == 1
    complete(store)
    with pytest.raises(ValueError, match='lost durable provider state'):
        restored.audit()
    store.rows[-1]['payload']['state'] = {'counter': 1}
    assert restored.audit()['protection_valid']


def test_unknown_transport_is_inspectable_but_cannot_replay(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    def timeout(body): raise UsageError('unknown transport')
    providers['control-0000'].perform_request = timeout
    with pytest.raises(UsageError): bridge.invoke(context, ('prompt',), {})
    pending = ledger.snapshot()['pending_calls']
    audit = bridge.audit()
    assert audit['unknown_cost_calls'] == pending
    assert audit['known_provider_tokens'] == 0
    assert audit['admission_open'] is False
    assert audit['authority']['pending_calls'] == pending
    with pytest.raises(UsageError): bridge.replay_bundle()
    with pytest.raises(UsageError): bridge.recover(context, context.argument_sha256)


from test_governed_cny_provider import local_endpoint


def test_public_framework_inspect_reports_unknown_pricing_without_replay(tmp_path, local_endpoint):
    from test_governed_cny_framework import campaign_fixture, framework, TASK
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(b'not-json')
    fw, _ = framework(tmp_path / 'run', campaign, local_endpoint)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    report = fw.inspect()['governance']['external_currency']
    assert report['unknown_cost_calls'] == campaign.snapshot()['pending_calls']
    assert report['admission_open'] is False
    assert report['known_provider_tokens'] == 0
    assert len(local_endpoint.requests) == 1
    with pytest.raises((UsageError, RuntimeError)):
        fw.replay(TASK)
    assert len(local_endpoint.requests) == 1


def recontext(setup_value, *, args=('prompt',), kwargs=None, main=False, intent='intent'):
    ledger, bridge, run, old, providers, calls, store, physical = setup_value
    kwargs = {} if kwargs is None else kwargs
    if main:
        physical.update(lane='main', slot_id=None, account='explore', intent_id=intent,
                        candidate_id='candidate-' + intent)
    key = 'main' if main else 'control-0000'
    context = GovernedCallContext(**{**old.to_dict(),
        **{k: v for k, v in physical.items() if k not in {'amounts', 'status'}},
        'session_id': bridge._ready.authority_binding['session_ids'][key],
        'argument_sha256': payload_digest({'args': args, 'kwargs': kwargs})})
    inv = {'schema_version': 2, 'external_context': context.to_dict(), 'intent_id': context.intent_id,
        'fingerprint': context.physical_fingerprint, 'lane': context.lane, 'slot_id': context.slot_id,
        'run_id': context.logical_run_id, 'adapter_binding_sha256': context.adapter_binding_sha256, 'ordinal': 0}
    store.append('composed_provider_started', {'binding': payload_digest({
        'request_sha256': context.argument_sha256, 'invocation': inv}),
        'request_sha256': context.argument_sha256, 'invocation': inv})
    return context


@pytest.mark.parametrize('args,kwargs', [(('prompt',), {'temperature': 1}), (('  ',), {})])
def test_unsupported_invocation_has_explicit_noncapacity_zero_proof(setup, args, kwargs):
    from core.llm import ProviderBudgetExhausted
    ledger, bridge, run, old, providers, calls, store, physical = setup
    store.rows.clear()
    context = recontext(setup, args=args, kwargs=kwargs)
    with pytest.raises(ProviderBudgetExhausted):
        bridge.invoke(context, args, kwargs)
    outcome = bridge.recover(context, context.argument_sha256)
    assert outcome.outcome == 'known_refused'
    assert outcome.integrity_reason == 'invocation_refused'
    assert outcome.usage == {'total_tokens': 0}
    assert not calls and not ledger.snapshot()['pending_calls']
    store.append('composed_provider_completed', {'binding': store.rows[-1]['payload']['binding'],
        'result': 'provider invocation refused before dispatch', 'tokens': 0, 'state': None,
        'outcome': 'budget_exhausted', 'observed_binding_sha256': context.adapter_binding_sha256})
    assert bridge.audit()['protection_valid']


@pytest.mark.parametrize('orphan', [False, True])
def test_new_main_intent_zero_proof_distinguishes_complete_old_call_from_orphan(setup, orphan):
    ledger, bridge, run, old, providers, calls, store, physical = setup
    store.rows.clear()
    first = recontext(setup, main=True, intent='first')
    assert bridge.invoke(first, ('prompt',), {}) == 'answer'
    complete(store)
    second = recontext(setup, main=True, intent='second')
    if orphan:
        for path in bridge._spool.glob('call-*.json'):
            path.unlink()
        with pytest.raises(UsageError):
            bridge.recover(second, second.argument_sha256)
    else:
        outcome = bridge.recover(second, second.argument_sha256)
        assert outcome.outcome == 'known_refused'
        assert outcome.usage == {'total_tokens': 0}
    assert len(calls) == 1
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 36


@pytest.mark.parametrize('setup', ['no_thinking'], indirect=True)
def test_non_thinking_call_replays_from_frozen_journal_without_redispatch(setup):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    assert bridge.invoke(context, ('prompt',), {}) == 'answer'
    assert json.loads(calls[0][1])['thinking'] == {'type': 'disabled'}
    complete(store)
    bundle = bridge.replay_bundle()
    recorded = CNYInvocationBridge(None)
    recorded.bind_run(ExternalRunContext(**{**run.to_dict(), 'mode': 'recorded', 'recorded_bundle': bundle},
        store=store, physical_identity_lookup=run.physical_identity_lookup, provider_sessions=providers))
    assert recorded.audit() == bridge.audit()
    assert recorded.recover(context, context.argument_sha256).result == 'answer'
    assert len(calls) == 1 and not ledger.snapshot()['pending_calls']
