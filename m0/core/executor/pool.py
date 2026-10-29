"""Bounded M7 execution with deterministic, serial result finalization."""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from core.executor.types import (Candidate, CostVec, EvalRequest, EvalResult,
                                 EvalStatus, EvidenceRecord, ExecutorSpec)
from core.x1.store import AppendOnlyStore
from core.llm import UsageError

ResultCallback = Callable[[Candidate, EvidenceRecord], object]


class ExecutorPool:
    """Run blocking M7 executors under a fixed evaluator-resource quota.

    Worker execution is parallel. Optional result callbacks run one at a time in
    candidate input order, after execution, so M1.absorb/StateApplier stay serial.
    This class does not recover externally running processes after a crash.
    """

    def __init__(self, backend, max_inflight: int,
                 evidence_store: AppendOnlyStore | None = None):
        if isinstance(max_inflight, bool) or not isinstance(max_inflight, int) \
                or max_inflight < 1:
            raise ValueError("max_inflight must be a positive integer")
        self.backend = backend
        self.max_inflight = max_inflight
        self.evidence_store = evidence_store
        self._threads = ThreadPoolExecutor(max_workers=max_inflight,
                                           thread_name_prefix="m7-executor")
        self._state_lock = threading.RLock()
        self._callback_lock = asyncio.Lock()
        self._queued: set[str] = set()
        self._inflight: set[str] = set()
        self._finalizing = 0
        self._attempts: dict[str, int] = {}
        self._closed = False

    def _emit(self, kind: str, payload: dict) -> None:
        if self.evidence_store is not None:
            self.evidence_store.append(kind, payload)

    @property
    def inflight_state(self) -> dict:
        with self._state_lock:
            return {"queued": sorted(self._queued),
                    "running": sorted(self._inflight),
                    "finalizing": self._finalizing}

    def checkpoint_state(self) -> dict:
        """Only a quiescent cycle boundary is checkpointable in this version."""
        with self._state_lock:
            if self._queued or self._inflight or self._finalizing:
                raise RuntimeError(
                    "ExecutorPool checkpoint requires empty queued/running/finalizing state")
            return {"schema_version": 1, "inflight_executor": [],
                    "queued": [], "finalizing": 0}

    def _register(self, candidates: list[Candidate]) -> None:
        ids = [candidate.id for candidate in candidates]
        if any(not candidate_id for candidate_id in ids):
            raise ValueError("ExecutorPool candidates require non-empty ids")
        if len(set(ids)) != len(ids):
            raise ValueError("ExecutorPool batch contains duplicate candidate ids")
        with self._state_lock:
            if self._closed:
                raise RuntimeError("ExecutorPool is closed")
            conflicts = set(ids).intersection(self._queued | self._inflight)
            if conflicts:
                raise ValueError("candidates already queued or running: "
                                 + ", ".join(sorted(conflicts)))
            for candidate_id in ids:
                self._queued.add(candidate_id)
                self._emit("executor_pool_queued", {"candidate_id": candidate_id})

    def _invoke(self, spec: ExecutorSpec, candidate: Candidate, workspace,
                request: EvalRequest) -> EvidenceRecord:
        with self._state_lock:
            self._queued.remove(candidate.id)
            self._inflight.add(candidate.id)
            attempt = self._attempts.get(candidate.id, 0) + 1
            self._attempts[candidate.id] = attempt
            self._emit("executor_pool_started",
                       {"candidate_id": candidate.id, "attempt": attempt})
        started = time.monotonic()
        try:
            evidence = asyncio.run(self.backend.execute(spec, candidate, workspace, request))
            if not isinstance(evidence, EvidenceRecord) \
                    or evidence.candidate_id != candidate.id:
                raise TypeError("executor must return matching EvidenceRecord")
        except UsageError:
            # Unknown token cost must retain the reserve for reconciliation.
            # Converting this to ordinary failed evidence would invent cost=0.
            raise
        except Exception as exc:
            detail = f"ExecutorPool {type(exc).__name__}: {exc}"[-4000:]
            result = EvalResult(EvalStatus.FAILED_TO_RUN,
                                cost=CostVec(time.monotonic() - started),
                                fidelity=request.fidelity, text_feedback=detail)
            evidence = EvidenceRecord(candidate.id, result, executor_status="failed_to_run",
                                      attempt=attempt, result_text=detail)
            with self._state_lock:
                self._emit("executor_pool_failure", {
                    "candidate_id": candidate.id, "attempt": attempt, "error": detail})
        finally:
            with self._state_lock:
                self._inflight.remove(candidate.id)
                self._emit("executor_pool_finished", {
                    "candidate_id": candidate.id, "attempt": attempt,
                    "status": evidence.eval_result.status.value
                    if "evidence" in locals() else "failed_to_run"})
        return evidence

    async def _dispatch(self, spec: ExecutorSpec, candidate: Candidate, workspace,
                        request: EvalRequest) -> EvidenceRecord:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._threads, self._invoke, spec, candidate, workspace, request)

    async def run(self, spec: ExecutorSpec, candidate: Candidate, workspace,
                  request: EvalRequest) -> EvidenceRecord:
        """SPEC single-candidate entry point with exactly one returned evidence."""
        self._register([candidate])
        return await self._dispatch(spec, candidate, workspace, request)

    async def run_many(self, specs: list[ExecutorSpec], candidates: list[Candidate],
                       workspace, requests: list[EvalRequest],
                       on_result: ResultCallback | None = None) -> list[EvidenceRecord]:
        """Execute a batch, then finalize results serially in input order."""
        if not (len(specs) == len(candidates) == len(requests)):
            raise ValueError("specs, candidates and requests must have equal lengths")
        if not candidates:
            return []
        self._register(candidates)
        results = await asyncio.gather(*(
            self._dispatch(spec, candidate, workspace, request)
            for spec, candidate, request in zip(specs, candidates, requests)),
            return_exceptions=True)
        # Drain every submitted worker before unwinding. Otherwise close() can
        # mask an unknown-cost failure while another paid call is still running.
        for result in results:
            if isinstance(result, BaseException):
                raise result
        if on_result is not None:
            async with self._callback_lock:
                with self._state_lock:
                    self._finalizing += 1
                try:
                    for candidate, evidence in zip(candidates, results):
                        returned = on_result(candidate, evidence)
                        if inspect.isawaitable(returned):
                            await returned
                        with self._state_lock:
                            self._emit("executor_pool_absorbed", {
                                "candidate_id": candidate.id,
                                "status": evidence.eval_result.status.value})
                finally:
                    with self._state_lock:
                        self._finalizing -= 1
        return results

    def close(self) -> None:
        with self._state_lock:
            self.checkpoint_state()
            self._closed = True
        self._threads.shutdown(wait=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
