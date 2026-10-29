"""Adapt the sequential M0 prompt evaluator to canonical M7 batch evidence.

The public M0 evaluator exposes only a process-global ``last_usage`` meter. The
adapter therefore serializes the complete metered propose/evaluate section. This
preserves exact per-candidate accounting; it deliberately does not claim parallel
execution of an evaluator whose meter is not concurrency-safe.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from core.eval.types import (EvalResult as M0EvalResult, ItemResult,
                             ReliabilityMeta)
from core.executor.external import ExternalCommandEvaluator, ExternalEvaluatorError
from core.executor.proposal import ExternalCommandLLM, ExternalProposalError
from core.executor.types import (Candidate, CostVec, EvalRequest, EvalResult,
                                 EvalStatus, EvidenceRecord, ExecutorSpec)
from core.llm import take_usage
from core.operator.types import VariationProposal
from core.policy.types import AllocationIntent


@dataclass
class M0NativeOutcome:
    """In-process display/gate payload paired with canonical executor evidence."""

    proposal: object | None
    result: M0EvalResult | None


def _marker_sha256(marker: dict) -> str:
    canonical = json.dumps(marker, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _inprocess_execution_id(cohort_id: str, candidate_id: str) -> str:
    return "m0-inprocess-" + hashlib.sha256(
        f"{cohort_id}\0{candidate_id}".encode("utf-8")).hexdigest()


def _inprocess_evaluation_execution_id(context: dict) -> str:
    digest = _marker_sha256(context).split(":", 1)[1]
    return "m0-inprocess-evaluation-" + hashlib.sha256(
        f"{context['proposal']['proposal_id']}\0{digest}".encode("utf-8")).hexdigest()


def _batch_evaluation_operation(context: dict) -> dict:
    candidate_id = context["proposal"]["proposal_id"]
    return {"schema_version": 1, "adapter": "in_process",
            "cohort_id": context["cohort_id"], "candidate_id": candidate_id,
            "execution_id": _inprocess_evaluation_execution_id(context),
            "evaluation_sha256": _marker_sha256(context)}


def _restore_m0_result(data: dict) -> M0EvalResult:
    reliability = dict(data.get("reliability") or {})
    if reliability.get("ci95") is not None:
        reliability["ci95"] = tuple(reliability["ci95"])
    return M0EvalResult(
        candidate_id=data["candidate_id"], head_sha=data["head_sha"],
        items=[ItemResult(**item) for item in data["items"]],
        combined_score=data.get("combined_score", 0.0),
        public=dict(data.get("public") or {}), private=dict(data.get("private") or {}),
        text_feedback=data.get("text_feedback", ""),
        reliability=ReliabilityMeta(**reliability),
        evaluator_version=data.get("evaluator_version", "det-v1"))


def inprocess_evaluation_operation_state(store, cohort_id: str,
                                         contexts: dict[str, dict],
                                         failed_ids=()) -> dict:
    """Validate actual batch evaluation operations separately from prepared proposals."""
    failed_ids = set(failed_ids)
    operations = [row["payload"] for row in store.read("m0_batch_evaluation_started")
                  if row["payload"].get("cohort_id") == cohort_id]
    by_candidate = {}
    for operation in operations:
        candidate_id = operation.get("candidate_id")
        if candidate_id in by_candidate or candidate_id in failed_ids \
                or candidate_id not in contexts \
                or operation != _batch_evaluation_operation(contexts[candidate_id]):
            raise RuntimeError("in-process batch evaluation operation is invalid")
        by_candidate[candidate_id] = operation
    outcome_rows = [row["payload"] for row in store.read("m0_evaluation_outcome")
                    if row["payload"].get("execution_ref") == cohort_id]
    outcomes = {}
    for outcome in outcome_rows:
        candidate_id = outcome.get("candidate_id")
        operation = by_candidate.get(candidate_id)
        if candidate_id in outcomes or operation is None \
                or outcome.get("execution_id") != operation.get("execution_id"):
            raise RuntimeError("in-process batch evaluation outcome is unbound or duplicated")
        context = contexts[candidate_id]
        if (outcome.get("schema_version") != 1
                or outcome.get("adapter") != "in_process"
                or outcome.get("generation") != context.get("generation")
                or outcome.get("operator") != context.get("operator")
                or outcome.get("start_sha256") != _marker_sha256(operation)
                or outcome.get("evaluation_sha256") != _marker_sha256(context)):
            raise RuntimeError("in-process batch evaluation outcome binding is invalid")
        usage = outcome.get("token_usage") or {}
        tokens = usage.get("total_tokens")
        if set(usage) != {"total_tokens"} or isinstance(tokens, bool) \
                or not isinstance(tokens, int) or tokens < 0:
            raise RuntimeError("in-process batch evaluation token usage is invalid")
        status = outcome.get("status")
        if status not in {"ok", "failed_to_run", "timeout", "invalid"} \
                or not isinstance(outcome.get("detail"), str):
            raise RuntimeError("in-process batch evaluation outcome status is invalid")
        if status == "ok":
            try:
                result = _restore_m0_result(outcome["result"])
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError("in-process batch evaluation result is invalid") from error
            if result.candidate_id != candidate_id \
                    or result.head_sha != context.get("head_sha"):
                raise RuntimeError("in-process batch evaluation result differs from its start")
        elif outcome.get("result") is not None:
            raise RuntimeError("failed in-process batch outcome cannot contain a result")
        outcomes[candidate_id] = outcome
    missing_outcomes = set(by_candidate) - set(outcomes)
    if missing_outcomes:
        raise RuntimeError("in-process batch evaluation is active or lacks its terminal outcome")
    missing = [candidate_id for candidate_id in contexts
               if candidate_id not in by_candidate]
    return {"operations": by_candidate, "outcomes": outcomes, "missing": missing}


def proposal_operation_state(store, cohort_id: str, ids: list[str]) -> dict:
    """Classify a strict prefix of durable proposal completions and one active call.

    A completion is either a successful evaluation-start context or a durable non-OK
    external proposer outcome. Successful proposer outcomes still require the normal
    start write, so an owner crash between those steps remains an active-call adoption.
    """
    starts = [row["payload"] for row in store.read("m0_evaluation_started")
              if row["payload"].get("cohort_id") == cohort_id]
    start_ids = [(context.get("proposal") or {}).get("proposal_id")
                 for context in starts]
    if len(set(start_ids)) != len(start_ids) or not set(start_ids).issubset(ids):
        raise RuntimeError("external M0 cohort proposal start journal is invalid")
    markers = [row["payload"] for row in store.read("m0_proposal_started")
               if row["payload"].get("cohort_id") == cohort_id]
    marker_ids = [marker.get("candidate_id") for marker in markers]
    failed = {}
    failure_sources = {}
    outcome_sources = (("external_proposer_outcome", "external"),
                       ("m0_proposal_outcome", "in_process"))
    for event_kind, source in outcome_sources:
        outcome_rows = [row["payload"] for row in store.read(event_kind)
                        if row["payload"].get("execution_ref") == cohort_id]
        for outcome in outcome_rows:
            candidate_id = outcome.get("operation_id")
            if outcome.get("status") == "ok":
                if source == "in_process":
                    raise RuntimeError("in-process proposal outcome must be terminal failure")
                continue
            if candidate_id not in ids or outcome.get("candidate_id") != candidate_id:
                raise RuntimeError("proposal failure has invalid candidate binding")
            if candidate_id in failed:
                raise RuntimeError("duplicate proposal operation outcomes")
            if candidate_id in start_ids:
                raise RuntimeError("proposal failure conflicts with its evaluation start")
            if source == "in_process":
                marker_index = ids.index(candidate_id)
                marker = markers[marker_index] if marker_index < len(markers) else None
                if (outcome.get("schema_version") != 1
                        or outcome.get("adapter") != "in_process"
                        or outcome.get("execution_id")
                        != _inprocess_execution_id(cohort_id, candidate_id)
                        or marker is None or marker.get("candidate_id") != candidate_id
                        or outcome.get("marker_sha256") != _marker_sha256(marker)):
                    raise RuntimeError("in-process proposal failure lacks its exact marker")
            failed[candidate_id] = outcome
            failure_sources[candidate_id] = source
    completed_ids = []
    for candidate_id in ids:
        if candidate_id in start_ids or candidate_id in failed:
            completed_ids.append(candidate_id)
        else:
            break
    expected_starts = [candidate_id for candidate_id in completed_ids
                       if candidate_id in start_ids]
    if start_ids != expected_starts:
        raise RuntimeError("external M0 cohort proposals must be an ordered prefix")
    active_call = len(markers) == len(completed_ids) + 1
    if marker_ids != ids[:len(markers)] or len(markers) > len(completed_ids) + 1:
        raise RuntimeError("incomplete M0 proposal operation is ambiguous")
    return {"starts": starts, "markers": markers, "completed_ids": completed_ids,
            "failed": failed, "failure_sources": failure_sources,
            "active_call": active_call}


class M0PromptExecutor:
    """Execute pre-registered deterministic proposal operations and M0 evaluation."""

    recovery_requires_workspace = False

    def __init__(self, llm, evaluator, operations: dict[str, Callable[[], object]],
                 fallback_token_cost: int, evidence_store=None):
        if isinstance(fallback_token_cost, bool) or not isinstance(fallback_token_cost, int) \
                or fallback_token_cost < 0:
            raise ValueError("fallback_token_cost must be a non-negative integer")
        self.llm = llm
        self.evaluator = evaluator
        self.store = evidence_store if evidence_store is not None else getattr(
            evaluator, "evidence_store", None)
        if self.store is None:
            raise ValueError("M0 executor requires an evidence store")
        self.operations = dict(operations)
        self.fallback_token_cost = fallback_token_cost
        self._meter_lock = threading.Lock()
        self._outcomes: dict[str, M0NativeOutcome] = {}
        self._prepared: dict[str, dict] = {}
        self._prepare_errors: dict[str, tuple[Exception, int]] = {}
        self._recovery_reports: dict[str, dict] = {}

    @staticmethod
    def _proposal_marker(spec, candidate, intent) -> dict:
        return {"cohort_id": spec.execution_ref, "generation": candidate.created_cycle,
                "operator": candidate.operator, "candidate_id": candidate.id,
                "intent": asdict(intent)}

    def _persist_proposal(self, spec, candidate, intent, marker=None) -> None:
        """Journal a new boundary or reuse one certified active operation marker."""
        take_usage(self.llm)
        if marker is None:
            marker = self._proposal_marker(spec, candidate, intent)
            self.store.append("m0_proposal_started", marker)
        durable_call = isinstance(self.llm, ExternalCommandLLM)
        if durable_call:
            self.llm.set_operation_context(marker)
        try:
            proposal = self.operations[candidate.id]()
            proposer_cost = take_usage(self.llm)
            if proposal.proposal_id != candidate.id:
                raise ValueError("M0 proposal differs from its frozen candidate")
            head_sha = hashlib.sha256(
                f"{proposal.proposal_id}\0{proposal.patch_text}".encode()
            ).hexdigest()[:8]
            context = {"cohort_id": spec.execution_ref,
                       "generation": candidate.created_cycle,
                       "operator": candidate.operator, "intent": asdict(intent),
                       "proposal": asdict(proposal), "head_sha": head_sha,
                       "proposer_token_cost": proposer_cost}
            self.store.append("m0_evaluation_started", context)
            self._prepared[candidate.id] = context
        except Exception as error:
            proposer_cost = take_usage(self.llm)
            self._prepare_errors[candidate.id] = (error, proposer_cost)
            if not durable_call:
                status = error.status if isinstance(error, ExternalProposalError) \
                    else EvalStatus.FAILED_TO_RUN
                detail = str(error) if isinstance(error, ExternalProposalError) \
                    else f"{type(error).__name__}: {error}"[-4000:]
                execution_id = _inprocess_execution_id(spec.execution_ref, candidate.id)
                self.store.append("m0_proposal_outcome", {
                    "schema_version": 1, "adapter": "in_process",
                    "execution_id": execution_id, "execution_ref": spec.execution_ref,
                    "operation_id": candidate.id, "candidate_id": candidate.id,
                    "status": status.value, "detail": detail,
                    "marker_sha256": _marker_sha256(marker),
                    "token_usage": {"total_tokens": proposer_cost}})
        finally:
            if durable_call:
                self.llm.clear_operation_context()

    def prepare(self, specs, candidates, requests, intents) -> None:
        """Persist every external proposal before any cohort process is launched."""
        del requests
        if not (len(specs) == len(candidates) == len(intents)):
            raise ValueError("M0 preparation inputs must align")
        for spec, candidate, intent in zip(specs, candidates, intents):
            self._persist_proposal(spec, candidate, intent)

    def _recover_proposals(self, cohort, records, prior) -> tuple[dict, list[str], list[str]]:
        """Resume successful and terminally failed durable proposal operations."""
        execution_ref = cohort["cohort_id"]
        ids = cohort["candidate_ids"]
        candidates = [Candidate(**payload) for payload in cohort["candidates"]]
        intents = [payload for payload in cohort["intents"]]
        if len(candidates) != len(ids) or len(intents) != len(ids) \
                or [candidate.id for candidate in candidates] != ids:
            raise RuntimeError("M0 recovery cohort inputs must align")
        store = self.store
        state = proposal_operation_state(store, execution_ref, ids)
        starts, markers = state["starts"], state["markers"]
        completed, active_call = state["completed_ids"], state["active_call"]
        if active_call and not isinstance(self.llm, ExternalCommandLLM):
            raise RuntimeError("incomplete M0 proposal operation is ambiguous")
        spec = ExecutorSpec(role="m0_prompt", execution_ref=execution_ref)
        starts_by_id = {(context.get("proposal") or {}).get("proposal_id"): context
                        for context in starts}
        for index, marker in enumerate(markers):
            candidate = candidates[index]
            expected = self._proposal_marker(spec, candidate, AllocationIntent(**intents[index]))
            start = starts_by_id.get(candidate.id)
            if marker != expected or (start is not None and (
                    start.get("generation") != marker["generation"]
                    or start.get("operator") != marker["operator"]
                    or start.get("intent") != marker["intent"])):
                raise RuntimeError("M0 proposal boundary does not match its durable context")
        if len(completed) < len(ids) and len(markers) not in (
                len(completed), len(completed) + (1 if active_call else 0)):
            raise RuntimeError("incomplete M0 proposals lack a certified operation boundary")
        if len(completed) < len(ids) and (records or prior):
            raise RuntimeError("incomplete M0 proposals cannot have processes or settlement")
        for candidate_id, outcome in state["failed"].items():
            if candidate_id in self._prepare_errors:
                continue
            status = {"timeout": EvalStatus.TIMEOUT, "invalid": EvalStatus.INVALID}.get(
                outcome.get("status"), EvalStatus.FAILED_TO_RUN)
            usage = outcome.get("token_usage") or {}
            tokens = usage.get("total_tokens")
            if set(usage) != {"total_tokens"} or isinstance(tokens, bool) \
                    or not isinstance(tokens, int) or tokens < 0:
                raise RuntimeError("recovered proposal failure has invalid token usage")
            self._prepare_errors[candidate_id] = (ExternalProposalError(
                status, str(outcome.get("detail") or "proposal failed"),
                outcome.get("execution_id")), tokens)
        for candidate, intent in zip(candidates, intents):
            context = starts_by_id.get(candidate.id)
            if context is None:
                continue
            if context.get("cohort_id") != execution_ref \
                    or context.get("generation") != candidate.created_cycle \
                    or context.get("operator") != candidate.operator \
                    or context.get("intent") != intent \
                    or context["proposal"]["parent_ids"] != candidate.parents \
                    or context["proposal"].get("apply_result") not in ("ok", "retry_ok"):
                raise RuntimeError("M0 recovery proposal or intent context is invalid")
            proposal = context["proposal"]
            head_sha = hashlib.sha256(
                f"{proposal['proposal_id']}\0{proposal['patch_text']}".encode()).hexdigest()[:8]
            proposer_cost = context.get("proposer_token_cost")
            if context.get("head_sha") != head_sha or isinstance(proposer_cost, bool) \
                    or not isinstance(proposer_cost, int) or proposer_cost < 0:
                raise RuntimeError("M0 recovery proposal cost or head is invalid")
            self._prepared[candidate.id] = context
        continued = []
        for offset, (candidate, intent_payload) in enumerate(zip(
                candidates[len(completed):], intents[len(completed):])):
            intent = AllocationIntent(**intent_payload)
            index = len(completed) + offset
            existing_marker = markers[index] if index < len(markers) else None
            self._persist_proposal(spec, candidate, intent, marker=existing_marker)
            if candidate.id not in self._prepared:
                self._validate_proposal_failure(candidate.id, execution_ref)
            continued.append(candidate.id)
        contexts = {candidate_id: self._prepared[candidate_id]
                    for candidate_id in ids if candidate_id in self._prepared}
        adopted = ids[len(completed):len(markers)] if active_call else []
        return contexts, continued, adopted

    def _validate_proposal_failure(self, candidate_id: str, execution_ref: str) -> dict:
        """Bind a non-OK prepare error to its real durable proposer execution."""
        prepared = self._prepare_errors.get(candidate_id)
        if prepared is None:
            raise RuntimeError("recovered M0 proposal operation did not complete")
        error, _cost = prepared
        if not isinstance(error, ExternalProposalError) or not error.execution_id:
            raise RuntimeError("recovered M0 proposal failure lacks durable evidence")
        if error.execution_id == _inprocess_execution_id(execution_ref, candidate_id):
            outcomes = [row["payload"] for row in self.store.read(
                "m0_proposal_outcome")
                if row["payload"].get("execution_id") == error.execution_id
                and row["payload"].get("execution_ref") == execution_ref
                and row["payload"].get("operation_id") == candidate_id
                and row["payload"].get("candidate_id") == candidate_id]
            if len(outcomes) != 1 or outcomes[0].get("status") == "ok" \
                    or outcomes[0].get("adapter") != "in_process":
                raise RuntimeError("recovered in-process proposal failure is not unique")
            return outcomes[0]
        outcomes = [row["payload"] for row in self.store.read(
            "external_proposer_outcome")
            if row["payload"].get("execution_id") == error.execution_id
            and row["payload"].get("execution_ref") == execution_ref
            and row["payload"].get("operation_id") == candidate_id
            and row["payload"].get("candidate_id") == candidate_id]
        if len(outcomes) != 1 or outcomes[0].get("status") == "ok":
            raise RuntimeError("recovered M0 proposal failure has ambiguous external evidence")
        outcome = outcomes[0]
        processes = [record for record in self.evaluator.processes.started(execution_ref)
                     if record.get("execution_id") == error.execution_id
                     and record.get("process_kind") == "m0_external_proposer"
                     and record.get("operation_id") == candidate_id]
        if len(processes) != 1:
            raise RuntimeError("recovered proposal failure lacks its original proposer process")
        request_path = Path(processes[0]["request_path"])
        request_sha = "sha256:" + hashlib.sha256(request_path.read_bytes()).hexdigest()
        if outcome.get("request_sha256") != request_sha:
            raise RuntimeError("recovered proposal failure differs from its operation request")
        return outcome

    def recovery_nonprocess_executions(self, execution_ref: str) -> list[dict]:
        """Expose real terminal proposer operations without inventing process records."""
        records = [{"execution_id": row["payload"]["execution_id"],
                    "candidate_id": row["payload"]["operation_id"],
                    "process_kind": "m0_external_proposer_terminal"}
                   for row in self.store.read("external_proposer_outcome")
                   if row["payload"].get("execution_ref") == execution_ref
                   and row["payload"].get("status") != "ok"]
        records.extend({"execution_id": row["payload"]["execution_id"],
                        "candidate_id": row["payload"]["operation_id"],
                        "process_kind": "m0_inprocess_proposer_terminal"}
                       for row in self.store.read("m0_proposal_outcome")
                       if row["payload"].get("execution_ref") == execution_ref
                       and row["payload"].get("status") != "ok")
        records.extend({"execution_id": row["payload"]["execution_id"],
                        "candidate_id": row["payload"]["candidate_id"],
                        "process_kind": "m0_inprocess_evaluator_terminal"}
                       for row in self.store.read("m0_evaluation_outcome")
                       if row["payload"].get("execution_ref") == execution_ref)
        return records

    def outcome(self, candidate_id: str) -> M0NativeOutcome:
        """Return the same-process M0 payload; batch recovery requires native M7 evidence."""
        try:
            return self._outcomes[candidate_id]
        except KeyError as error:
            raise RuntimeError(f"M0 native outcome is unavailable: {candidate_id}") from error

    @staticmethod
    def _failure(candidate_id: str, status: EvalStatus, detail: str,
                 token_cost: int, elapsed: float, fidelity: str) -> EvidenceRecord:
        executor_status = {EvalStatus.INVALID: "invalid", EvalStatus.TIMEOUT: "timeout"}.get(
            status, "failed_to_run")
        result = EvalResult(status, fidelity=fidelity, text_feedback=detail,
                            cost=CostVec(wall_seconds=elapsed, tokens_in=token_cost))
        return EvidenceRecord(candidate_id, result, executor_status=executor_status,
                              result_text=detail)

    def _recover_inprocess_inflight(self, execution_ref: str):
        """Adopt durable batch evaluator outcomes; execute only never-started operations."""
        cohorts = [row["payload"] for row in self.store.read(
            "batch_cycle_started") if row["payload"].get("cohort_id") == execution_ref]
        if len(cohorts) != 1:
            raise RuntimeError("M0 recovery requires exactly one cohort journal")
        cohort = cohorts[0]
        ids = cohort["candidate_ids"]
        candidates = {payload["id"]: Candidate(**payload)
                      for payload in cohort["candidates"]}
        prior = {row["payload"]["candidate_id"]: row["payload"]["evidence"]
                 for row in self.store.read("batch_execution_settled")
                 if row["payload"].get("cohort_id") == execution_ref}
        contexts, continued_proposals, adopted_proposals = self._recover_proposals(
            cohort, [], prior)
        failed = {candidate_id: self._validate_proposal_failure(candidate_id, execution_ref)
                  for candidate_id in ids if candidate_id not in contexts}
        state = inprocess_evaluation_operation_state(
            self.store, execution_ref, contexts, failed_ids=failed)
        missing = state["missing"]
        if missing and prior:
            raise RuntimeError("partially started cohort cannot have batch settlement")
        adopted_count = len(state["operations"])
        spec = ExecutorSpec(role="m0_prompt", execution_ref=execution_ref)
        for candidate_id in missing:
            asyncio.run(self.execute(
                spec, candidates[candidate_id], None, EvalRequest("dev")))
        state = inprocess_evaluation_operation_state(
            self.store, execution_ref, contexts, failed_ids=failed)
        operations, outcomes = state["operations"], state["outcomes"]
        if set(operations) | set(failed) != set(ids) \
                or len(operations) + len(failed) != len(ids) \
                or set(outcomes) != set(operations):
            raise RuntimeError("M0 recovery could not complete the original cohort executions")
        if execution_ref not in self._recovery_reports:
            self._recovery_reports[execution_ref] = {
                "adopted_process_count": 0,
                "continued_process_count": 0,
                "continued_candidate_ids": [],
                "adopted_inprocess_evaluation_count": adopted_count,
                "continued_inprocess_evaluation_count": len(missing),
                "continued_inprocess_evaluation_ids": missing,
                "continued_proposal_count": len(continued_proposals),
                "continued_proposal_ids": continued_proposals,
                "adopted_proposal_count": len(adopted_proposals),
                "adopted_proposal_ids": adopted_proposals,
                "new_proposal_count": len(continued_proposals) - len(adopted_proposals),
                "recovered_proposal_failure_count": len(failed),
                "recovered_proposal_failure_ids": list(failed)}
        recovered = []

        def persist(candidate_id, evidence, execution_id):
            if candidate_id in prior and prior[candidate_id] != asdict(evidence):
                raise RuntimeError("recovered in-process outcome differs from settled evidence")
            payload = {"evidence": asdict(evidence),
                       "outcome": evidence.eval_result.status.value,
                       "detail": evidence.result_text, "execution_id": execution_id}
            existing = [row["payload"] for row in self.store.read(
                "executor_evidence") if row["payload"].get("execution_id") == execution_id]
            if not existing:
                self.store.append("executor_evidence", payload)
            elif len(existing) != 1 or existing[0] != payload:
                raise RuntimeError("duplicate or mismatched recovered in-process executor evidence")
            recovered.append(evidence)

        for candidate_id, outcome in failed.items():
            error, proposer_cost = self._prepare_errors[candidate_id]
            token_cost = proposer_cost or self.fallback_token_cost
            evidence = self._failure(candidate_id, error.status, str(error),
                                     token_cost, 0.0, "dev")
            persist(candidate_id, evidence, outcome["execution_id"])
            self._outcomes[candidate_id] = M0NativeOutcome(None, None)
        for candidate_id in ids:
            if candidate_id not in operations:
                continue
            context = contexts[candidate_id]
            outcome = outcomes[candidate_id]
            proposal = VariationProposal(**context["proposal"])
            execution_id = operations[candidate_id]["execution_id"]
            if outcome["status"] == "ok":
                result = _restore_m0_result(outcome["result"])
                error = None
            else:
                result = None
                status = {"timeout": EvalStatus.TIMEOUT,
                          "invalid": EvalStatus.INVALID}.get(
                              outcome["status"], EvalStatus.FAILED_TO_RUN)
                error = ExternalEvaluatorError(status, outcome["detail"], execution_id)
            token_cost = context["proposer_token_cost"] + \
                outcome["token_usage"]["total_tokens"]
            token_cost = token_cost or self.fallback_token_cost
            if error is not None:
                evidence = self._failure(candidate_id, error.status, str(error),
                                         token_cost, 0.0, "dev")
            else:
                evidence_result = EvalResult(
                    EvalStatus.OK, {"dev/score": float(result.combined_score)},
                    cost=CostVec(wall_seconds=0.0, tokens_in=token_cost), fidelity="dev",
                    text_feedback=result.text_feedback)
                evidence = EvidenceRecord(candidate_id, evidence_result,
                                          executor_status="scored",
                                          result_text=result.text_feedback)
            persist(candidate_id, evidence, execution_id)
            self._outcomes[candidate_id] = M0NativeOutcome(proposal, result)
        return recovered

    def recover_inflight(self, workspace=None, execution_ref: str | None = None):
        """Adopt started outcomes and continue only never-started prepared candidates."""
        del workspace
        if execution_ref is None:
            raise RuntimeError("M0 recovery requires a cohort identity")
        if not isinstance(self.evaluator, ExternalCommandEvaluator):
            return self._recover_inprocess_inflight(execution_ref)
        cohorts = [row["payload"] for row in self.store.read(
            "batch_cycle_started") if row["payload"].get("cohort_id") == execution_ref]
        if len(cohorts) != 1:
            raise RuntimeError("M0 recovery requires exactly one cohort journal")
        cohort = cohorts[0]
        ids = cohort["candidate_ids"]
        candidates = {payload["id"]: Candidate(**payload)
                      for payload in cohort["candidates"]}

        def cohort_records():
            return [record for record in self.evaluator.processes.started()
                    if record.get("process_kind", "m0_external_evaluator")
                    == "m0_external_evaluator"
                    and record.get("execution_ref") == execution_ref]

        records = cohort_records()
        if len({record["candidate_id"] for record in records}) != len(records) \
                or not {record["candidate_id"] for record in records}.issubset(ids):
            raise RuntimeError("duplicate or foreign M0 cohort process journal")
        by_candidate = {record["candidate_id"]: record for record in records}
        prior = {row["payload"]["candidate_id"]: row["payload"]["evidence"]
                 for row in self.store.read("batch_execution_settled")
                 if row["payload"].get("cohort_id") == execution_ref}
        contexts, continued_proposals, adopted_proposals = self._recover_proposals(
            cohort, records, prior)
        failed = {candidate_id: self._validate_proposal_failure(candidate_id, execution_ref)
                  for candidate_id in ids if candidate_id not in contexts}
        for candidate_id, record in by_candidate.items():
            if candidate_id not in contexts \
                    or record.get("evaluation_context") != contexts[candidate_id]:
                raise RuntimeError("external M0 cohort recovery context mismatch")
        missing = [candidate_id for candidate_id in contexts
                   if candidate_id not in by_candidate]
        if missing and prior:
            raise RuntimeError("partially started cohort cannot have batch settlement")
        adopted_count = len(by_candidate)
        self.evaluator.recover_inflight(wait=True)
        recovered = []
        for candidate_id, outcome in failed.items():
            error, proposer_cost = self._prepare_errors[candidate_id]
            token_cost = proposer_cost or self.fallback_token_cost
            evidence = self._failure(candidate_id, error.status, str(error),
                                     token_cost, 0.0, "dev")
            if candidate_id in prior and prior[candidate_id] != asdict(evidence):
                raise RuntimeError("recovered proposal failure differs from settled evidence")
            execution_id = outcome["execution_id"]
            existing = [row["payload"] for row in self.store.read(
                "executor_evidence") if row["payload"].get("execution_id") == execution_id]
            payload = {"evidence": asdict(evidence),
                       "outcome": evidence.eval_result.status.value,
                       "detail": evidence.result_text, "execution_id": execution_id}
            if not existing:
                self.store.append("executor_evidence", payload)
            elif len(existing) != 1 or existing[0] != payload:
                raise RuntimeError("duplicate or mismatched recovered proposal failure evidence")
            self._outcomes[candidate_id] = M0NativeOutcome(None, None)
            recovered.append(evidence)
        for candidate_id in missing:
            asyncio.run(self.execute(
                ExecutorSpec(role="m0_prompt", execution_ref=execution_ref),
                candidates[candidate_id], None, EvalRequest("dev")))
        records = cohort_records()
        if {record["candidate_id"] for record in records} | set(failed) != set(ids) \
                or len(records) + len(failed) != len(ids):
            raise RuntimeError("M0 recovery could not complete the original cohort executions")
        if execution_ref not in self._recovery_reports:
            self._recovery_reports[execution_ref] = {
                "adopted_process_count": adopted_count,
                "continued_process_count": len(missing),
                "continued_candidate_ids": missing,
                "continued_proposal_count": len(continued_proposals),
                "continued_proposal_ids": continued_proposals,
                "adopted_proposal_count": len(adopted_proposals),
                "adopted_proposal_ids": adopted_proposals,
                "new_proposal_count": len(continued_proposals) - len(adopted_proposals),
                "recovered_proposal_failure_count": len(failed),
                "recovered_proposal_failure_ids": list(failed)}
        for record in records:
            candidate_id = record["candidate_id"]
            adopted = self.evaluator.outcome(record)
            context = contexts[candidate_id]
            proposal = VariationProposal(**context["proposal"])
            result = adopted["result"]
            error = adopted["error"]
            token_cost = context.get("proposer_token_cost", 0) + (
                (adopted["token_usage"] or {}).get("total_tokens", 0))
            token_cost = token_cost or self.fallback_token_cost
            if candidate_id in prior:
                from core.orchestration import _evidence_from_payload
                evidence = _evidence_from_payload(prior[candidate_id])
            elif error is not None:
                evidence = self._failure(candidate_id, error.status, str(error),
                                         token_cost, 0.0, "dev")
            else:
                evidence_result = EvalResult(
                    EvalStatus.OK, {"dev/score": float(result.combined_score)},
                    cost=CostVec(wall_seconds=0.0, tokens_in=token_cost), fidelity="dev",
                    text_feedback=result.text_feedback)
                evidence = EvidenceRecord(candidate_id, evidence_result,
                                          executor_status="scored",
                                          result_text=result.text_feedback)
            existing = [row["payload"] for row in self.store.read(
                "executor_evidence") if row["payload"].get("execution_id")
                == record["execution_id"]]
            if not existing:
                self.store.append("executor_evidence", {
                    "evidence": asdict(evidence), "outcome": evidence.eval_result.status.value,
                    "detail": evidence.result_text, "execution_id": record["execution_id"]})
            elif len(existing) != 1 or existing[0]["evidence"] != asdict(evidence):
                raise RuntimeError("duplicate or mismatched recovered M0 executor evidence")
            self._outcomes[candidate_id] = M0NativeOutcome(proposal, result)
            recovered.append(evidence)
        return recovered

    async def execute(self, spec: ExecutorSpec, candidate: Candidate, workspace,
                      request: EvalRequest) -> EvidenceRecord:
        del workspace  # M0 operations are closed over immutable proposal inputs.
        started = time.monotonic()
        proposal = None
        result = None
        failure = None
        failure_from_proposal = False
        proposal_phase = True
        proposer_cost = 0
        evaluation_operation = None
        with self._meter_lock:
            take_usage(self.llm)
            take_usage(self.evaluator)
            try:
                prepared = self._prepared.get(candidate.id)
                if prepared is not None:
                    proposal = VariationProposal(**prepared["proposal"])
                    proposer_cost = prepared["proposer_token_cost"]
                    head_sha = prepared["head_sha"]
                elif candidate.id in self._prepare_errors:
                    error, proposer_cost = self._prepare_errors[candidate.id]
                    raise error
                else:
                    proposal = self.operations[candidate.id]()
                    proposer_cost = take_usage(self.llm)
                    head_sha = hashlib.sha256(
                        f"{proposal.proposal_id}\0{proposal.patch_text}".encode()
                    ).hexdigest()[:8]
                if proposal.apply_result not in ("ok", "retry_ok"):
                    failure = (EvalStatus.INVALID,
                               f"deterministic apply failed: {proposal.apply_result}")
                else:
                    proposal_phase = False
                    external = isinstance(self.evaluator, ExternalCommandEvaluator)
                    if external:
                        if prepared is None:
                            cohorts = [row["payload"] for row in
                                       self.store.read("batch_cycle_started")
                                       if row["payload"].get("cohort_id") == spec.execution_ref]
                            if len(cohorts) != 1:
                                raise RuntimeError("external M0 batch lacks its cohort journal")
                            intents = [payload for payload in cohorts[0].get("intents", [])
                                       if payload.get("candidate_ref") == candidate.id]
                            if len(intents) != 1:
                                raise RuntimeError("external M0 batch lacks its candidate intent")
                            prepared = {"cohort_id": spec.execution_ref,
                                        "generation": candidate.created_cycle,
                                        "operator": candidate.operator, "intent": intents[0],
                                        "proposal": asdict(proposal), "head_sha": head_sha,
                                        "proposer_token_cost": proposer_cost}
                            self.store.append(
                                "m0_evaluation_started", prepared)
                        self.evaluator.set_evaluation_context(prepared)
                    else:
                        if prepared is None:
                            raise RuntimeError("in-process M0 batch lacks its prepared context")
                        evaluation_operation = _batch_evaluation_operation(prepared)
                        self.store.append("m0_batch_evaluation_started", evaluation_operation)
                    try:
                        result = self.evaluator(candidate.id, head_sha, proposal.patch_text)
                    finally:
                        if external:
                            self.evaluator.clear_evaluation_context()
                    if not isinstance(result, M0EvalResult) \
                            or result.candidate_id != candidate.id:
                        raise ValueError("M0 evaluator returned a mismatched result")
            except ExternalProposalError as error:
                result = None
                failure = (error.status, str(error))
                failure_from_proposal = True
            except ExternalEvaluatorError as error:
                result = None
                failure = (error.status, str(error))
            except Exception as error:
                result = None
                failure = (EvalStatus.FAILED_TO_RUN,
                           f"{type(error).__name__}: {error}"[-4000:])
                failure_from_proposal = proposal_phase
            metered = proposer_cost + take_usage(self.llm) + take_usage(self.evaluator)
            token_cost = metered or self.fallback_token_cost
            if evaluation_operation is not None:
                status = EvalStatus.OK if failure is None else failure[0]
                self.store.append("m0_evaluation_outcome", {
                    "schema_version": 1, "adapter": "in_process",
                    "execution_id": evaluation_operation["execution_id"],
                    "execution_ref": spec.execution_ref, "candidate_id": candidate.id,
                    "generation": candidate.created_cycle, "operator": candidate.operator,
                    "start_sha256": _marker_sha256(evaluation_operation),
                    "evaluation_sha256": _marker_sha256(prepared),
                    "status": status.value,
                    "detail": "in-process batch evaluation completed" if failure is None
                    else failure[1],
                    "result": asdict(result) if failure is None else None,
                    "token_usage": {"total_tokens": metered - proposer_cost}})
            self._outcomes[candidate.id] = M0NativeOutcome(proposal, result)
        elapsed = time.monotonic() - started
        if failure is not None:
            # Durable terminal operations reconstruct with zero diagnostic elapsed time.
            evidence_elapsed = 0.0 if failure_from_proposal \
                or evaluation_operation is not None else elapsed
            return self._failure(candidate.id, failure[0], failure[1],
                                 token_cost, evidence_elapsed, request.fidelity)
        evidence_result = EvalResult(
            EvalStatus.OK, {"dev/score": float(result.combined_score)},
            cost=CostVec(wall_seconds=0.0 if evaluation_operation is not None else elapsed,
                         tokens_in=token_cost),
            fidelity=request.fidelity, text_feedback=result.text_feedback)
        return EvidenceRecord(candidate.id, evidence_result, executor_status="scored",
                              result_text=result.text_feedback)
