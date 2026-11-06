"""Private orchestration of frozen resident controls and measured invocations.

The budget is the sole settlement authority. This service binds isolated
components to that authority and never inserts control outcomes into search.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, replace
from enum import Enum
from contextlib import contextmanager

from core.composition.contracts import BuildContext, OperatorRequest
from core.composition.evaluation import encode_evidence
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
        self.external = None
        self.external_plan = None
        binding = getattr(runtime.parts["provider"], "governance_binding", None)
        if not callable(binding):
            raise ValueError("main provider requires a governance binding and hard call bound")
        self.main_binding = validate_factory_governance("provider", binding(),
            external_bridges=runtime.registry.external_bridge_names)
        expected_external = runtime.external_bridge_name
        actual_external = self.main_binding.get("external_currency")
        if (actual_external.get("bridge") if isinstance(actual_external, dict) else None) != expected_external:
            raise ValueError("main and control providers require the same external authority capability")
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
            if runtime.construction_enabled:
                from core.composition.configured_execution import ConfiguredExecution
                session["construction_execution"] = ConfiguredExecution(runtime.assembly.execution,
                    session, runtime.store, getattr(runtime, "_recorded_artifacts_root", runtime.workdir),
                    lane="control", slot_id=slot["slot_id"])
        runtime.parts["provider"]._governed_store = runtime.store
        if not runtime.cfg.resume_from_checkpoint:
            runtime.budget.protect_controls(self.plan)

        if expected_external is not None:
            from core.composition.external_provider import ExternalRunContext, ExternalConstructionRunContext
            self.external = runtime.registry.external_bridge(expected_external)
            recorded = getattr(runtime, "_recorded_external_bundle", None)
            context_type, extra = ExternalRunContext, {}
            if runtime.construction_enabled:
                context_type = ExternalConstructionRunContext
                manifest = {**runtime.manifest, "governance": self.plan,
                            "governance_provider": self.main_binding}
                extra["construction"] = {"schema_version": 1, "envelope": "candidate_production_v1",
                    "manifest_sha256": payload_digest(manifest),
                    "execution": runtime.assembly.execution.to_dict(),
                    "main": runtime.construction.manifest_binding,
                    "roles": {key: {name: asdict(role) for name, role in parts["constructor"].roles.items()}
                              for key, parts in {"main": runtime.parts, **self.sessions}.items()},
                    "controls": {key: value["construction_execution"].manifest_binding
                                 for key, value in self.sessions.items()}}
            context = context_type(**extra, logical_run_id=runtime._logical_run_id,
                runtime_id=runtime.runtime_identity, workdir=str(runtime.workdir.resolve()),
                physical_plan=self.plan, main_provider_binding=self.main_binding,
                control_provider_bindings={key: value["governance_binding"] for key, value in self.sessions.items()},
                mode="recorded" if recorded is not None else "live", recorded_bundle=recorded,
                store=runtime.store, physical_identity_lookup=runtime.budget.invocation_identity,
                provider_sessions={"main": runtime.parts["provider"].raw_provider,
                    **{key: value["provider"].raw_provider for key, value in self.sessions.items()}})
            self.external_plan = self.external.bind_run(context)
            cell_clock = getattr(self.external, 'cell_deadline', None)
            check_clock = getattr(self.external, '_check_cell_deadline', None)
            if callable(cell_clock) and callable(check_clock):
                deadline = cell_clock()
                if deadline is not None:
                    runtime.budget.install_admission_guard(check_clock)
                    record_evaluation = getattr(self.external, 'record_evaluation_eligibility', None)
                    if callable(record_evaluation):
                        runtime.budget.install_evaluation_eligibility_recorder(record_evaluation)
                    record_cycle = getattr(self.external, 'record_cycle_eligibility', None)
                    if callable(record_cycle):
                        runtime.budget.install_cycle_eligibility_recorder(record_cycle)
                    for domain in [runtime.parts['domain'], *(session['domain'] for session in self.sessions.values())]:
                        bind_deadline = getattr(domain, 'bind_cell_deadline', None)
                        if not callable(bind_deadline):
                            raise ValueError('timed governance requires a deadline-aware domain')
                        bind_deadline(deadline)

    def _external_context(self, receipt, binding, lane, slot_id, ordinal, args, kwargs):
        from core.composition.external_provider import GovernedCallContext, external_session_id
        identity = self.runtime.budget.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
        if identity["lane"] != lane or identity["slot_id"] != slot_id:
            raise ValueError("external call lane differs from physical authority")
        authority = self.external_plan.authority_binding
        return GovernedCallContext(schema_version=1, runtime_id=self.runtime.runtime_identity,
            logical_run_id=self.runtime._logical_run_id, currency_run_id=authority["currency_run_id"],
            campaign_id=authority["campaign_id"], policy_sha256=authority["policy_sha256"],
            physical_plan_ref=self.plan["plan_ref"], bridge_plan_ref=self.external_plan.bridge_plan_ref,
            lane=lane, slot_id=slot_id, candidate_id=identity["candidate_id"], intent_id=receipt.intent_id,
            physical_fingerprint=receipt.fingerprint, account=identity["account"],
            operation=identity["operation"], phase=identity["phase"], ordinal=ordinal,
            adapter_binding_sha256=payload_digest(binding),
            session_id=external_session_id(self.runtime._logical_run_id, lane, slot_id, payload_digest(binding)),
            argument_sha256=payload_digest({"args": args, "kwargs": kwargs}))


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
            if self.external is not None:
                from core.composition.external_provider import validate_external_ordinal
                current = provider.__dict__.get("current_external_context")
                if current is None:
                    raise UsageError("external invocation has no trusted call context")
                if current.phase != "planning" or "planning" in binding["phase_call_limits"]:
                    try:
                        validate_external_ordinal(binding, current.phase, current.ordinal)
                    except ValueError:
                        raise ProviderBudgetExhausted("external invocation exhausted its frozen ordinal allowance") from None
            allowance = receipt.amounts.get("token", 0)
            bound = binding["call_bound"]["units"].get("token", 0)
            if self.external is not None and provider.current_external_context.ordinal >= allowance // bound:
                raise ProviderBudgetExhausted("external invocation exhausted its frozen physical call-count allowance")
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
        if self.external is not None:
            provider.external_context_factory = lambda ordinal, args, kwargs: self._external_context(
                receipt, binding, lane, slot_id, ordinal, args, kwargs)
            provider.external_invoke = self.external.invoke
            provider.external_recover = self.external.recover
            accounting = getattr(self.external, '_recover_for_accounting', None)
            deadline = getattr(self.external, '_check_cell_deadline', None)
            if callable(accounting) and callable(deadline):
                provider.external_accounting_recover = accounting
                provider.external_deadline_check = deadline
        try:
            yield
        finally:
            if not unchanged():
                self._violations[receipt.intent_id] = "provider_governance_binding_changed"
            provider.__dict__.pop("admission_guard", None)
            provider.__dict__.pop("governance_measurement", None)
            provider.__dict__.pop("invocation_binding", None)
            provider.__dict__.pop("invocation_ordinal", None)
            for name in ("external_context_factory", "external_invoke", "external_recover",
                         "external_accounting_recover", "external_deadline_check"):
                provider.__dict__.pop(name, None)

    def check_integrity(self, receipt):
        reason = self._violations.pop(receipt.intent_id, None)
        if self.external is not None:
            store = self.runtime.store
            pending = callable(getattr(store, "peek", None)) and store.peek() is not None
            prefix_audit = getattr(self.external, "_audit_replay_prefix", None)
            if (getattr(store, "restoring", False) or pending) and callable(prefix_audit):
                audit = prefix_audit()
            else:
                audit = self.external.audit()
            if not audit["protection_valid"]:
                reason = reason or "external_currency_protection_breached"
        if reason is not None:
            self.runtime.budget.invalidate_protection(receipt.intent_id, reason)
            self.runtime.store.append("governed_integrity_failure", {
                "intent_id": receipt.intent_id, "reason": reason})
            raise UsageError("governance binding or provider call bound violated")

    def _terminals(self):
        from core.composition.governance_audit import audit_terminals
        return audit_terminals(self.runtime, self.plan, self.sessions)

    async def due(self, main_cycles, *, drain=False):
        runtime = self.runtime
        for slot in self.plan["slots"]:
            terminals = self._terminals()
            if slot["slot_id"] in terminals:
                if self.external is not None:
                    self.external.finish_control(slot["slot_id"], "sha256:" + payload_digest(terminals[slot["slot_id"]]))
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
        source_context = None
        if runtime.construction_enabled:
            source_context = session["construction_execution"].control_context(runtime.task)
            candidate = replace(candidate, context_pack_ref=source_context["context_pack_ref"])
            control_context = session["construction_execution"].project(source_context)
            if runtime.funsearch:
                control_context['instruction'] = ('The JSON artifact field must contain exactly one Python function with the target name and '
                    'signature in this frozen template. The artifact must not contain other top-level statements.\n' +
                    runtime.assembly.policy.options['template'])
            frozen_control_context = copy.deepcopy(control_context)
            request = replace(request, context=control_context)
        receipt = runtime.budget.reserve_control_operation(slot_id, "operator", candidate)
        if not receipt.granted:
            raise UsageError("protected control operator reservation was refused")
        runtime.store.append("governed_control_started", {"slot_id": slot_id,
            "plan_ref": self.plan["plan_ref"], "candidate_id": identifier, "main_cycles": main_cycles})
        operator = runtime._production_operator(session["operator"], slot["operator"]["name"],
            source_context, receipt, parts=session, lane="control", slot_id=slot_id, cycle=0)
        proposal, failure = await runtime.invocations.operator(operator, request, candidate, receipt,
                                                provider=session["provider"], lane="control", slot_id=slot_id)
        if proposal.candidate.id != identifier or proposal.candidate.parents or \
                proposal.candidate.created_cycle != 0 or not isinstance(proposal.artifact, str):
            raise ValueError("control proposal changed frozen identity or parentless lineage")
        expected_context = frozen_control_context if runtime.construction_enabled \
            else self.plan["initial_context"]
        if request.context != expected_context:
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
        if self.external is not None:
            self.external.finish_control(slot_id, "sha256:" + payload_digest(self._terminals()[slot_id]))

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
        external_audit = self.external.audit() if self.external is not None else None
        return {"schema_version": 1, "plan_ref": self.plan["plan_ref"],
            "planned": planned, "completed": completed, "failed": failed,
            "pending": planned - len(started), "unresolved": unresolved,
            "budget": budget,
            "violations": [r["payload"] for r in store.read("governed_integrity_failure")],
            "resident_complete": len(terminals) == planned and not unresolved,
            "input_isolation": "registered_fresh_sessions_and_restricted_store_views",
            "sampling": {key: value["governance_binding"] for key, value in self.sessions.items()},
            "iid_statistically_verified": False, "superiority_established": False,
            "external_currency_protected": bool(external_audit and external_audit["protection_valid"]),
            **({"external_currency": external_audit} if external_audit is not None else {}),
            "formal_release_certified": False}
