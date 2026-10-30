"""Runtime bridge for physical budgets, exact requests and paid held-out calls.

The controller owns atomic accounting. This bridge owns call boundaries: every
call is reserved first, known usage is settled before validating its identity,
and unknown usage retains its reservation. It never converts physical units.
"""
from __future__ import annotations

import copy
import hashlib
import math
import time
from dataclasses import asdict, replace

from core.composition.contracts import Decision, Proposal
from core.composition.proxy_runtime import ProxyRuntime
from core.composition.evaluation import (EvaluationContract, comparison_projection,
    encode_evidence, measured_costs, public_projection, validate_evidence)
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.llm import UsageError
from core.policy.types import MutationOp, StateMutation
from core.x1.checkpoint import payload_digest


def _identity(*values):
    return hashlib.sha256("\0".join(map(str, values)).encode()).hexdigest()


def _physical(cost):
    if not isinstance(cost, CostVec):
        raise UsageError("operation must return explicit physical costs")
    for name, value in asdict(cost).items():
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise UsageError("physical costs must be finite and nonnegative")
        if name in {"tokens_in", "tokens_out", "eval_count", "node_count"} and type(value) is not int:
            raise UsageError("physical token and count costs must be integers")
    return {"token": cost.tokens_in + cost.tokens_out, "eval_count": cost.eval_count,
            "node": cost.node_count, "wallclock": cost.wall_seconds,
            "gpu_hours": cost.gpu_hours, "usd": cost.usd}


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
            from core.composition.defaults import InstructionSkill
            if type(self.parts["policy"]) is not GreedyPolicy or any(
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
        if getattr(self, "durable_executor", False):
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
        self.budget.settle_operation(receipt.intent_id,
            {unit: values[unit] for unit in self.budget.units},
            measured_units=tuple(covered), fingerprint=receipt.fingerprint)

    def _unresolved_physical(self, receipt, error):
        self.budget.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint,
                                    reason=type(error).__name__ + ": " + str(error))

    def _check_provider_floor(self, receipt, before, cost):
        observed = self.parts["provider"].usage_total - before
        reported = _physical(cost)["token"]
        if reported < observed:
            self.store.append("composed_usage_discrepancy", {"intent_id": receipt.intent_id,
                "provider_tokens": observed, "reported_tokens": reported})
            raise UsageError("reported token cost is below observed provider usage")

    def _halt_physical(self, cycle, reason, *, started=False):
        self._halted_reason = reason
        self.store.append("composed_cycle_aborted" if started else "composed_stopped",
                          {"cycle": cycle, "reason": reason})
        self._save()
        return False

    async def _planning_physical(self, receipt, function):
        self.budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
        before, started = self.parts["provider"].usage_total, time.monotonic()
        def settle():
            try:
                tokens = self.parts["provider"].usage_total - before
                # GPU/USD zeros are authorized only for the pure local hooks
                # admitted by preflight; tokens have their own provider meter.
                coverage = ("token", "eval_count", "node", "gpu_hours", "usd")
                if tokens and set(self.budget.units) & {"gpu_hours", "usd"}:
                    raise UsageError("paid planning has no GPU/currency meter")
                self._settle_physical(receipt, CostVec(tokens_in=tokens), coverage,
                                      time.monotonic() - started)
            except Exception as error:
                self._unresolved_physical(receipt, error)
                raise
        try:
            result = await function()
        except UsageError as error:
            self._unresolved_physical(receipt, error)
            raise
        except Exception:
            settle()
            raise
        settle()
        return result

    async def _evaluate_physical(self, proposal, request, receipt):
        self._validate_domain(request)
        expected = self._binding(proposal, request)
        self.budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
        started, settled = time.monotonic(), False
        before = self.parts["provider"].usage_total
        try:
            elapsed = None
            if getattr(self, "durable_executor", False):
                from core.composition.worktree import MeasuredCommandError
                operation = {"run_id": self._logical_run_id, "cycle": self._active_cycle,
                    "phase": request.split_id, "intent_id": receipt.intent_id,
                    "fingerprint": receipt.fingerprint,
                    "manifest_sha256": "sha256:" + payload_digest(self.manifest)}
                try:
                    evidence = await self.parts["executor"].execute_bound(
                        copy.deepcopy(proposal), copy.deepcopy(request), self.parts["domain"], operation)
                except MeasuredCommandError as error:
                    self._check_provider_floor(receipt, before, error.cost)
                    self._settle_physical(receipt, error.cost, error.measured_cost_units,
                                          error.wall_seconds, evaluation=True)
                    settled = True
                    raise
                elapsed = self.parts["executor"].operation_metadata(operation)["wall_seconds"]
            else:
                evidence = await self.parts["executor"].execute(
                    copy.deepcopy(proposal), copy.deepcopy(request), self.parts["domain"])
            if not isinstance(evidence, EvidenceRecord):
                raise UsageError("executor returned no measurable canonical evidence")
            self._check_provider_floor(receipt, before, evidence.eval_result.cost)
            measured_costs(evidence.eval_result)
            self._settle_physical(receipt, evidence.eval_result.cost,
                evidence.eval_result.contract.measured_cost_units,
                elapsed if elapsed is not None else time.monotonic() - started,
                evaluation=True)
            settled = True
            if evidence.eval_result.cost.eval_count < 1:
                raise ValueError("evaluation count is below the actual domain invocation")
            self._validate_domain(request)
            validate_evidence(evidence, expected_binding=expected)
            self.store.append("composed_physical_evidence", {"intent_id": receipt.intent_id,
                "request": asdict(request), "evidence": encode_evidence(evidence)})
            return evidence
        except Exception as error:
            if not settled:
                self._unresolved_physical(receipt, error)
            raise

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
        from core.composition.defaults import OperatorFailure
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
        operator, selected, parents, context, request = await self._planning_physical(planning,
            lambda: self._prepare_cycle(task, cycle, identifier))
        candidate = Candidate(identifier, parents, operator=selected, created_cycle=cycle,
                              context_pack_ref=context["context_pack_ref"])
        direction, depth = self._candidate_scope(candidate)
        if not self.budget.should_continue(direction):
            return self._halt_physical(cycle, "selected direction cannot continue", started=True)
        evaluation_request = self.budget.allocate(candidate, direction_id=direction, depth=depth)
        operation = self._reserve_physical(candidate, "operator", cycle)
        if not operation.granted:
            return self._halt_physical(cycle, operation.reason, started=True)
        self.budget.start_operation(operation.intent_id, fingerprint=operation.fingerprint)
        request = replace(request, context={**request.context, "budget": {
            "state": self.budget.state(), "allocated_request": asdict(evaluation_request),
            "direction_id": direction, "depth": depth}})
        started, settled, failure = time.monotonic(), False, None
        before = self.parts["provider"].usage_total
        try:
            try:
                proposal = await operator.propose(request)
            except OperatorFailure as error:
                failure = error
                proposal = Proposal(candidate, "", error.cost, error.measured_cost_units)
            if not isinstance(proposal, Proposal):
                raise UsageError("operator returned no measurable Proposal")
            self._check_provider_floor(operation, before, proposal.cost)
            self._settle_physical(operation, proposal.cost, proposal.measured_cost_units,
                                  time.monotonic() - started, operator=True)
            settled = True
            if "node" in proposal.measured_cost_units and proposal.cost.node_count != 1:
                raise ValueError("operator node measurement differs from the actual candidate attempt")
        except Exception as error:
            if not settled:
                self._unresolved_physical(operation, error)
            raise
        if request.context.get("retrieval") != context["retrieval"] or \
                request.context.get("context_pack_ref") != context["context_pack_ref"]:
            raise ValueError("operator changed authoritative retrieval context")
        if proposal.candidate.id != identifier or proposal.candidate.parents != parents \
                or not isinstance(proposal.artifact, str):
            raise ValueError("operator proposal changed identity or lineage")
        proposal.candidate.validate()
        if proposal.candidate.context_pack_ref != context["context_pack_ref"]:
            raise ValueError("operator dropped or changed retrieval context identity")
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
        mutations = await self._planning_physical(absorb,
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
