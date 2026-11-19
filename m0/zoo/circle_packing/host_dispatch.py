"""Join existing physical and CNY authorities for a single host invocation.

This component does not start a controller or implement full run recovery.
"""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import re
from types import SimpleNamespace

from core.composition.external_provider import GovernedCallContext, external_session_id
from core.llm import UsageError
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.host_physical import HostPhysicalAdmission


class HostDispatchRouter:
    """Route authenticated fixture requests to existing authorities."""
    def __init__(self, provider, stages):
        self.provider, self.stages = provider, stages
        if stages is not None and stages.budget._require_initial_control and (provider is None or stages.control_authority is not provider):
            raise ValueError('host stages require their original control authority')
        if provider is not None and stages is not None:
            if stages.budget is not provider.budget:
                raise ValueError('host provider and stages must share the same budget')
            from zoo.mle_bench_lite.composed_domain import SandboxRunner
            main_path = stages.workspace.resolve()
            control_path = provider.control_domain.workspace.resolve()
            if type(stages.runner) is not SandboxRunner or stages.runner is provider.control_domain.runner or \
                    stages.runner.manifest_binding != provider.control_domain.runner.manifest_binding or \
                    main_path == control_path or main_path in control_path.parents or control_path in main_path.parents:
                raise ValueError('main and control stages require independent matched sandbox environments')

    def __call__(self, request_id, argument):
        from zoo.circle_packing.host_transport import _validate_argument
        _validate_argument(argument)
        if type(argument) is dict and set(argument) == {'host_messages', 'host_prompt_ref'} and self.provider:
            return self.provider(request_id, argument)
        if type(argument) is dict and set(argument) == {'stage', 'program', 'program_ref', 'prior_id'} and self.stages:
            with self.stages.budget._lock:
                if self.provider is not None:
                    self.provider._require_control()
                result = self.stages.execute(request_id, argument['program'], stage=argument['stage'],
                                             prior_id=argument['prior_id'])
            return {'state': 'ok', 'result': json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False),
                    'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}
        raise ValueError('host route is not available')


