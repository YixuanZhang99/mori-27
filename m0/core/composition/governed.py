"""Private orchestration of frozen resident controls and measured invocations.

The budget is the sole settlement authority. This service binds isolated
components to that authority and never inserts control outcomes into search.
"""
from __future__ import annotations

import copy
import time
from dataclasses import asdict, replace
from enum import Enum
from contextlib import contextmanager

from core.composition.contracts import BuildContext, OperatorFailure, OperatorRequest, Proposal
from core.composition.evaluation import binding_for, decode_evidence, encode_evidence, validate_evidence
from core.executor.types import Candidate, EvalRequest, EvalStatus
from core.llm import ProviderBudgetExhausted, UsageError
from core.memory.types import ScopeContext
from core.x1.checkpoint import payload_digest


class StopDisposition(str, Enum):
    ORDINARY = "ordinary"
    INTEGRITY = "integrity"


class GovernedInvocation:
    def __init__(self, runtime):
        from core.composition.governance import ControlPlan, validate_factory_governance
        self.runtime = runtime
        self._violations = {}
        binding = getattr(runtime.parts["provider"], "governance_binding", None)
        if not callable(binding):
            raise ValueError("main provider requires a governance binding and hard call bound")
        self.main_binding = validate_factory_governance("provider", binding())
        self.plan = ControlPlan.freeze(runtime.assembly.governance, task_desc=runtime.task,
            initial_context={}, max_generations=runtime.cfg.max_generations,
            units=runtime.budget.units).to_dict()
        self.sessions = {}
        context = BuildContext(None, None, runtime.store,
            ScopeContext(runtime._logical_run_id, payload_digest(runtime.task), runtime.assembly.domain.name),
            runtime.cfg, str(runtime.workdir), runtime.stamp, mode=runtime.assembly.mode,
            governance=runtime.assembly.governance.to_dict())
        for slot in self.plan["slots"]:
            session = runtime.registry.build_control(runtime.assembly, context, slot)
            self.sessions[slot["slot_id"]] = session
            request = EvalRequest(**slot["request"])
            domain = session["domain"]
            validator = getattr(domain, "validate_request", None)
            if not callable(validator):
                raise ValueError("control domain requires explicit request validation")
            validator(copy.deepcopy(request))
            context_for = getattr(domain, "evaluation_context_for", None)
            actual = context_for(request) if callable(context_for) else getattr(domain, "evaluation_context", "")
            if actual != runtime.manifest["evaluation_contexts"].get("dev") or \
                    getattr(domain, "evaluator_version", None) != runtime.manifest["domain_version"]:
                raise ValueError("control domain is not comparable with the frozen main development basis")
            if getattr(session["executor"], "durable_operation_recovery", False):
                session["executor"].validate_domain(domain)
            session["provider"]._governed_store = runtime.store
        runtime.parts["provider"]._governed_store = runtime.store
        if not runtime.cfg.resume_from_checkpoint:
            runtime.budget.protect_controls(self.plan)

    @contextmanager
    def meter(self, provider, receipt, *, lane="main", slot_id=None):
        """Admit every provider ordinal against one physical intent envelope."""
        binding = self.main_binding if lane == "main" else self.sessions[slot_id]["governance_binding"]
        before = provider.usage_total

        def unchanged():
            try:
                return provider.governance_binding() == binding
            except Exception:
                return False

        def guard():
            if not unchanged():
                self._violations[receipt.intent_id] = "provider_governance_binding_changed"
                raise ProviderBudgetExhausted("provider changed its frozen governance binding")
            allowance = receipt.amounts.get("token", 0)
            bound = binding["call_bound"]["units"].get("token", 0)
            if provider.usage_total - before + bound > allowance:
                raise ProviderBudgetExhausted("governed invocation cannot admit another bounded call")

        def measured(used, observed_binding_sha256=...):
            if observed_binding_sha256 is not ... and observed_binding_sha256 != payload_digest(binding):
                self._violations[receipt.intent_id] = "provider_governance_binding_changed"
            if used > binding["call_bound"]["units"].get("token", 0):
                self._violations[receipt.intent_id] = "provider_total_call_bound_exceeded"

        provider.admission_guard = guard
        provider.governance_measurement = measured
        provider.invocation_binding = {"intent_id": receipt.intent_id,
            "fingerprint": receipt.fingerprint, "lane": lane, "slot_id": slot_id,
            "run_id": self.runtime._logical_run_id,
            "adapter_binding_sha256": payload_digest(binding)}
        provider.invocation_ordinal = 0
        try:
            yield
        finally:
            if not unchanged():
                self._violations[receipt.intent_id] = "provider_governance_binding_changed"
            provider.__dict__.pop("admission_guard", None)
            provider.__dict__.pop("governance_measurement", None)
            provider.__dict__.pop("invocation_binding", None)
            provider.__dict__.pop("invocation_ordinal", None)

    def check_integrity(self, receipt):
        reason = self._violations.pop(receipt.intent_id, None)
        if reason is not None:
            self.runtime.budget.invalidate_protection(receipt.intent_id, reason)
            self.runtime.store.append("governed_integrity_failure", {
                "intent_id": receipt.intent_id, "reason": reason})
            raise UsageError("governance binding or provider call bound violated")

    async def operator(self, operator, request, candidate, receipt, *, provider, lane="main", slot_id=None):
        """One shared operator settlement path for main and controls."""
        runtime = self.runtime
        runtime.budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
        before, started, settled, failure = provider.usage_total, time.monotonic(), False, None
        try:
            try:
                with self.meter(provider, receipt, lane=lane, slot_id=slot_id):
                    proposal = await operator.propose(request)
            except OperatorFailure as error:
                failure = error
                proposal = Proposal(candidate, "", error.cost, error.measured_cost_units)
            if not isinstance(proposal, Proposal):
                raise UsageError("operator returned no measurable Proposal")
            runtime._check_provider_floor(receipt, before, proposal.cost, provider=provider)
            # The terminal outcome precedes settlement, so a crash cannot cause
            # an already measured invocation to disappear from its authority.
            runtime.store.append("governed_operator_outcome", {
                "intent_id": receipt.intent_id, "fingerprint": receipt.fingerprint,
                "proposal": asdict(proposal),
                "failure_type": type(failure).__name__ if failure else None})
            runtime._settle_physical(receipt, proposal.cost, proposal.measured_cost_units,
                                    time.monotonic() - started, operator=True)
            settled = True
            self.check_integrity(receipt)
            if "node" in proposal.measured_cost_units and proposal.cost.node_count != 1:
                raise ValueError("operator node measurement differs from the actual candidate attempt")
            return proposal, failure
        except Exception as error:
            if not settled:
                runtime._unresolved_physical(receipt, error)
            raise

    def _terminals(self):
        from core.composition.governance_audit import audit_terminals
        return audit_terminals(self.runtime, self.plan, self.sessions)

    async def due(self, main_cycles, *, drain=False):
        runtime = self.runtime
        for slot in self.plan["slots"]:
            if slot["slot_id"] in self._terminals():
                continue
            if not drain and slot["after_main_cycles"] > main_cycles:
                continue
            if not runtime.budget.audit_governance()["protection_valid"]:
                raise UsageError("governed control protection is no longer valid")
            await self._control(slot, main_cycles)
            runtime._save()

    async def _control(self, slot, main_cycles):
        runtime = self.runtime
        slot_id = slot["slot_id"]
        session = self.sessions[slot_id]
        identifier = payload_digest({"run_id": runtime._logical_run_id,
            "plan_ref": self.plan["plan_ref"], "slot_id": slot_id})
        request = OperatorRequest(runtime.task, identifier, 0,
                                  context=copy.deepcopy(self.plan["initial_context"]))
        candidate = Candidate(identifier, operator=slot["operator"]["name"], created_cycle=0)
        receipt = runtime.budget.reserve_control_operation(slot_id, "operator", candidate)
        if not receipt.granted:
            raise UsageError("protected control operator reservation was refused")
        runtime.store.append("governed_control_started", {"slot_id": slot_id,
            "plan_ref": self.plan["plan_ref"], "candidate_id": identifier, "main_cycles": main_cycles})
        proposal, failure = await self.operator(session["operator"], request, candidate, receipt,
                                                provider=session["provider"], lane="control", slot_id=slot_id)
        if proposal.candidate.id != identifier or proposal.candidate.parents or \
                proposal.candidate.created_cycle != 0 or not isinstance(proposal.artifact, str):
            raise ValueError("control proposal changed frozen identity or parentless lineage")
        if request.context != self.plan["initial_context"]:
            raise ValueError("control operator mutated its frozen initial context")
        if not runtime.budget.audit_governance()["protection_valid"]:
            raise UsageError("control operator exceeded protected capacity")
        evidence = None
        if failure is not None:
            runtime.budget.cancel_control_slot(slot_id, reason=type(failure).__name__)
        else:
            evaluation_request = EvalRequest(**slot["request"])
            receipt = runtime.budget.reserve_control_operation(slot_id, "evaluation", candidate,
                                                               request=evaluation_request)
            if not receipt.granted:
                raise UsageError("protected control evaluation reservation was refused")
            evidence = await runtime._evaluate_physical(proposal, evaluation_request, receipt,
                                                       parts=session, lane="control", control_slot=slot_id)
        status = "evaluated" if evidence is not None and evidence.eval_result.status is EvalStatus.OK else "failed"
        if evidence is not None and status == "failed":
            runtime.budget.cancel_control_slot(slot_id, reason="evaluation_failed")
        runtime.store.append("governed_control_terminal", {"slot_id": slot_id,
            "plan_ref": self.plan["plan_ref"], "candidate_id": identifier,
            "main_cycles": main_cycles, "status": status,
            "proposal": asdict(proposal), "evidence": encode_evidence(evidence) if evidence else None,
            "failure_type": type(failure).__name__ if failure else None})

    def audit(self):
        from core.x1.store import AppendOnlyStore
        store = self.runtime.store
        # ContinuationStore intentionally exposes a checkpoint prefix while
        # restoring. Outside recovery, inspection must detect disk changes too.
        if not store.restoring and store.peek() is None and list(AppendOnlyStore(store.path).read()) != store.rows:
            raise ValueError("governed authoritative journal changed outside its coordinator")
        from core.composition.provider_evidence import audit_provider_receipts
        audit_provider_receipts(self.runtime, self.sessions, self.main_binding)
        terminals = self._terminals()
        budget = self.runtime.budget.audit_governance()
        started = {r["payload"]["slot_id"] for r in self.runtime.store.read("governed_control_started")}
        planned = len(self.plan["slots"])
        completed = sum(t["status"] == "evaluated" for t in terminals.values())
        failed = len(terminals) - completed
        unresolved = len(started - terminals.keys())
        return {"schema_version": 1, "plan_ref": self.plan["plan_ref"],
            "planned": planned, "completed": completed, "failed": failed,
            "pending": planned - len(started), "unresolved": unresolved,
            "budget": budget,
            "violations": [r["payload"] for r in store.read("governed_integrity_failure")],
            "resident_complete": len(terminals) == planned and not unresolved,
            "input_isolation": "registered_fresh_sessions_and_restricted_store_views",
            "sampling": {key: value["governance_binding"] for key, value in self.sessions.items()},
            "iid_statistically_verified": False, "superiority_established": False,
            "external_currency_protected": False,
            "formal_release_certified": False}
