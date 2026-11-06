"""Join existing physical and CNY authorities for a single host invocation.

This component does not start a controller or implement full run recovery.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from core.composition.external_provider import GovernedCallContext, external_session_id
from core.llm import UsageError
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.host_physical import HostPhysicalAdmission


class HostDispatchRouter:
    """Route authenticated fixture requests to existing authorities."""
    def __init__(self, provider, stages):
        self.provider, self.stages = provider, stages

    def __call__(self, request_id, argument):
        from zoo.circle_packing.host_transport import _validate_argument
        _validate_argument(argument)
        if type(argument) is dict and set(argument) == {'host_messages', 'host_prompt_ref'} and self.provider:
            return self.provider(request_id, argument)
        if type(argument) is dict and set(argument) == {'stage', 'program', 'program_ref', 'prior_id'} and self.stages:
            result = self.stages.execute(request_id, argument['program'], stage=argument['stage'],
                                         prior_id=argument['prior_id'])
            return {'state': 'ok', 'result': json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False),
                    'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}
        raise ValueError('host route is not available')


class HostDispatchCoordinator:
    def __init__(self, budget, bridge, run, ready):
        if run.store is not budget.store or getattr(run.physical_identity_lookup, '__self__', None) is not budget \
                or bridge._run is not run or ready.physical_plan_ref != run.physical_plan['plan_ref']:
            raise ValueError('host authorities must share the same frozen physical run')
        self.physical = HostPhysicalAdmission(budget)
        self.budget, self.bridge, self.run, self.ready = budget, bridge, run, ready
        self.store = budget.store
        self.binding = run.main_provider_binding
        self.provider = run.provider_sessions['main']
        if self.provider.governance_binding() != self.binding or \
                self.provider.manifest_binding().get('message_mode') != 'openevolve_host_v1':
            raise ValueError('host provider must use its frozen exact-message mode')
        reservation = budget.options.get('operation_reservations', {}).get('operator', budget.options['reservation'])
        if reservation != {'token': self.binding['call_bound']['units']['token'], 'node': 1, 'eval_count': 0}:
            raise ValueError('host physical reservation must cover exactly one bounded provider call')

    def audit(self):
        """Join original provider receipts to both existing authorities."""
        from core.composition.provider_evidence import audit_provider_receipts
        physical = self.budget.audit_governance()
        currency = self.bridge.audit()
        if physical['open_intents'] or currency['unknown_cost_calls'] or not currency['protection_valid']:
            raise ValueError('host authorities contain unresolved or invalid operations')
        runtime = SimpleNamespace(store=self.store, budget=self.budget, _logical_run_id=self.run.logical_run_id,
            governed=SimpleNamespace(external_plan=self.ready, plan=self.run.physical_plan))
        sessions = {key: {'governance_binding': value}
                    for key, value in self.run.control_provider_bindings.items()}
        audit_provider_receipts(runtime, sessions, self.binding)
        return {'physical': physical, 'currency': currency}

    def __call__(self, request_id, argument):
        if type(argument) is not dict or set(argument) != {'host_messages', 'host_prompt_ref'}:
            raise ValueError('host invocation lacks its message binding')
        messages = argument['host_messages']
        if type(messages) is not dict or set(messages) != {'system', 'user'} or \
                any(type(messages[key]) is not str or not messages[key].strip() for key in messages) or \
                argument['host_prompt_ref'] != 'sha256:' + payload_digest(messages):
            raise ValueError('host invocation message binding differs')
        prompt = json.dumps(argument, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        args, kwargs = (prompt,), {}
        receipt = self.physical.begin(request_id)
        try:
            identity = self.budget.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
            authority = self.ready.authority_binding
            adapter_sha = payload_digest(self.binding)
            context = GovernedCallContext(schema_version=1, runtime_id=self.run.runtime_id,
                logical_run_id=self.run.logical_run_id, currency_run_id=authority['currency_run_id'],
                campaign_id=authority['campaign_id'], policy_sha256=authority['policy_sha256'],
                physical_plan_ref=self.run.physical_plan['plan_ref'], bridge_plan_ref=self.ready.bridge_plan_ref,
                lane='main', slot_id=None, candidate_id=identity['candidate_id'], intent_id=receipt.intent_id,
                physical_fingerprint=receipt.fingerprint, account=identity['account'], operation='operator',
                phase='operator', ordinal=0, adapter_binding_sha256=adapter_sha,
                session_id=external_session_id(self.run.logical_run_id, 'main', None, adapter_sha),
                argument_sha256=payload_digest({'args': args, 'kwargs': kwargs}))
            invocation = {'schema_version': 2, 'external_context': context.to_dict(), 'intent_id': receipt.intent_id,
                'fingerprint': receipt.fingerprint, 'lane': 'main', 'slot_id': None,
                'run_id': self.run.logical_run_id, 'adapter_binding_sha256': adapter_sha, 'ordinal': 0}
            binding = payload_digest({'request_sha256': context.argument_sha256, 'invocation': invocation})
            self.store.append('composed_provider_started', {'binding': binding,
                'request_sha256': context.argument_sha256, 'invocation': invocation})
            invoked, invoked_result = False, None
            try:
                invoked_result = self.bridge.invoke(context, args, kwargs)
                invoked = True
            except Exception:
                # Only the authority's durable outcome can distinguish a known
                # bill/refusal from an unresolved provider operation.
                pass
            outcome = self.bridge.recover(context, context.argument_sha256)
            if invoked and (outcome.outcome != 'returned' or invoked_result != outcome.result):
                raise UsageError('host response differs from durable currency outcome')
            if outcome.outcome == 'unknown' or outcome.usage is None:
                raise UsageError('host provider usage is unresolved')
            if outcome.outcome == 'returned':
                state, public_result, receipt_outcome = 'ok', outcome.result, 'returned'
            elif outcome.outcome == 'known_failed':
                state, public_result, receipt_outcome = 'known_failed', 'provider invocation failed (RuntimeError)', 'failed'
            elif outcome.outcome == 'known_refused':
                state, public_result, receipt_outcome = 'known_refused', 'provider invocation refused before dispatch', 'budget_exhausted'
            else:
                raise UsageError('host provider outcome is unsupported')
            if type(public_result) is not str:
                raise UsageError('host provider outcome has no validated result')
            completion = {'binding': binding, 'result': public_result, 'tokens': outcome.usage['total_tokens'],
                'state': None, 'observed_binding_sha256': payload_digest(self.provider.governance_binding())}
            if receipt_outcome != 'returned':
                completion['outcome'] = receipt_outcome
            self.store.append('composed_provider_completed', completion)
            self.physical.settle(receipt, tokens=outcome.usage['total_tokens'])
            return {'state': state, 'result': outcome.result if state == 'ok' else None, 'usage': outcome.usage}
        except Exception:
            try:
                if receipt.intent_id in self.budget.state()['open_intents']:
                    self.budget.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint,
                                                reason='host_dispatch_unresolved')
            except Exception:
                pass
            raise UsageError('host dispatch is unresolved or could not be proven') from None
