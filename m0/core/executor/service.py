"""M7 git-worktree executor: one Candidate in, exactly one EvidenceRecord out."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from core.executor.process import ProcessJournal
from core.executor.types import (Candidate, CostVec, EvalRequest, EvalResult,
                                 EvalStatus, EvidenceRecord, ExecutorSpec)
from core.executor.workspace import (GitWorktree, protected_manifest, safe_relative,
                                     verify_manifest)
from core.tasks.adapter import EvalContract
from core.x1.store import AppendOnlyStore

CandidateBuilder = Callable[[Candidate, Path], None]


def _tail(text: str | None, limit: int = 4000) -> str:
    return (text or "")[-limit:]


def _evidence_json(evidence: EvidenceRecord) -> dict:
    payload = asdict(evidence)
    payload["eval_result"]["status"] = evidence.eval_result.status.value
    return payload


class GitWorktreeExecutor:
    """Execute through an injected candidate builder and the task's eval_cmd.

    git worktree is an artifact/isolation backend, not a security sandbox.  A
    container backend is required for untrusted code or credential isolation.
    """

    def __init__(self, contract: EvalContract, builder: CandidateBuilder,
                 evidence_store: AppendOnlyStore, data_dir: str | Path | None = None,
                 hitl=None, sandbox=None):
        self.contract = contract
        self.builder = builder
        self.evidence_store = evidence_store
        self.data_dir = str(data_dir) if data_dir is not None else ""
        self.hitl = hitl
        self.sandbox = sandbox
        self._attempts: dict[str, int] = {}
        self._trusted_manifests: dict[str, dict[str, str]] = {}
        self._lock = threading.RLock()
        self.processes = ProcessJournal(evidence_store)

    async def execute(self, spec: ExecutorSpec, cand: Candidate,
                      workspace: GitWorktree, request: EvalRequest) -> EvidenceRecord:
        with self._lock:
            attempt = self._attempts.get(cand.id, 0) + 1
            self._attempts[cand.id] = attempt
        worktree_ref = None
        started = time.monotonic()
        try:
            cand.validate()
            request.validate()
            levels = {level.name for level in self.contract.fidelity_levels}
            if request.fidelity not in levels:
                raise ValueError(f"undeclared fidelity: {request.fidelity}")
            if spec.hypothesis_frozen and spec.hypothesis is not None \
                    and cand.hypothesis != spec.hypothesis:
                raise ValueError("candidate hypothesis differs from frozen ExecutorSpec")
            if self.hitl is not None:
                with self._lock:
                    decision = self.hitl.authorize("executor.execute", {
                        "candidate_id": cand.id, "fidelity": request.fidelity,
                        "seed_set": request.seed_set, "resume_from": request.resume_from})
                if not decision.allowed:
                    return self._finish(workspace, worktree_ref, EvidenceRecord(
                        cand.id, self._result(EvalStatus.FAILED_TO_RUN, request, started,
                                              decision.reason),
                        executor_status="skipped", attempt=attempt,
                        result_text=decision.reason), "hitl", decision.request_id)

            base_key = str(workspace.base_repo)
            base_manifest = protected_manifest(workspace.base_repo,
                                               self.contract.protected_paths)
            with self._lock:
                trusted = self._trusted_manifests.setdefault(base_key, base_manifest)
            verify_manifest(workspace.base_repo, trusted, self.contract.protected_paths)
            worktree_ref = workspace.fork(request.resume_from or "HEAD")
            root = workspace.path_for(worktree_ref)
            protected = workspace.manifest(worktree_ref, self.contract.protected_paths)
            verify_manifest(root, trusted, self.contract.protected_paths)
            self.evidence_store.append("executor_protected_check", {
                "candidate_id": cand.id, "attempt": attempt, "stage": "startup",
                "passed": True, "manifest_sha256": self._manifest_digest(protected)})

            self.builder(cand, root)
            completed = self._run_command(root, request, cand, spec, attempt,
                                          worktree_ref, protected)
            return self._complete_process(completed["process_record"], completed, workspace)
        except Exception as exc:
            branch = None
            if worktree_ref is not None:
                branch = self._safe_commit(workspace, worktree_ref, cand.id)
            detail = f"{type(exc).__name__}: {exc}"[-4000:]
            result = self._result(EvalStatus.FAILED_TO_RUN, request, started, detail)
            evidence = EvidenceRecord(cand.id, result, branch, "failed_to_run", attempt,
                                      result_text=detail)
            return self._finish(workspace, worktree_ref, evidence, "failed_to_run",
                                time.monotonic() - started)

    def _run_command(self, root: Path, request: EvalRequest, cand: Candidate,
                     spec: ExecutorSpec, attempt: int, worktree_ref: str,
                     protected: dict) -> dict:
        command = self.contract.eval_cmd.format(cwd=str(root), data_dir=self.data_dir)
        args = shlex.split(command)
        if not args:
            raise ValueError("eval_cmd is empty")
        env = dict(os.environ)
        env.update({"AR_FIDELITY": request.fidelity,
                    "AR_BUDGET_TOKEN": str(request.budget_token or ""),
                    "AR_SEED_SET": json.dumps(request.seed_set or [])})
        seccomp_policy = None
        if self.sandbox is not None:
            args = self.sandbox.wrap(args, root, self.contract.protected_paths,
                                     self.data_dir, env)
            policy_factory = getattr(self.sandbox, "seccomp_spec", None)
            if callable(policy_factory):
                seccomp_policy = policy_factory()
        proc, record = self.processes.launch(
            args, root, env, request.time_limit,
            {"candidate_id": cand.id, "candidate": asdict(cand),
             "request": asdict(request), "attempt": attempt,
             "execution_ref": spec.execution_ref,
             "worktree_ref": worktree_ref, "root": str(root),
             "protected": protected, "started_wall": time.time()},
            seccomp_policy=seccomp_policy)
        completed = self.processes.wait(proc, record)
        completed["process_record"] = record
        return completed

    @staticmethod
    def _process_context(record: dict) -> tuple[Candidate, EvalRequest]:
        candidate = Candidate(**record["candidate"])
        request = EvalRequest(**record["request"])
        candidate.validate()
        request.validate()
        return candidate, request

    def _complete_process(self, record: dict, completed: dict,
                          workspace: GitWorktree) -> EvidenceRecord:
        """Shared normal/recovery finalization; the process result is already durable."""
        cand, request = self._process_context(record)
        worktree_ref = record["worktree_ref"]
        root = workspace.path_for(worktree_ref)
        protected = record["protected"]
        elapsed = max(0.0, time.time() - record["started_wall"])
        started = time.monotonic() - elapsed
        attempt = record["attempt"]
        execution_id = record["execution_id"]
        if completed["timeout"]:
            branch = self._safe_commit(workspace, worktree_ref, cand.id)
            result = self._result(EvalStatus.TIMEOUT, request, started,
                                  "evaluation exceeded time_limit")
            return self._finish(workspace, worktree_ref, EvidenceRecord(
                cand.id, result, branch, "timeout", attempt,
                result_text="evaluation exceeded time_limit"), "timeout", elapsed,
                execution_id)
        if completed["returncode"] != 0:
            branch = self._safe_commit(workspace, worktree_ref, cand.id)
            detail = _tail(completed["stderr"] or completed["stdout"]
                           or completed.get("wrapper_error"))
            result = self._result(EvalStatus.FAILED_TO_RUN, request, started, detail)
            return self._finish(workspace, worktree_ref, EvidenceRecord(
                cand.id, result, branch, "failed_to_run", attempt,
                result_text=detail or "evaluation command failed"),
                "failed_to_run", elapsed, execution_id)

        missing = [relative for relative in self.contract.required_outputs
                   if not safe_relative(root, relative).is_file()]
        if missing:
            branch = self._safe_commit(workspace, worktree_ref, cand.id)
            detail = "required outputs missing: " + ", ".join(missing)
            result = self._result(EvalStatus.INVALID, request, started, detail)
            return self._finish(workspace, worktree_ref, EvidenceRecord(
                cand.id, result, branch, "invalid", attempt, result_text=detail),
                "invalid", elapsed, execution_id)

        try:
            verify_manifest(root, protected, self.contract.protected_paths)
        except ValueError as exc:
            self.evidence_store.append("executor_protected_check", {
                "candidate_id": cand.id, "attempt": attempt, "stage": "pre_merge",
                "passed": False, "error": str(exc)})
            branch = self._safe_commit(workspace, worktree_ref, cand.id)
            result = self._result(EvalStatus.INVALID, request, started, str(exc))
            return self._finish(workspace, worktree_ref, EvidenceRecord(
                cand.id, result, branch, "invalid", attempt, result_text=str(exc)),
                "protected_premerge_failed", elapsed, execution_id)
        self.evidence_store.append("executor_protected_check", {
            "candidate_id": cand.id, "attempt": attempt, "stage": "pre_merge",
            "passed": True, "manifest_sha256": self._manifest_digest(protected)})

        metrics = self._metrics(root)
        branch = workspace.commit(worktree_ref, f"evaluate {cand.id}",
                                  self.contract.required_outputs)
        feedback = _tail(completed["stdout"])
        result = EvalResult(EvalStatus.OK, metrics, CostVec(elapsed),
                            request.fidelity, text_feedback=feedback,
                            artifacts_ref=branch)
        evidence = EvidenceRecord(cand.id, result, branch, "scored", attempt,
                                  result_text=feedback or "evaluation completed")
        return self._finish(workspace, worktree_ref, evidence, "scored", elapsed,
                            execution_id)

    def recover_inflight(self, workspace: GitWorktree,
                         execution_ref: str | None = None) -> list[EvidenceRecord]:
        """Reconcile detached attempts after owner crash; pending attempts stay pending."""
        recovered = []
        with self._lock:
            finalized = {record["payload"].get("execution_id")
                         for record in self.evidence_store.read("executor_evidence")}
            finished_ids = self.processes.finished_ids()
            for record in self.processes.started(execution_ref):
                execution_id = record["execution_id"]
                if execution_id in finalized:
                    continue
                cand, request = self._process_context(record)
                if execution_id in finished_ids:
                    try:
                        state = {"status": "finished",
                                 **self.processes.completed_result(record)}
                    except (OSError, ValueError, UnicodeError) as exc:
                        self.processes.terminate_target(record)
                        state = {"status": "lost", "execution_id": execution_id,
                                 "detail": f"invalid durable process result: {exc}"}
                else:
                    state = self.processes.recover(record)
                if state["status"] == "pending":
                    continue
                worktree_ref = record["worktree_ref"]
                try:
                    workspace.adopt(worktree_ref, record["root"])
                    verify_manifest(workspace.base_repo, record["protected"],
                                    self.contract.protected_paths)
                    if state["status"] == "finished":
                        evidence = self._complete_process(record, state, workspace)
                    else:
                        detail = state["detail"]
                        self.processes.fail(record, detail)
                        elapsed = max(0.0, time.time() - record["started_wall"])
                        branch = self._safe_commit(workspace, worktree_ref, cand.id)
                        result = EvalResult(EvalStatus.FAILED_TO_RUN,
                                            cost=CostVec(elapsed), fidelity=request.fidelity,
                                            text_feedback=detail)
                        evidence = self._finish(workspace, worktree_ref, EvidenceRecord(
                            cand.id, result, branch, "failed_to_run", record["attempt"],
                            result_text=detail), "failed_to_run", elapsed, execution_id)
                except Exception as exc:
                    detail = f"recovery failed closed: {type(exc).__name__}: {exc}"[-4000:]
                    if state["status"] == "lost" and execution_id not in finished_ids:
                        self.processes.fail(record, detail)
                    elapsed = max(0.0, time.time() - record["started_wall"])
                    result = EvalResult(EvalStatus.FAILED_TO_RUN, cost=CostVec(elapsed),
                                        fidelity=request.fidelity, text_feedback=detail)
                    evidence = self._finish(workspace, None, EvidenceRecord(
                        cand.id, result, worktree_ref, "failed_to_run", record["attempt"],
                        result_text=detail), "recovery_failed", elapsed, execution_id)
                recovered.append(evidence)
        return recovered

    @staticmethod
    def _metrics(root: Path) -> dict[str, float]:
        path = root / "metrics.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("metrics.json must contain an object")
        metrics = {}
        for key, value in payload.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                raise ValueError("metrics must be finite numbers")
            metrics[str(key)] = float(value)
        return metrics

    @staticmethod
    def _result(status: EvalStatus, request: EvalRequest,
                started: float, feedback: str) -> EvalResult:
        return EvalResult(status=status, fidelity=request.fidelity,
                          cost=CostVec(time.monotonic() - started),
                          text_feedback=_tail(feedback))

    @staticmethod
    def _manifest_digest(manifest: dict[str, str]) -> str:
        return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _safe_commit(workspace: GitWorktree, ref: str, candidate_id: str) -> str | None:
        try:
            return workspace.commit(ref, f"unfinished {candidate_id}")
        except Exception:
            return ref

    def _finish(self, workspace: GitWorktree, worktree_ref: str | None,
                evidence: EvidenceRecord, outcome: str, detail,
                execution_id: str | None = None) -> EvidenceRecord:
        self.evidence_store.append("executor_evidence", {
            "evidence": _evidence_json(evidence), "outcome": outcome,
            "detail": detail, "execution_id": execution_id})
        if worktree_ref is not None:
            try:
                workspace.destroy(worktree_ref)
            except Exception as exc:
                self.evidence_store.append("executor_cleanup_failure", {
                    "candidate_id": evidence.candidate_id, "error": str(exc)})
        return evidence
