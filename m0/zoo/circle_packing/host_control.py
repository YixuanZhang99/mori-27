"""Protected zero-provider seed control through the existing invocation lifecycle."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import math
import re
from types import SimpleNamespace

from core.composition.contracts import OperatorRequest, Proposal
from core.composition.defaults import InProcessExecutor
from core.composition.evaluation import MeasuredEvaluationError, binding_for, encode_evidence, validate_evidence
from core.composition.governance_audit import audit_terminals
from core.composition.hierarchical_runtime import HierarchicalRuntime
from core.composition.invocation import InvocationLifecycle
from core.composition.provider import MeteredProvider
from core.composition.provider_evidence import invocation_records
from core.composition.recovery import ContinuationStore
from core.executor.types import Candidate, CostVec, EvalRequest, EvalStatus
from core.llm import UsageError
from core.x1.checkpoint import payload_digest
from core.composition.openevolve_registration import _SEED, _SEED_SHA, _frozen_source
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.composed_domain import SandboxRunner


class _NoProvider:
    last_usage = {'total_tokens': 0}
    def __call__(self, *_args, **_kwargs):
        raise UsageError('seed control forbids provider calls')


class _ControlGuard:
    def __init__(self, budget):
        self.budget = budget

    @contextmanager
    def meter(self, provider, receipt, *, lane, slot_id):
        if lane != 'control' or not slot_id or provider.usage_total != 0:
            raise UsageError('seed control requires an independent zero-provider lane')
        yield
        if provider.usage_total != 0:
            raise UsageError('seed control consumed provider usage')

    def check_integrity(self, receipt):
        if not self.budget.audit_governance()['protection_valid']:
            raise UsageError('control protection is invalid')


class _SeedOperator:
    def __init__(self, candidate, seed):
        self.candidate, self.seed = candidate, seed

    async def propose(self, request):
        if request.candidate_id != self.candidate.id or request.parents or request.evidence:
            raise ValueError('seed control must be parentless and independent')
        return Proposal(self.candidate, self.seed, CostVec(node_count=1), ('token', 'node', 'eval_count'))


class HostSeedControl:
    """Execute one frozen control without a provider; fail closed on interruption."""
    def __init__(self, budget, bridge, run, ready, domain):
        if not budget._require_initial_control or not isinstance(budget.store, ContinuationStore) or run.store is not budget.store or \
                getattr(run.physical_identity_lookup, '__self__', None) is not budget or bridge._run is not run or \
                ready.physical_plan_ref != run.physical_plan['plan_ref'] or type(domain) is not CirclePackingDomain or \
                type(domain.runner) is not SandboxRunner or domain.stage_timeout != 60:
            raise ValueError('control requires the original physical run and a fresh circle domain')
        if domain.checkpoint_state()['entries']:
            raise ValueError('main domain must start without prior candidate state')
        if len(run.physical_plan.get('slots', [])) != 1 or \
                run.physical_plan['slots'][0]['operator']['name'] != 'draft' or \
                not re.fullmatch(r'control-[0-9]{4}', run.physical_plan['slots'][0]['slot_id']):
            raise ValueError('seed control requires one frozen parentless draft slot')
        slot = run.physical_plan['slots'][0]
        slot_binding = run.control_provider_bindings.get(slot['slot_id'])
        if slot_binding is None or EvalRequest(**slot['request']) != EvalRequest(fidelity='dev', split_id='dev') or \
                slot['reservations']['operator'] != {'token': 2 * slot_binding['call_bound']['units']['token'],
                                                     'node': 1, 'eval_count': 0} or \
                slot['reservations']['evaluation'] != {'token': 0, 'node': 0, 'eval_count': 2}:
            raise ValueError('seed control requires the frozen development request and full cascade reserve')
        obligations = [item for item in bridge._preparation['obligations'] if item['slot_id'] == slot['slot_id']]
        quote = bridge.ledger.quote_call(run.provider_sessions[slot['slot_id']].manifest_binding()['max_completion_tokens'])
        if slot_binding['phase_call_limits'] != {'operator': 2, 'evaluation': 0} or obligations != [
                {'slot_id': slot['slot_id'], 'phase': 'operator', 'ordinal': i, 'bound': quote} for i in range(2)]:
            raise ValueError('control requires two frozen protected currency calls')
        frozen = run.physical_plan.get('initial_context', {}).get('circle_domain_binding')
        domain.validate_context()
        if frozen != domain.manifest_binding:
            raise ValueError('main evaluation domain differs from its frozen binding')
        control_path = (Path(run.workdir) / 'host-controls' / slot['slot_id']).resolve()
        main_path = domain.workspace.resolve()
        if control_path == main_path or control_path in main_path.parents or main_path in control_path.parents:
            raise ValueError('main and control workspaces must be independent')
        control_domain = CirclePackingDomain(control_path, runner=SandboxRunner())
        if control_domain.runner is domain.runner or control_domain.manifest_binding != frozen:
            raise ValueError('control evaluator differs from frozen main environment')
        self.budget, self.bridge, self.run, self.ready, self.domain = budget, bridge, run, ready, control_domain
        self._running = False
        self.store, self.plan = budget.store, run.physical_plan
        self.provider = MeteredProvider(_NoProvider())
        self.guard = _ControlGuard(budget)
        self.runtime = SimpleNamespace(budget=budget, store=self.store, _logical_run_id=run.logical_run_id,
            continuation_enabled=True, governed=self.guard, durable_executor=False)
        self.sessions = {slot['slot_id']: {'domain': control_domain} for slot in self.plan['slots']}
        self.invocations = InvocationLifecycle(budget, self.store,
            lambda *args, **kwargs: HierarchicalRuntime._settle_physical(self.runtime, *args, **kwargs),
            governance=self.guard)

    def _audited(self):
        return audit_terminals(self.runtime, self.plan, self.sessions)

    def _adopt_operator(self, slot_id, candidate, seed, started):
        """Resume only a fully evidenced, settled deterministic seed proposal."""
        intent_id = f'control:{slot_id}:operator'
        operations = self.budget._rebuild()[0]['operations']
        operation = operations.get(intent_id)
        if operation is None:
            if any(row['kind'] == 'governed_control_started' for row in self.store.read()):
                raise ValueError('control start lacks its physical reservation')
            return None
        if operation['status'] != 'settled' or operation['intent']['candidate'] != asdict(candidate) or \
                operation['intent']['lane'] != 'control' or operation['intent']['control_slot'] != slot_id or \
                operation['actual_costs'] != {'token': 0, 'node': 1, 'eval_count': 0} or \
                operation['provider_evidence_ref'] != 'sha256:' + payload_digest([]) or \
                invocation_records(self.store).get(intent_id) or \
                self.budget.audit_governance()['slots'][slot_id]['phases']['evaluation'] != 'protected':
            raise ValueError('control operator is not safely recoverable')
        proposal = Proposal(candidate, seed, CostVec(node_count=1), ('token', 'node', 'eval_count'))
        expected_proposal = asdict(proposal)
        expected_proposal['measured_cost_units'] = list(proposal.measured_cost_units)
        rows = list(self.store.read())
        selected = {}
        for index, row in enumerate(rows):
            kind, data = row['kind'], row['payload']
            if kind == 'governed_control_started' and data.get('slot_id') == slot_id:
                key = 'control_start'
            elif kind == 'governed_operator_outcome' and data.get('intent_id') == intent_id:
                key = 'operator_outcome'
            elif kind == 'composed_operation_measurement' and data.get('identity', {}).get('intent_id') == intent_id:
                key = 'measurement'
            elif kind == 'hierarchical_budget' and data.get('event') in {'reserve', 'start', 'settle'}:
                event = data['event']
                identifier = data['data']['intent']['intent_id'] if event == 'reserve' else data['data']['intent_id']
                if identifier != intent_id:
                    continue
                key = event
            else:
                continue
            if key in selected:
                raise ValueError('duplicate control operator recovery evidence')
            selected[key] = (index, data)
        if set(selected) != {'reserve', 'control_start', 'start', 'operator_outcome', 'measurement', 'settle'} or \
                not selected['reserve'][0] < selected['control_start'][0] < selected['start'][0] < \
                    selected['operator_outcome'][0] < selected['measurement'][0] < selected['settle'][0] or \
                selected['control_start'][1] != started:
            raise ValueError('control operator recovery evidence order differs')
        outcome = selected['operator_outcome'][1]
        measurement = selected['measurement'][1]
        identity = {'intent_id': intent_id, 'fingerprint': operation['fingerprint'],
                    'cost': asdict(proposal.cost), 'coverage': list(proposal.measured_cost_units),
                    'evaluation': False, 'operator': True}
        elapsed = measurement.get('elapsed')
        if outcome != {'intent_id': intent_id, 'fingerprint': operation['fingerprint'],
                       'proposal': expected_proposal, 'failure_type': None} or \
                measurement.get('identity') != identity or type(elapsed) not in (int, float) or \
                not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('control operator differs from original measured seed')
        return proposal

    async def execute(self, slot_id):
        with self.budget._lock:
            if self._running:
                raise ValueError('control is already running')
            self._running = True
            try:
                return await self._execute(slot_id)
            finally:
                self._running = False

    async def _execute(self, slot_id):
        existing = self._audited()
        if slot_id in existing:
            terminal = existing[slot_id]
            terminal_ref = 'sha256:' + payload_digest(terminal)
            self.bridge.finish_control(slot_id, terminal_ref)
            if terminal['status'] == 'evaluated':
                self.budget.authorize_initial_control(slot_id, terminal_ref, bridge=self.bridge, run=self.run, domain=self.domain)
            return terminal
        slots = [slot for slot in self.plan['slots'] if slot['slot_id'] == slot_id]
        if len(slots) != 1 or slots[0]['after_main_cycles'] != 0 or self.budget.state()['open_intents']:
            raise ValueError('control requires its frozen first slot and no unresolved operation')
        operations = self.budget._rebuild()[0]['operations']
        if any(operation['intent']['lane'] == 'main' for operation in operations.values()):
            raise ValueError('control must run before all main operations')
        slot = slots[0]
        currency = self.bridge.audit()
        if currency['unknown_cost_calls'] or not currency['protection_valid']:
            raise UsageError('currency protection is not valid for the control')
        seed = _frozen_source(_SEED, _SEED_SHA).decode('utf-8')
        identifier = payload_digest({'run_id': self.run.logical_run_id,
                                     'plan_ref': self.plan['plan_ref'], 'slot_id': slot_id})
        candidate = Candidate(identifier, operator=slot['operator']['name'], created_cycle=0)
        request = OperatorRequest(self.plan['task_desc'], identifier, 0, context=self.plan['initial_context'])
        started = {'slot_id': slot_id, 'plan_ref': self.plan['plan_ref'], 'candidate_id': identifier, 'main_cycles': 0}
        proposal = self._adopt_operator(slot_id, candidate, seed, started)
        if proposal is None:
            receipt = self.budget.reserve_control_operation(slot_id, 'operator', candidate)
            if not receipt.granted:
                raise UsageError('protected control operator reservation was refused')
            self.store.append('governed_control_started', started)
            proposal, failure = await self.invocations.operator(_SeedOperator(candidate, seed), request, candidate, receipt,
                provider=self.provider, lane='control', slot_id=slot_id)
            if failure is not None:
                raise UsageError('deterministic seed control failed')
        evaluation_request = EvalRequest(**slot['request'])
        receipt = self.budget.reserve_control_operation(slot_id, 'evaluation', candidate, request=evaluation_request)
        if not receipt.granted:
            raise UsageError('protected control evaluation reservation was refused')
        expected = binding_for(proposal, evaluation_request, evaluator_version=self.domain.evaluator_version,
                               evaluation_context=self.domain.evaluation_context_for(evaluation_request))
        identity = {'intent_id': receipt.intent_id, 'fingerprint': receipt.fingerprint, 'binding': asdict(expected),
                    'lane': 'control', 'control_slot': slot_id}
        async def invoke():
            return await InProcessExecutor().execute(proposal, evaluation_request, self.domain)
        try:
            evidence = await self.invocations.evaluation(receipt, self.provider, invoke, identity=identity,
                domain=self.domain, lane='control', slot_id=slot_id)
        except MeasuredEvaluationError:
            self.budget.cancel_control_slot(slot_id, reason='evaluation_failed')
            self.budget.invalidate_protection(receipt.intent_id, 'control_evaluation_integrity_failed')
            raise
        try:
            validate_evidence(evidence, expected_binding=expected)
            encoded = encode_evidence(evidence)
        except (ValueError, TypeError):
            self.budget.cancel_control_slot(slot_id, reason='evaluation_failed')
            self.budget.invalidate_protection(receipt.intent_id, 'control_evaluation_integrity_failed')
            raise
        self.store.append('composed_physical_evidence', {'intent_id': receipt.intent_id,
            'request': asdict(evaluation_request), 'evidence': encoded})
        status = 'evaluated' if evidence.eval_result.status is EvalStatus.OK else 'failed'
        if status == 'failed':
            self.budget.cancel_control_slot(slot_id, reason='evaluation_failed')
        self.store.append('governed_control_terminal', {**started, 'status': status, 'proposal': asdict(proposal),
                                                       'evidence': encoded, 'failure_type': None})
        terminal = self._audited()[slot_id]
        terminal_ref = 'sha256:' + payload_digest(terminal)
        self.bridge.finish_control(slot_id, terminal_ref)
        if terminal['status'] == 'evaluated':
            self.budget.authorize_initial_control(slot_id, terminal_ref, bridge=self.bridge, run=self.run, domain=self.domain)
        return terminal
