"""Canonical same-cohort batch execution, accounting and serial admission."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import threading
from dataclasses import asdict, replace

from core.budget.currency import MultiCurrencyBudgetLedger
from core.budget.ledger import BudgetError
from core.eval.decision import AdmissionDecision
from core.executor.types import (Candidate, CostVec, EvalRequest, EvalResult, EvalStatus,
                                 EvidenceRecord, ExecutorSpec)
from core.policy.types import AllocationIntent, MutationOp, StateMutation
from core.state import _jsonable


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _cohort_id(candidates: list[Candidate], intents: list[AllocationIntent]) -> str:
    payload = {"candidate_ids": [candidate.id for candidate in candidates],
               "intent_ids": [intent.intent_id for intent in intents]}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _decision_payload(decision: AdmissionDecision) -> dict:
    payload = {"admit": decision.admit, "reason": decision.reason,
               "mutations": [{"op": mutation.op.value, "target": mutation.target,
                              "fields": mutation.fields, "rationale": mutation.rationale}
                             for mutation in decision.mutations]}
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _evidence_from_payload(payload: dict) -> EvidenceRecord:
    result = payload["eval_result"]
    evidence = EvidenceRecord(
        payload["candidate_id"],
        EvalResult(EvalStatus(result["status"]), dict(result.get("metrics", {})),
                   cost=CostVec(**result.get("cost", {})),
                   fidelity=result.get("fidelity", "dev"),
                   uncertainty=result.get("uncertainty"),
                   text_feedback=result.get("text_feedback"),
                   partial_curves_ref=result.get("partial_curves_ref"),
                   trajectory_ref=result.get("trajectory_ref"),
                   artifacts_ref=result.get("artifacts_ref")),
        branch_ref=payload.get("branch_ref"),
        executor_status=payload.get("executor_status", "scored"),
        attempt=payload.get("attempt", 1), insight=payload.get("insight"),
        result_text=payload.get("result_text"))
    return evidence


class BatchScheduler:
    """Execute one frozen candidate cohort; never parallelize governed state writes.

    This coordinator consumes canonical M7 EvidenceRecord costs. The opt-in M0
    prompt adapter serializes its process-global usage meter before entering this
    path; generic M7 executors may run concurrently. The caller owns pool lifetime.
    """

    def __init__(self, pool, ledger, policy, applier, store):
        self.pool = pool
        self.ledger = ledger
        self.policy = policy
        self.applier = applier
        self.store = store
        self._lock = threading.RLock()
        self._active = False
        self._last_admissions: dict[str, bool] = {}

    @property
    def last_admissions(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._last_admissions)

    def recovery_state(self) -> dict:
        """Return the newest journaled cohort without mutating search state."""
        events = [record for record in self.store.read()
                  if isinstance(record.get("payload"), dict)
                  and record["payload"].get("cohort_id")]
        started = [record["payload"] for record in events
                   if record["kind"] == "batch_cycle_started"]
        if not started:
            return {"schema_version": 1, "cohort_id": None, "status": "none",
                    "recovery_required": False, "pending_candidates": []}
        cohort = started[-1]
        cohort_id = cohort["cohort_id"]
        ids = list(cohort["candidate_ids"])
        selected = [record for record in events
                    if record["payload"].get("cohort_id") == cohort_id]
        completed = any(record["kind"] == "batch_cycle_completed"
                        for record in selected)
        rejected = any(record["kind"] == "batch_budget_rejected"
                       for record in selected)
        settled = [record["payload"] for record in selected
                   if record["kind"] == "batch_execution_settled"]
        admitted = {record["payload"]["candidate_id"] for record in selected
                    if record["kind"] == "batch_admission"}
        decided = {record["payload"]["candidate_id"] for record in selected
                   if record["kind"] == "batch_decision"}
        ambiguous = sorted(decided - admitted)
        settled_candidates = {item["candidate_id"] for item in settled}
        intent_candidates = {item["intent_id"]: item["candidate_ref"]
                             for item in cohort.get("intents", [])}
        interrupted_accounting = {entry["payload"]["intent_id"]
                                  for entry in self.store.read("ledger")
                                  if entry["payload"].get("entry_kind")
                                  in {"settle", "reserve_released"}}
        accounting_ambiguous = sorted(
            intent_candidates[intent_id] for intent_id in interrupted_accounting
            if intent_id in intent_candidates
            and intent_candidates[intent_id] not in settled_candidates)
        released_intents = {entry["payload"]["intent_id"]
                            for entry in self.store.read("ledger")
                            if entry["payload"].get("entry_kind") == "reserve_released"}
        accounting_recovery_safe = bool(accounting_ambiguous) and not any(
            intent_id in released_intents for intent_id in intent_candidates)
        if completed:
            status = "completed"
        elif rejected:
            status = "budget_rejected"
        elif any(record["kind"] == "batch_cycle_aborted" for record in selected):
            status = "aborted"
        elif accounting_ambiguous:
            status = "accounting_ambiguous"
        elif len(settled) != len(ids):
            status = "execution_incomplete"
        elif ambiguous:
            status = "ambiguous"
        else:
            status = "ready"
        pending = [candidate_id for candidate_id in ids if candidate_id not in admitted]
        return {"schema_version": 1, "cohort_id": cohort_id, "status": status,
                "recovery_required": status in {"execution_incomplete", "accounting_ambiguous",
                                                "ambiguous", "ready"},
                "pending_candidates": pending, "ambiguous_candidates": ambiguous,
                "accounting_ambiguous_candidates": accounting_ambiguous,
                "accounting_recovery_safe": accounting_recovery_safe,
                "settled_evidence": len(settled), "candidate_count": len(ids)}

    def checkpoint_state(self) -> dict:
        with self._lock:
            if self._active or self.ledger.reserves:
                raise RuntimeError(
                    "BatchScheduler checkpoint requires an inactive, fully settled cohort")
            return {"schema_version": 2, "executor": self.pool.checkpoint_state(),
                    "open_reserves": [], "recovery": self.recovery_state()}

    @staticmethod
    def _actual_cost(evidence: EvidenceRecord) -> int:
        cost = evidence.eval_result.cost
        values = (cost.tokens_in, cost.tokens_out)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in values):
            raise BudgetError("executor token costs must be non-negative integers")
        return cost.tokens_in + cost.tokens_out

    @staticmethod
    def _actual_costs(evidence: EvidenceRecord,
                      reserved_amounts: dict[str, float]) -> dict[str, float]:
        """Project explicit executor costs onto exactly the reserved physical units."""
        cost = evidence.eval_result.cost
        token_cost = BatchScheduler._actual_cost(evidence)
        values = {"token": token_cost, "usd": cost.usd,
                  "eval_count": cost.eval_count, "node": cost.node_count,
                  "wallclock": cost.wall_seconds, "gpu_hours": cost.gpu_hours}
        actual = {}
        for unit in reserved_amounts:
            if unit not in values:
                raise BudgetError(f"unsupported executor cost unit: {unit}")
            value = values[unit]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise BudgetError(f"executor {unit} cost must be finite and non-negative")
            if unit in {"eval_count", "node"} and (
                    not isinstance(value, int) or isinstance(value, bool)):
                raise BudgetError(f"executor {unit} cost must be a non-negative integer")
            actual[unit] = value
        return actual

    def _bounded_request(self, request: EvalRequest,
                         intent: AllocationIntent) -> EvalRequest:
        if not isinstance(self.ledger, MultiCurrencyBudgetLedger):
            if intent.requested_amounts:
                raise BudgetError("single-currency ledger cannot reserve a cost basket")
            return replace(request, budget_token=intent.requested)
        amounts = self.ledger.requested_amounts(intent)
        if "token" not in amounts:
            return replace(request, budget_token=None)
        token_budget = amounts["token"]
        if (isinstance(token_budget, bool) or not isinstance(token_budget, (int, float))
                or not math.isfinite(token_budget) or token_budget < 0
                or int(token_budget) != token_budget):
            raise BudgetError("reserved token budget must be a non-negative integer")
        return replace(request, budget_token=int(token_budget))

    @staticmethod
    def _validate_decision(candidate: Candidate, evidence: EvidenceRecord,
                           decision: AdmissionDecision) -> None:
        if not isinstance(decision, AdmissionDecision) \
                or not isinstance(decision.admit, bool):
            raise ValueError("admission must return AdmissionDecision with a boolean admit")
        if evidence.eval_result.status is not EvalStatus.OK and decision.admit:
            raise ValueError("non-OK evidence cannot be admitted")
        if not all(isinstance(mutation, StateMutation)
                   for mutation in decision.mutations):
            raise ValueError("admission mutations must be StateMutation objects")
        expected = MutationOp.MERGE if decision.admit else MutationOp.PRUNE
        primary = [mutation for mutation in decision.mutations
                   if mutation.target == candidate.id
                   and mutation.op in {MutationOp.MERGE, MutationOp.PRUNE}]
        if len(primary) != 1 or primary[0].op is not expected:
            raise ValueError("admission requires exactly one candidate MERGE or PRUNE")

    async def _finalize(self, candidate: Candidate, evidence: EvidenceRecord,
                        admission, cohort_id: str, absorb: bool = True,
                        expected_decision: dict | None = None,
                        record: bool = True,
                        record_absorb: bool | None = None) -> None:
        if absorb:
            self.applier.apply(StateMutation(
                MutationOp.ADD_NODE, candidate.id,
                {"candidate": candidate, "evidence": evidence},
                "materialize batch candidate evidence"))
            for mutation in await self.policy.absorb(evidence):
                await self.applier.apply_async(mutation)
            if (record if record_absorb is None else record_absorb):
                self.store.append("batch_absorbed", {
                    "cohort_id": cohort_id, "candidate_id": candidate.id})
        decision = admission(candidate, evidence)
        if inspect.isawaitable(decision):
            decision = await decision
        self._validate_decision(candidate, evidence, decision)
        payload = _decision_payload(decision)
        if expected_decision is not None and payload != expected_decision:
            raise ValueError("resumed admission decision differs from journaled decision")
        if record:
            self.store.append("batch_decision", {
                "cohort_id": cohort_id, "candidate_id": candidate.id,
                "decision": payload})
        for mutation in decision.mutations:
            await self.applier.apply_async(mutation)
        with self._lock:
            self._last_admissions[candidate.id] = decision.admit
        if record:
            self.store.append("batch_admission", {
                "cohort_id": cohort_id, "candidate_id": candidate.id,
                "admit": decision.admit, "reason": decision.reason,
                "decision": payload})

    def _restore_ledger_for_recovery(self) -> None:
        if isinstance(self.ledger, MultiCurrencyBudgetLedger):
            fresh = (not self.ledger.reserves and not self.ledger.settled_intents
                     and not any(value for values in self.ledger.spent.values()
                                 for value in values.values()))
        else:
            fresh = (not self.ledger.reserves and not self.ledger.settled_intents
                     and not any(self.ledger.spent.values()))
        if fresh:
            self.ledger.restore_from_journal()

    def _recorded_costs(self, intent: AllocationIntent) -> dict[str, float]:
        recorded = {}
        for entry in self.store.read("ledger"):
            payload = entry["payload"]
            if payload.get("intent_id") != intent.intent_id \
                    or payload.get("entry_kind") != "settle":
                continue
            unit = payload.get("unit", "token")
            if payload.get("account") != intent.account or unit in recorded:
                raise BudgetError("accounting_ambiguous: duplicate or cross-account settlement")
            recorded[unit] = payload.get("settled", 0.0)
        return recorded

    def _recover_execution(self, cohort_id: str, workspace) -> None:
        """Settle durable executor evidence, never rerun candidates or admit early."""
        if workspace is None and getattr(self.pool.backend, "recovery_requires_workspace", True):
            raise RuntimeError("execution_incomplete recovery requires its original workspace")
        started = [record["payload"] for record in self.store.read("batch_cycle_started")
                   if record["payload"].get("cohort_id") == cohort_id]
        if len(started) != 1:
            raise ValueError("execution recovery requires exactly one cohort start")
        cohort = started[0]
        ids = cohort["candidate_ids"]
        if len(cohort.get("intents", [])) != len(ids):
            raise ValueError("execution recovery requires durable allocation intents")
        intents = [AllocationIntent(**payload) for payload in cohort["intents"]]
        if [intent.candidate_ref for intent in intents] != ids:
            raise ValueError("journaled intents do not match cohort candidates")
        self._restore_ledger_for_recovery()
        recover = getattr(self.pool.backend, "recover_inflight", None)
        if recover is None:
            raise RuntimeError("executor does not support in-flight recovery")
        recover(workspace, execution_ref=cohort_id)
        process_records = [record["payload"]
                           for record in self.store.read("executor_process_started")
                           if record["payload"].get("execution_ref") == cohort_id
                           and record["payload"].get("process_kind") != "m0_external_proposer"]
        nonprocess_hook = getattr(self.pool.backend, "recovery_nonprocess_executions", None)
        nonprocess_records = nonprocess_hook(cohort_id) if nonprocess_hook is not None else []
        execution_records = [*process_records, *nonprocess_records]
        by_execution = {record["execution_id"]: record for record in execution_records}
        execution_candidates = [record["candidate_id"] for record in execution_records]
        if len(by_execution) != len(execution_records) or len(execution_records) != len(ids) \
                or len(set(execution_candidates)) != len(execution_candidates) \
                or set(execution_candidates) != set(ids):
            raise RuntimeError("execution journal is incomplete for the active cohort")
        evidence_events: dict[str, list[dict]] = {}
        for record in self.store.read("executor_evidence"):
            execution_id = record["payload"].get("execution_id")
            if execution_id in by_execution:
                evidence_events.setdefault(execution_id, []).append(record["payload"])
        if any(len(events) != 1 for events in evidence_events.values()):
            raise ValueError("duplicate executor evidence blocks batch recovery")
        evidence = {}
        for execution_id, process in by_execution.items():
            events = evidence_events.get(execution_id, [])
            if not events:
                raise RuntimeError("execution_pending: durable executor evidence is incomplete")
            item = _evidence_from_payload(events[0]["evidence"])
            if item.candidate_id != process["candidate_id"]:
                raise ValueError("executor evidence does not match its process journal")
            evidence[item.candidate_id] = item
        if set(evidence) != set(ids):
            raise RuntimeError("execution_pending: cohort evidence is incomplete")
        results = [evidence[candidate_id] for candidate_id in ids]
        prior = {record["payload"]["candidate_id"]: record["payload"]
                 for record in self.store.read("batch_execution_settled")
                 if record["payload"].get("cohort_id") == cohort_id}
        for candidate_id, item in prior.items():
            if asdict(_evidence_from_payload(item["evidence"])) != asdict(evidence[candidate_id]):
                raise ValueError("recovered evidence differs from settled evidence")
        pending = [(intent, evidence[intent.candidate_ref]) for intent in intents
                   if intent.candidate_ref not in prior]
        multi = isinstance(self.ledger, MultiCurrencyBudgetLedger)
        # Project onto the original complete reservation, not merely un-settled units.
        actual_costs = [self._actual_costs(item, self.ledger.requested_amounts(intent))
                        if multi else {"token": self._actual_cost(item)}
                        for intent, item in pending]
        plans = []
        for (intent, item), actual in zip(pending, actual_costs):
            recorded = self._recorded_costs(intent)
            if set(recorded) - set(actual) \
                    or any(recorded[unit] != actual[unit] for unit in recorded):
                raise BudgetError("accounting_ambiguous: journaled and executor costs differ")
            reserve = self.ledger.reserves.get(intent.intent_id)
            remaining = None
            if set(recorded) != set(actual):
                missing = set(actual) - set(recorded)
                if reserve is None or intent.intent_id in self.ledger.settled_intents:
                    raise BudgetError("accounting_ambiguous: recovered reserve is missing")
                if multi:
                    if set(reserve.amounts) != missing \
                            or any(reserve.amounts[unit]
                                   != self.ledger.requested_amounts(intent)[unit]
                                   for unit in missing):
                        raise BudgetError("accounting_ambiguous: partial reserve does not match")
                    remaining = {unit: actual[unit] for unit in missing}
                else:
                    if recorded or reserve.amount != intent.requested:
                        raise BudgetError("accounting_ambiguous: invalid token reserve replay")
                    remaining = actual
            elif reserve is not None or intent.intent_id not in self.ledger.settled_intents:
                raise BudgetError("accounting_ambiguous: complete settlement has invalid state")
            plans.append((intent, item, actual, remaining))
        # Every plan is validated before any new ledger mutation. A fully journaled
        # settlement only appends its missing batch evidence; partial baskets settle
        # exactly their missing physical units.
        for intent, item, actual, remaining in plans:
            if remaining is not None:
                if multi:
                    self.ledger.settle(intent, actual_costs=remaining)
                else:
                    self.ledger.settle(intent, actual_cost=remaining["token"])
            self.store.append("batch_execution_settled", {
                "cohort_id": cohort_id, "candidate_id": intent.candidate_ref,
                "intent_id": intent.intent_id, "actual_token_cost": actual.get("token"),
                "actual_costs": actual, "evidence": asdict(item),
                "status": item.eval_result.status.value, "recovered": True})

    def _recovery_payloads(self, cohort_id: str) -> tuple:
        records = [record for record in self.store.read()
                   if isinstance(record.get("payload"), dict)
                   and record["payload"].get("cohort_id") == cohort_id]
        started = [record["payload"] for record in records
                   if record["kind"] == "batch_cycle_started"]
        if len(started) != 1:
            raise ValueError("recovery requires exactly one cohort start record")
        cohort = started[0]
        ids = cohort["candidate_ids"]
        if cohort.get("intent_ids") is not None:
            digest_payload = {"candidate_ids": ids,
                              "intent_ids": cohort["intent_ids"]}
            if cohort_id != hashlib.sha256(
                    _canonical(digest_payload).encode("utf-8")).hexdigest():
                raise ValueError("cohort identity does not match its journal")
        candidates = [Candidate(**payload) for payload in cohort["candidates"]]
        if [candidate.id for candidate in candidates] != ids:
            raise ValueError("cohort candidate journal is inconsistent")
        settled = [record["payload"] for record in records
                   if record["kind"] == "batch_execution_settled"]
        if len(settled) != len(ids) or {item["candidate_id"] for item in settled} != set(ids):
            raise ValueError("recovery requires one settled evidence record per candidate")
        evidence = {item["candidate_id"]: _evidence_from_payload(item["evidence"])
                    for item in settled}
        if any(evidence[candidate_id].candidate_id != candidate_id for candidate_id in ids):
            raise ValueError("settled evidence candidate mismatch")
        absorbed_rows = [record["payload"] for record in records
                         if record["kind"] == "batch_absorbed"]
        decision_rows = [record["payload"] for record in records
                         if record["kind"] == "batch_decision"]
        admission_rows = [record["payload"] for record in records
                          if record["kind"] == "batch_admission"]
        absorbed = {item["candidate_id"] for item in absorbed_rows}
        decisions = {item["candidate_id"]: item["decision"] for item in decision_rows}
        admissions = {item["candidate_id"]: item for item in admission_rows}
        if (len(absorbed) != len(absorbed_rows) or len(decisions) != len(decision_rows)
                or len(admissions) != len(admission_rows)
                or not (absorbed | set(decisions) | set(admissions)).issubset(ids)):
            raise ValueError("duplicate or foreign batch finalization evidence")
        return ids, candidates, evidence, absorbed, decisions, admissions

    async def _apply_recovery_mutation(self, mutation: StateMutation,
                                       cursor: list[int]) -> None:
        """Apply only the missing suffix and replay exact durable mutations silently."""
        rows = list(self.store.read("state_mutation"))
        index = cursor[0]
        if len(rows) < index:
            raise RuntimeError("checkpoint mutation cursor exceeds durable history")
        if len(rows) == index:
            await self.applier.apply_async(mutation)
        else:
            actual = {key: value for key, value in rows[index]["payload"].items()
                      if key != "result"}
            if actual != _jsonable(mutation):
                raise RuntimeError("post-checkpoint batch mutation history differs from plan")
            self.applier.replay(mutation)
        cursor[0] += 1

    async def _finalize_recovered(self, candidate: Candidate, evidence: EvidenceRecord,
                                  admission, cohort_id: str, absorbed: set,
                                  decisions: dict, admissions: dict,
                                  cursor: list[int]) -> None:
        """Resume one candidate with exact mutation and journal-boundary validation."""
        candidate_id = candidate.id
        absorb_mutations = [StateMutation(
            MutationOp.ADD_NODE, candidate_id,
            {"candidate": candidate, "evidence": evidence},
            "materialize batch candidate evidence"),
            *await self.policy.absorb(evidence)]
        durable = len(list(self.store.read("state_mutation")))
        absorb_end = cursor[0] + len(absorb_mutations)
        if (candidate_id in absorbed) != (durable > absorb_end):
            if durable != absorb_end:
                raise RuntimeError("batch absorb marker and mutation suffix are inconsistent")
        if candidate_id in absorbed and durable < absorb_end:
            raise RuntimeError("batch absorb marker precedes its mutations")
        for mutation in absorb_mutations:
            await self._apply_recovery_mutation(mutation, cursor)
        if candidate_id not in absorbed:
            self.store.append("batch_absorbed", {
                "cohort_id": cohort_id, "candidate_id": candidate_id})

        decision = admission(candidate, evidence)
        if inspect.isawaitable(decision):
            decision = await decision
        self._validate_decision(candidate, evidence, decision)
        payload = _decision_payload(decision)
        expected = decisions.get(candidate_id)
        if expected is not None and payload != expected:
            raise ValueError("resumed admission decision differs from journaled decision")
        if expected is None:
            if candidate_id in admissions:
                raise RuntimeError("batch admission lacks its decision")
            self.store.append("batch_decision", {
                "cohort_id": cohort_id, "candidate_id": candidate_id,
                "decision": payload})

        durable = len(list(self.store.read("state_mutation")))
        admission_end = cursor[0] + len(decision.mutations)
        if candidate_id in admissions and durable < admission_end:
            raise RuntimeError("batch admission marker precedes its mutations")
        if candidate_id not in admissions and durable > admission_end:
            raise RuntimeError("batch admission marker is missing before later mutations")
        for mutation in decision.mutations:
            await self._apply_recovery_mutation(mutation, cursor)
        with self._lock:
            self._last_admissions[candidate_id] = decision.admit
        expected_admission = {"cohort_id": cohort_id, "candidate_id": candidate_id,
                              "admit": decision.admit, "reason": decision.reason,
                              "decision": payload}
        prior_admission = admissions.get(candidate_id)
        if prior_admission is None:
            self.store.append("batch_admission", expected_admission)
        elif prior_admission != expected_admission:
            raise RuntimeError("recovered batch admission differs from its journal")

    @staticmethod
    def _check_final_node(frontier, candidate_id: str, admission: dict) -> None:
        node = frontier.nodes.get(candidate_id)
        expected = "merged" if admission["admit"] else "pruned"
        if node is None or node.status != expected:
            raise ValueError(f"restored frontier does not match admission for {candidate_id}")

    async def resume(self, admission, workspace=None,
                     mutation_start: int | None = None) -> list[EvidenceRecord]:
        """Recover detached execution if needed, then continue serial finalization.

        A checkpoint mutation cursor opts into exact post-checkpoint suffix replay.
        Without it, decision-without-admission remains ambiguous as in v16.
        """
        cursor_recovery = mutation_start is not None
        if cursor_recovery and (isinstance(mutation_start, bool)
                                or not isinstance(mutation_start, int) or mutation_start < 0):
            raise ValueError("batch recovery mutation cursor must be non-negative")
        state = self.recovery_state()
        allowed = {"ready", "completed", "execution_incomplete", "accounting_ambiguous"}
        if cursor_recovery:
            allowed.add("ambiguous")
        if state["status"] not in allowed:
            raise RuntimeError(f"batch recovery is not automatic: {state['status']}")
        if state["status"] == "accounting_ambiguous" \
                and not state.get("accounting_recovery_safe"):
            raise RuntimeError("batch recovery is not automatic: accounting_ambiguous")
        if state["status"] in {"execution_incomplete", "accounting_ambiguous"} \
                and workspace is None \
                and getattr(self.pool.backend, "recovery_requires_workspace", True):
            raise RuntimeError(f"batch recovery is not automatic: {state['status']}")
        with self._lock:
            if self._active:
                raise RuntimeError("BatchScheduler accepts one cohort at a time")
            self._active = True
            self._last_admissions = {}
        try:
            cohort_id = state["cohort_id"]
            if state["status"] in {"execution_incomplete", "accounting_ambiguous"}:
                self._recover_execution(cohort_id, workspace)
                state = self.recovery_state()
                expected_states = {"ready", "ambiguous"} if cursor_recovery else {"ready"}
                if state["status"] not in expected_states:
                    raise RuntimeError(f"batch recovery is not automatic: {state['status']}")
            ids, candidates, evidence, absorbed, decisions, admissions = \
                self._recovery_payloads(cohort_id)
            results = [evidence[candidate_id] for candidate_id in ids]
            if cursor_recovery:
                cursor = [mutation_start]
                for candidate in candidates:
                    await self._finalize_recovered(
                        candidate, evidence[candidate.id], admission, cohort_id,
                        absorbed, decisions, admissions, cursor)
                if len(list(self.store.read("state_mutation"))) != cursor[0]:
                    raise RuntimeError("post-checkpoint batch mutation suffix has extra entries")
                completed = [record["payload"] for record in self.store.read(
                    "batch_cycle_completed")
                    if record["payload"].get("cohort_id") == cohort_id]
                payload = {"cohort_id": cohort_id, "candidate_ids": ids,
                           "admissions": self.last_admissions}
                if not completed:
                    self.store.append("batch_cycle_completed", payload)
                elif len(completed) != 1 or completed[0] != payload:
                    raise RuntimeError("duplicate or mismatched batch completion evidence")
                return results
            if state["status"] == "completed":
                for candidate_id in ids:
                    self._check_final_node(self.applier.frontier,
                                           candidate_id, admissions[candidate_id])
                self._last_admissions = {
                    candidate_id: admissions[candidate_id]["admit"] for candidate_id in ids}
                return results
            for candidate in candidates:
                candidate_id = candidate.id
                prior_admission = admissions.get(candidate_id)
                node = self.applier.frontier.nodes.get(candidate_id)
                if prior_admission is not None and node is not None:
                    self._check_final_node(self.applier.frontier,
                                           candidate_id, prior_admission)
                    self._last_admissions[candidate_id] = prior_admission["admit"]
                    continue
                if prior_admission is None and node is not None \
                        and candidate_id not in absorbed:
                    raise ValueError("unjournaled frontier state blocks batch recovery")
                await self._finalize(
                    candidate, evidence[candidate_id], admission, cohort_id,
                    absorb=node is None, expected_decision=decisions.get(candidate_id),
                    record=prior_admission is None,
                    record_absorb=(prior_admission is None and candidate_id not in absorbed))
            self.store.append("batch_cycle_completed", {
                "cohort_id": cohort_id, "candidate_ids": ids,
                "admissions": self.last_admissions})
            return results
        finally:
            with self._lock:
                self._active = False

    async def run(self, specs: list[ExecutorSpec], candidates: list[Candidate],
                  workspace, requests: list[EvalRequest], intents: list[AllocationIntent],
                  admission) -> list[EvidenceRecord]:
        if not (len(specs) == len(candidates) == len(requests) == len(intents)):
            raise ValueError("batch specs, candidates, requests and intents must align")
        if not candidates:
            return []
        ids = [candidate.id for candidate in candidates]
        if any(not candidate_id for candidate_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("batch candidate ids must be non-empty and unique")
        for candidate, request, intent in zip(candidates, requests, intents):
            candidate.validate()
            request.validate()
            if intent.candidate_ref != candidate.id:
                raise ValueError("allocation intent candidate does not match batch")
        recovery = self.recovery_state()
        if recovery["recovery_required"]:
            raise RuntimeError("recover the previous cohort before starting a new batch")
        with self._lock:
            if self._active:
                raise RuntimeError("BatchScheduler accepts one cohort at a time")
            self._active = True
            self._last_admissions = {}
        reserved = []
        submitted = False
        rejected = False
        cohort_id = _cohort_id(candidates, intents)
        try:
            self.store.append("batch_cycle_started", {
                "cohort_id": cohort_id, "candidate_ids": ids,
                "intent_ids": [intent.intent_id for intent in intents],
                "candidates": [asdict(candidate) for candidate in candidates],
                "intents": [asdict(intent) for intent in intents]})
            for intent in intents:
                receipt = self.ledger.quote_reserve(intent)
                if receipt.verdict != "granted":
                    for previous in reversed(reserved):
                        self.ledger.release_for(previous)
                    rejected = True
                    self.store.append("batch_budget_rejected", {
                        "cohort_id": cohort_id,
                        "rejected_intent": intent.intent_id,
                        "verdict": receipt.verdict, "reason": receipt.reason,
                        "released_intents": [item.intent_id for item in reserved]})
                    raise BudgetError(
                        f"batch reservation rejected for {intent.candidate_ref}: {receipt.reason}")
                reserved.append(intent)
            self.ledger.pre_call_check()
            bounded_requests = [self._bounded_request(request, intent)
                                for request, intent in zip(requests, intents)]
            correlated_specs = [replace(spec, execution_ref=cohort_id) for spec in specs]
            prepare = getattr(self.pool.backend, "prepare", None)
            if prepare is not None:
                prepare(correlated_specs, candidates, bounded_requests, intents)
            submitted = True
            results = await self.pool.run_many(correlated_specs, candidates, workspace,
                                               bounded_requests)
            with self._lock:
                if not self._active:
                    raise RuntimeError("batch scheduler lost active cohort ownership")
            # Validate the entire cohort before mutating any ledger account. This
            # prevents a malformed later CostVec from leaving a half-settled batch.
            if isinstance(self.ledger, MultiCurrencyBudgetLedger):
                actual_costs = [self._actual_costs(
                    evidence, self.ledger.reserves[intent.intent_id].amounts)
                    for intent, evidence in zip(intents, results)]
            else:
                actual_costs = [{"token": self._actual_cost(evidence)}
                                for evidence in results]
            # Settle every real execution before any admission callback can fail.
            for intent, evidence, actual in zip(intents, results, actual_costs):
                if isinstance(self.ledger, MultiCurrencyBudgetLedger):
                    self.ledger.settle(intent, actual_costs=actual)
                else:
                    self.ledger.settle(intent, actual_cost=actual["token"])
                self.store.append("batch_execution_settled", {
                    "cohort_id": cohort_id,
                    "candidate_id": intent.candidate_ref, "intent_id": intent.intent_id,
                    "actual_token_cost": actual.get("token"),
                    "actual_costs": actual, "evidence": asdict(evidence),
                    "status": evidence.eval_result.status.value})
            # The cohort was frozen before execution; only this serial loop changes state.
            for candidate, evidence in zip(candidates, results):
                await self._finalize(candidate, evidence, admission, cohort_id)
            self.store.append("batch_cycle_completed", {
                "cohort_id": cohort_id, "candidate_ids": ids,
                "admissions": self.last_admissions})
            return results
        finally:
            # Only unexecuted/unreturned reservations can remain here. Every returned
            # evidence was settled above; real costs are never erased with release.
            for intent in intents:
                if intent.intent_id in self.ledger.reserves:
                    self.ledger.release_for(intent)
            if not submitted and not rejected:
                self.store.append("batch_cycle_aborted", {"cohort_id": cohort_id})
            with self._lock:
                self._active = False