class HostDispatchCoordinator:
    def __init__(self, budget, bridge, run, ready, *, runner=None, owner_check=None, owner_operation=None):
        if owner_check is not None and not callable(owner_check):
            raise ValueError('dispatch owner check must be callable')
        if owner_operation is not None and not callable(owner_operation):
            raise ValueError('dispatch owner operation must be callable')
        self._owner_check = owner_check
        self._owner_operation = owner_operation
        if not budget._require_initial_control or run.store is not budget.store or getattr(run.physical_identity_lookup, '__self__', None) is not budget \
                or bridge._run is not run or ready.physical_plan_ref != run.physical_plan['plan_ref']:
            raise ValueError('host authorities must share the same frozen physical run')
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
        if run.physical_plan.get('schema_version') != 1 or len(run.physical_plan.get('slots', [])) != 1:
            raise ValueError('host requires a complete frozen control plan')
        budget._governed.validate_plan(run.physical_plan)
        from zoo.circle_packing.domain import CirclePackingDomain
        from zoo.mle_bench_lite.composed_domain import SandboxRunner
        if runner is not None and (type(runner) is not SandboxRunner or
                runner._campaign_runtime is not None and runner._campaign_runtime[0] is not bridge.ledger):
            raise ValueError('host runner must belong to the campaign')
        from zoo.circle_packing.host_control import _require_campaign_runtime
        _require_campaign_runtime(bridge.ledger, runner, bridge=bridge)
        slot = run.physical_plan['slots'][0]
        if type(slot['slot_id']) is not str or not re.fullmatch(r'control-[0-9]{4}', slot['slot_id']):
            raise ValueError('host requires a canonical control slot identity')
        frozen = run.physical_plan['initial_context'].get('circle_domain_binding')
        self.control_domain = CirclePackingDomain(Path(run.workdir) / 'host-controls' / slot['slot_id'],
                                                   runner=SandboxRunner() if runner is None else runner.independent_runner())
        if self.control_domain.manifest_binding != frozen:
            raise ValueError('host control audit domain differs from frozen evaluation binding')
        self.physical = HostPhysicalAdmission(budget, control_authority=self)

    def _require_control(self):
        if self._owner_check is not None:
            self._owner_check()
        from core.composition.governance_audit import audit_terminals
        from zoo.circle_packing.host_control import _require_campaign_runtime
        _require_campaign_runtime(self.bridge.ledger, self.control_domain.runner, bridge=self.bridge)
        slot_id = self.run.physical_plan['slots'][0]['slot_id']
        runtime = SimpleNamespace(store=self.store, budget=self.budget, _logical_run_id=self.run.logical_run_id)
        terminals = audit_terminals(runtime, self.run.physical_plan, {slot_id: {'domain': self.control_domain}})
        terminal = terminals.get(slot_id)
        if terminal is None or terminal['status'] != 'evaluated':
            raise ValueError('host main work requires a completed valid independent control')
        if self.budget.state().get('initial_control_ready') != {'slot_id': slot_id, 'terminal_ref': 'sha256:' + payload_digest(terminal)}:
            raise ValueError('host control lacks durable physical authorization')
        proof = self.bridge._load('terminal-' + slot_id)
        if proof != {'slot_id': slot_id, 'terminal_ref': 'sha256:' + payload_digest(terminal), 'terminal': terminal}:
            raise ValueError('host control lacks its durable currency terminal')
        currency = self.bridge.audit()
        if currency['unknown_cost_calls'] or not currency['protection_valid']:
            raise ValueError('host currency protection is unresolved or invalid')

    def audit(self):
        """Join original provider receipts to both existing authorities."""
        from core.composition.provider_evidence import audit_provider_receipts
        self._require_control()
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
        with self._owner_operation() if self._owner_operation is not None else nullcontext():
            with self.budget._lock:
                if self._owner_check is not None:
                    self._owner_check()
                return self._invoke(request_id, argument)

    def _invoke(self, request_id, argument):
        if type(argument) is not dict or set(argument) != {'host_messages', 'host_prompt_ref'}:
            raise ValueError('host invocation lacks its message binding')
        messages = argument['host_messages']
        if type(messages) is not dict or set(messages) != {'system', 'user'} or \
                any(type(messages[key]) is not str or not messages[key].strip() for key in messages) or \
                argument['host_prompt_ref'] != 'sha256:' + payload_digest(messages):
            raise ValueError('host invocation message binding differs')
        prompt = json.dumps(argument, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        args, kwargs = (prompt,), {}
        with self.budget._lock:
            self._require_control()
            deadline = self.bridge.cell_deadline()
            if deadline is not None:
                deadline.check()
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
            from zoo.circle_packing.cell_deadline import DeadlineExpired
            invoked, invoked_result, deadline_expired = False, None, False
            try:
                invoked_result = self.bridge.invoke(context, args, kwargs)
                invoked = True
            except DeadlineExpired:
                deadline_expired = True
            except Exception:
                # Only the authority's durable outcome can distinguish a known
                # bill/refusal from an unresolved provider operation.
                pass
            # Trusted recovery accounts the original call before its deadline
            # is rechecked; a timed-out pre-admission refusal is not a budget refusal.
            reason = 'deadline_refused' if deadline_expired else 'capacity_refused'
            outcome = self.bridge._recover(context, context.argument_sha256, refusal_reason=reason)
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
            if deadline_expired:
                self.store.append('composed_provider_deadline_expired', {'binding': binding})
            self.physical.settle(receipt, tokens=outcome.usage['total_tokens'])
            public_reply = {'state': state, 'result': outcome.result if state == 'ok' else None, 'usage': outcome.usage}
        except Exception:
            try:
                if receipt.intent_id in self.budget.state()['open_intents']:
                    self.budget.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint,
                                                reason='host_dispatch_unresolved')
            except Exception:
                pass
            raise UsageError('host dispatch is unresolved or could not be proven') from None
        deadline = self.bridge.cell_deadline()
        if deadline is not None:
            deadline.check()
        return public_reply
