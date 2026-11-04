"""Runtime bridge for physical budgets, exact requests and paid held-out calls.

The controller owns atomic accounting. This bridge owns call boundaries: every
call is reserved first, known usage is settled before validating its identity,
and unknown usage retains its reservation. It never converts physical units.
"""
from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import asdict, replace

from core.composition.contracts import Decision, Proposal
from core.composition.invocation import _physical, check_provider_floor
from core.composition.proxy_runtime import ProxyRuntime
from core.composition.evaluation import (EvaluationContract, comparison_projection,
    encode_evidence, measured_costs, public_projection, validate_evidence)
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.llm import ProviderBudgetExhausted, UsageError
from core.policy.types import MutationOp, StateMutation
from core.x1.checkpoint import payload_digest


def _identity(*values):
    return hashlib.sha256("\0".join(map(str, values)).encode()).hexdigest()




class HierarchicalRuntime(ProxyRuntime):
    def _preflight_hierarchical(self):
        from core.composition.knowledge import LocalKnowledge
        if self.parts.get("knowledge") is not None and type(self.parts["knowledge"]) is not LocalKnowledge:
            raise ValueError("hierarchical runtime requires the explicitly metered local knowledge adapter")
        for rung in self.budget.options["fidelity_rungs"]:
            self._validate_domain(EvalRequest(**rung))
        extra = set(self.budget.units) - {"token", "eval_count", "node", "wallclock"}
        for component in (*self.parts["operators"], self.parts["domain"]):
            if not extra.issubset(getattr(component, "measured_cost_units", ())):
                raise ValueError("component does not declare the configured physical cost coverage")
        if extra:
            # No currency/GPU meter exists for arbitrary policy or skill hooks.
            # These built-ins are pure local work, with a provable zero charge.
            from core.composition.strategies import GreedyPolicy
            from core.composition.population import PopulationPolicy
            from core.composition.defaults import InstructionSkill
            if type(self.parts["policy"]) not in {GreedyPolicy, PopulationPolicy} or any(
                    type(skill) is not InstructionSkill for skill in self.parts["skills"]):
                raise ValueError("policy/skill physical coverage requires a supported local adapter")
        convergence = self.budget.options.get("convergence")
        if convergence and (convergence.get("metric", "dev/score") != self.frontier.metric
                or convergence.get("direction", "maximize") != self.frontier.direction):
            raise ValueError("budget convergence objective differs from exploration")

    def _candidate_scope(self, candidate):
        def lineage(identifier, visiting):
            if identifier in visiting:
                raise ValueError("candidate skeleton contains a cycle")
            ancestor = self.proposals.get(identifier)
            if ancestor is None:
                raise ValueError("candidate skeleton parent is missing")
            parents = ancestor.candidate.parents
            if not parents:
                return identifier, 0
            branches = [lineage(parent, visiting | {identifier}) for parent in parents]
            return branches[0][0], 1 + max(depth for _, depth in branches)
        if not candidate.parents:
            return candidate.id, 0
        branches = [lineage(parent, {candidate.id}) for parent in candidate.parents]
        return branches[0][0], 1 + max(depth for _, depth in branches)

    def _reserve_physical(self, candidate, operation, tag, *, request=None, direction=None, depth=None):
        if direction is None:
            direction, depth = self._candidate_scope(candidate)
        return self.budget.reserve_operation(
            _identity(self._logical_run_id, candidate.id, operation, tag), candidate,
            direction, operation, request=request, depth=depth)

    def _settle_physical(self, receipt, cost, coverage, elapsed, *, evaluation=False, operator=False):
        if getattr(self, "continuation_enabled", False):
            if not evaluation and "wallclock" in self.budget.units \
                    and receipt.intent_id in self.store.replayed_starts and self.store.peek() is None:
                raise UsageError("interrupted local operation has no durable wall-time measurement")
            elapsed = self.store.measurement({"intent_id": receipt.intent_id,
                "fingerprint": receipt.fingerprint, "cost": asdict(cost),
                "coverage": list(coverage), "evaluation": evaluation, "operator": operator}, elapsed)
        values = _physical(cost)
        if type(coverage) not in (tuple, list) or any(type(unit) is not str for unit in coverage):
            raise UsageError("physical usage coverage is missing")
        covered = set(coverage)
        if evaluation:
            # Evaluation does not materialize a new search node.
            if values["node"] != 0:
                raise UsageError("evaluation cannot claim candidate materialization cost")
            covered.add("node")
            # A native batch may report more than one experiment, but an actual
            # domain invocation cannot consume fewer than one evaluation.
            values["eval_count"] = max(1, values["eval_count"])
            if getattr(self, "durable_executor", False):
                # The supervisor measures the actual process lifetime. A
                # producer's zero/shorter wall meter cannot make it free.
                values["wallclock"] = max(values["wallclock"], elapsed)
                covered.add("wallclock")
        if operator:
            # The driver knows that this invocation attempted exactly one
            # candidate. An omitted node meter cannot turn that attempt free.
            values["node"] = 1
            covered.add("node")
        if any(value != 0 and unit not in covered for unit, value in values.items()):
            raise UsageError("nonzero physical cost lacks measurement coverage")
        if "wallclock" not in covered:
            values["wallclock"] = elapsed
            covered.add("wallclock")
        if not set(self.budget.units).issubset(covered):
            raise UsageError("operation does not measure every configured physical unit")
        proof = {}
        if getattr(self, "governed", None):
            from core.composition.provider_evidence import evidence_reference
            proof["provider_evidence_ref"] = evidence_reference(self.store, receipt.intent_id)
        self.budget.settle_operation(receipt.intent_id,
            {unit: values[unit] for unit in self.budget.units},
            measured_units=tuple(covered), fingerprint=receipt.fingerprint, **proof)

    def _check_provider_floor(self, receipt, before, cost, *, provider=None):
        check_provider_floor(self.store, receipt, provider or self.parts["provider"], before, cost)

    def _halt_physical(self, cycle, reason, *, started=False):
        self._halted_reason = reason
        if getattr(self, "governed", None):
            from core.composition.governed import StopDisposition
            self._stop_disposition = (StopDisposition.ORDINARY if self.budget.audit_governance()["protection_valid"]
                                      else StopDisposition.INTEGRITY)
        self.store.append("composed_cycle_aborted" if started else "composed_stopped",
                          {"cycle": cycle, "reason": reason})
        if getattr(self, "governed", None):
            self.store.append("governed_main_stopped", {"main_cycles": self.next_cycle,
                "disposition": self._stop_disposition.value})
        self._save()
        return False

    async def _evaluate_physical(self, proposal, request, receipt, *, parts=None, lane="main", control_slot=None):
        parts = self.parts if parts is None else parts
        domain = parts["domain"]
        if lane == "main":
            self._validate_domain(request)
            expected = self._binding(proposal, request)
        else:
            from core.composition.evaluation import binding_for
            domain.validate_request(copy.deepcopy(request))
            context_for = getattr(domain, "evaluation_context_for", None)
            expected = binding_for(proposal, request, evaluator_version=domain.evaluator_version,
                evaluation_context=context_for(request) if callable(context_for) else domain.evaluation_context)
        operation = None
        if self.construction_enabled:
            operation = self._execution_operation(receipt, request.split_id, lane=lane, slot_id=control_slot,
                                                 cycle=0 if lane == "control" else None)
        elif self.durable_executor:
            operation = {"run_id": self._logical_run_id,
                "cycle": getattr(self, "_active_cycle", 0), "phase": request.split_id,
                "intent_id": receipt.intent_id, "fingerprint": receipt.fingerprint,
                "manifest_sha256": "sha256:" + payload_digest(self.manifest)}

        async def invoke():
            if self.construction_enabled:
                return await parts["construction_execution"].evaluate(proposal, request, operation)
            if operation is not None:
                return await parts["executor"].execute_bound(
                    copy.deepcopy(proposal), copy.deepcopy(request), domain, operation)
            return await parts["executor"].execute(
                copy.deepcopy(proposal), copy.deepcopy(request), domain)

        identity = {"intent_id": receipt.intent_id, "fingerprint": receipt.fingerprint,
            "binding": asdict(expected), "lane": lane, "control_slot": control_slot}
        measurement_owner = parts["construction_execution"].owner if self.construction_enabled else parts["executor"]
        elapsed = (lambda: measurement_owner.operation_metadata(operation)["wall_seconds"]) \
            if operation is not None else None
        evidence = await self.invocations.evaluation(receipt, parts["provider"], invoke,
            identity=identity, domain=domain, elapsed=elapsed, lane=lane, slot_id=control_slot,
            outcome_owner="executor" if self.construction_enabled else "lifecycle")
        if lane == "main":
            self._validate_domain(request)
        validate_evidence(evidence, expected_binding=expected)
        self.store.append("composed_physical_evidence", {"intent_id": receipt.intent_id,
            "request": asdict(request), "evidence": encode_evidence(evidence)})
        return evidence

    async def _execute_hierarchical_calls(self, calls):
        reserved = []
        for call in calls:
            self._validate_domain(call.request)
            receipt = self._reserve_physical(call.proposal.candidate,
                "final" if call.request.split_id == "final_audit" else "admission",
                call.key, request=call.request)
            if not receipt.granted:
                for _, previous in reserved:
                    self.budget.release_operation(previous.intent_id, fingerprint=previous.fingerprint)
                self.store.append("layered_budget_rejected", {"phase": call.phase, "reason": receipt.reason})
                return False
            reserved.append((call, receipt))
        for index, (call, receipt) in enumerate(reserved):
            started = recorded = False
            try:
                self.budget.pre_call_check()
                self.layered.before_call(call)
                started = True
                evidence = await self._evaluate_physical(call.proposal, call.request, receipt)
                self.layered.record(call, evidence)
                recorded = True
                self.store.append("layered_evidence", {"key": call.key, "phase": call.phase,
                                                        "evidence": encode_evidence(evidence)})
            except Exception as error:
                for _, remaining in reserved[index + 1:]:
                    self.budget.release_operation(remaining.intent_id, fingerprint=remaining.fingerprint)
                if not started:
                    self.budget.release_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
                elif not recorded:
                    self.layered.mark_failed(call, type(error).__name__)
                raise
        return True

    async def _cycle_hierarchical(self, task, cycle):
        from core.composition.contracts import OperatorBudgetExhausted
        signal = self.budget.converged(self.frontier)
        if signal:
            return self._halt_physical(cycle, signal.rule + ": " + signal.reason)
        identifier = _identity(self.assembly.name, task, cycle)
        provisional = Candidate(identifier, created_cycle=cycle)
        planning = self._reserve_physical(provisional, "planning", cycle, direction="coordination", depth=0)
        if not planning.granted:
            return self._halt_physical(cycle, planning.reason)
        self.store.append("composed_cycle_started", {"cycle": cycle, "intent": planning.intent_id})
        self._policy_tokens, self._known_cost = 0, 0
        try:
            operator, selected, parents, context, request = await self.invocations.planning(planning, self.parts["provider"],
                lambda: self._prepare_cycle(task, cycle, identifier))
        except ProviderBudgetExhausted as error:
            if not getattr(self, "governed", None):
                raise
            return self._halt_physical(cycle, str(error), started=True)
        candidate = Candidate(identifier, parents, operator=selected, created_cycle=cycle,
                              context_pack_ref=context["context_pack_ref"])
        direction, depth = self._candidate_scope(candidate)
        if not self.budget.should_continue(direction):
            return self._halt_physical(cycle, "selected direction cannot continue", started=True)
        evaluation_request = self.budget.allocate(candidate, direction_id=direction, depth=depth)
        operation = self._reserve_physical(candidate, "operator", cycle)
        if not operation.granted:
            return self._halt_physical(cycle, operation.reason, started=True)
        request = replace(request, context={**request.context, "budget": {
            "state": self.budget.main_state() if self.governed else self.budget.state(), "allocated_request": asdict(evaluation_request),
            "direction_id": direction, "depth": depth}})
        operator = self._production_operator(operator, selected, context, operation, cycle=cycle)
        proposal, failure = await self.invocations.operator(operator, request, candidate, operation,
            provider=self.parts["provider"], stop_at_token_reserve=self.construction_enabled)
        producer_context = self.construction.project(context) if self.construction_enabled else context
        if request.context.get("retrieval") != producer_context["retrieval"] or \
                request.context.get("context_pack_ref") != context["context_pack_ref"]:
            raise ValueError("operator changed authoritative retrieval context")
        if proposal.candidate.id != identifier or proposal.candidate.parents != parents \
                or not isinstance(proposal.artifact, str):
            raise ValueError("operator proposal changed identity or lineage")
        proposal.candidate.validate()
        if proposal.candidate.context_pack_ref != context["context_pack_ref"]:
            raise ValueError("operator dropped or changed retrieval context identity")
        if isinstance(failure, OperatorBudgetExhausted):
            return self._halt_physical(cycle, str(failure), started=True)
        if self.layered:
            self.layered.check_integrity(proposal, self._source_refs(context))
        if self.parts.get("knowledge") is not None:
            audit = self.parts["knowledge"].audit(identifier, proposal.artifact)
            if any(_physical(audit.cost).values()):
                raise UsageError("configured local audit returned an unsupported paid charge")
            self.store.append("composed_knowledge_audit", {"candidate_id": identifier, "audit": audit.to_dict()})
        if failure:
            evidence = EvidenceRecord(identifier, EvalResult(EvalStatus.FAILED_TO_RUN,
                cost=CostVec(), fidelity=evaluation_request.fidelity, text_feedback=str(failure),
                contract=EvaluationContract(self._binding(proposal, evaluation_request),
                    ("token", "eval_count"), binding_source="invocation")),
                executor_status="failed_to_run", result_text=str(failure))
        else:
            evaluation = self._reserve_physical(candidate, "dev", cycle, request=evaluation_request)
            if not evaluation.granted:
                return self._halt_physical(cycle, evaluation.reason, started=True)
            evidence = await self._evaluate_physical(proposal, evaluation_request, evaluation)
        # A changed request must compare against an actually re-evaluated
        # incumbent. Old receipts remain durable; only current dev views move.
        if self.incumbent and self.eval_requests[self.incumbent] != evaluation_request:
            incumbent = self.proposals[self.incumbent]
            baseline = self._reserve_physical(incumbent.candidate, "dev_baseline", cycle,
                                              request=evaluation_request)
            if not baseline.granted:
                return self._halt_physical(cycle, baseline.reason, started=True)
            previous = self.evidence[self.incumbent]
            refreshed = await self._evaluate_physical(incumbent, evaluation_request, baseline)
            refreshed = replace(refreshed, attempt=previous.attempt + 1)
            if refreshed.eval_result.status is not EvalStatus.OK:
                raise ValueError("incumbent development baseline did not succeed")
            self.store.append("composed_dev_baseline", {"cycle": cycle, "previous": encode_evidence(previous),
                "evidence": encode_evidence(refreshed), "request": asdict(evaluation_request)})
            if self.layered:
                self.layered.advance_development_basis(refreshed)
            self.evidence[self.incumbent], self.eval_requests[self.incumbent] = refreshed, evaluation_request
            node = self.frontier.nodes[self.incumbent]
            refreshed_ref = "sha256:" + payload_digest({"logical_run_id": self._logical_run_id,
                                                        "evidence": encode_evidence(refreshed)})
            result = {**(node.result or {}), "metrics": dict(refreshed.eval_result.metrics),
                      "text_feedback": refreshed.eval_result.text_feedback,
                      "result_text": refreshed.result_text, "evidence_ref": refreshed_ref}
            self.applier.apply(StateMutation(MutationOp.UPDATE_NODE, self.incumbent,
                {"score": refreshed.eval_result.metrics[self.frontier.metric],
                 "score_split": dict(refreshed.eval_result.metrics), "attempt": refreshed.attempt,
                 "cost": asdict(refreshed.eval_result.cost), "uncertainty": refreshed.eval_result.uncertainty,
                 "result": result}, "refresh incumbent from actual comparable dev baseline"))
        continued, proxy_rejection, proxy_mutations = await self._calibrate_candidates(proposal, evidence, cycle)
        if not continued:
            return False
        absorb = self._reserve_physical(candidate, "planning", "absorb:" + str(cycle),
                                       direction="coordination", depth=depth)
        if not absorb.granted:
            return self._halt_physical(cycle, absorb.reason, started=True)
        mutations = await self.invocations.planning(absorb, self.parts["provider"],
            lambda: self._policy("absorb", public_projection(evidence)))
        self._validate_mutations(mutations, evidence)
        evidence_ref = "sha256:" + payload_digest({"logical_run_id": self._logical_run_id,
                                                   "evidence": encode_evidence(evidence)})
        mutations = self.memory.prepare_mutations(mutations, public_projection(evidence),
                                                 evidence_ref, cycle=cycle)
        mutations.extend(proxy_mutations)
        if self.layered:
            decision = await self._admit_layered(proposal, evidence, context, rejection_reason=proxy_rejection)
        elif proxy_rejection:
            decision = Decision(False, proxy_rejection)
        else:
            decision = self.parts["admission"].judge(comparison_projection(evidence),
                comparison_projection(self.evidence[self.incumbent]) if self.incumbent else None)
        if not isinstance(decision, Decision):
            raise ValueError("admission must return a Decision")
        if decision.admit and evidence.eval_result.status is not EvalStatus.OK:
            raise ValueError("failed execution cannot be admitted")
        self.budget.should_continue(direction, public_projection(evidence))
        return self._commit_cycle(cycle, proposal, evidence, decision, mutations, context,
                                  evidence_ref, evaluation_request)
