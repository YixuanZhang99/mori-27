"""Explicit external M0 evaluator protocol with durable process/native outcomes.

The command receives ``request.json response.json`` and writes one versioned
EvalResult envelope. Framework v30/v31 adds bounded recovery for a started
sequential improve through admission before its cycle checkpoint. BubblewrapSandbox
is the fail-closed default; only an explicit None/False disables isolation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta, validate_eval_result
from core.executor.process import ProcessJournal
from core.executor.resources import ResourcePolicy
from core.executor.sandbox import BubblewrapSandbox
from core.executor.types import EvalStatus
from core.llm import reset_usage
from core.x1.store import AppendOnlyStore


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _digest(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) \
        and math.isfinite(value)


_DEFAULT_SANDBOX = object()


class ExternalEvaluatorError(RuntimeError):
    """Structured process/protocol failure consumable by M0 evidence adapters."""

    def __init__(self, status: EvalStatus, detail: str, execution_id: str | None = None):
        super().__init__(detail[-4000:])
        self.status = status
        self.execution_id = execution_id


class ExternalCommandEvaluator:
    """Callable M0 evaluator backed by one real subprocess per candidate.

    ``command`` is an argv prefix, never a shell string. The child gets exactly
    two appended arguments: request and response paths. Environment is inherited
    by the wrapper but never journaled; Bubblewrap clears it inside the sandbox.
    """

    def __init__(self, command: list[str], workdir: str | Path,
                 evidence_store: AppendOnlyStore, *, time_limit: int | None = 120,
                 sandbox=_DEFAULT_SANDBOX, data_dir: str | Path | None = None,
                 protected_paths=(), resource_policy: ResourcePolicy | None = None,
                 evaluation_context: str = ""):
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("external evaluator command must be a non-empty argv list")
        if isinstance(time_limit, bool) or not isinstance(time_limit, int) or time_limit <= 0:
            raise ValueError("external evaluator time_limit must be a positive integer")
        if not isinstance(evaluation_context, str) or (evaluation_context and
                not re.fullmatch(r"sha256:[0-9a-f]{64}", evaluation_context)):
            raise ValueError("evaluation_context must be empty or a canonical SHA-256 digest")
        self._result_context = evaluation_context
        self.command = list(command)
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.evidence_store = evidence_store
        self.time_limit = time_limit
        if sandbox is _DEFAULT_SANDBOX or sandbox is True:
            sandbox = BubblewrapSandbox()
        if sandbox is None or sandbox is False:
            self.sandbox = None
            self.sandbox_policy = "disabled"
        else:
            if not callable(getattr(sandbox, "wrap", None)):
                raise TypeError("external evaluator sandbox must provide wrap()")
            self.sandbox = sandbox
            self.sandbox_policy = type(sandbox).__name__
        self.data_dir = str(data_dir) if data_dir is not None else ""
        self.protected_paths = tuple(protected_paths)
        if resource_policy is not None and not isinstance(resource_policy, ResourcePolicy):
            raise TypeError("resource_policy must be ResourcePolicy or None")
        self.resource_policy = resource_policy
        self.resource_limits = resource_policy.as_dict() if resource_policy else {}
        self.processes = ProcessJournal(evidence_store)
        self.evaluation_root = self.workdir / "evaluations"
        self.last_usage = None
        self.last_execution_id: str | None = None
        self._evaluation_context: dict = {}

    @property
    def evaluation_context(self) -> str:
        """Pinned content identity; empty explicitly retains the legacy protocol."""
        return self._result_context

    def fork(self, workdir: str | Path, evidence_store: AppendOnlyStore):
        """Reuse command assets while binding replay to independent evidence."""
        clone = type(self)(self.command, self.workdir, evidence_store,
                           time_limit=self.time_limit, sandbox=self.sandbox,
                           data_dir=self.data_dir, protected_paths=self.protected_paths,
                           resource_policy=self.resource_policy,
                           evaluation_context=self.evaluation_context)
        namespace = hashlib.sha256(str(Path(workdir).resolve()).encode()).hexdigest()[:16]
        clone.evaluation_root = self.workdir / "evaluations" / namespace
        return clone

    def set_evaluation_context(self, context: dict) -> None:
        """Bind the next call to its already-proposed candidate and open intent."""
        if self._evaluation_context:
            raise RuntimeError("external evaluation context is already active")
        self._evaluation_context = dict(context)

    def clear_evaluation_context(self) -> None:
        self._evaluation_context = {}

    @staticmethod
    def _usage(payload) -> dict[str, int]:
        if not isinstance(payload, dict):
            raise ValueError("token_usage must be an object")
        if set(payload) != {"total_tokens"}:
            raise ValueError("token_usage requires exactly total_tokens")
        total = payload["total_tokens"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("total_tokens must be a non-negative integer")
        return {"total_tokens": total}

    @staticmethod
    def _result(payload, candidate_id: str, head_sha: str,
                evaluation_context: str | None = None) -> EvalResult:
        required = {"candidate_id", "head_sha", "items", "combined_score", "public",
                    "private", "text_feedback", "reliability", "evaluator_version"}
        if not isinstance(payload, dict) or not required <= set(payload) \
                or not set(payload) <= required | {"evaluation_context"}:
            raise ValueError("external result must contain the complete v1 EvalResult schema")
        if payload["candidate_id"] != candidate_id or payload["head_sha"] != head_sha:
            raise ValueError("external result candidate/head binding mismatch")
        if not _finite_number(payload["combined_score"]):
            raise ValueError("combined_score must be finite")
        if not isinstance(payload["public"], dict) or not isinstance(payload["private"], dict):
            raise ValueError("public/private must be objects")
        if not isinstance(payload["text_feedback"], str):
            raise ValueError("text_feedback must be a string")
        if not isinstance(payload["evaluator_version"], str) \
                or not payload["evaluator_version"]:
            raise ValueError("evaluator_version must be non-empty")
        raw_items = payload["items"]
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("items must be a non-empty list")
        items = []
        item_ids = set()
        for item in raw_items:
            if not isinstance(item, dict) or set(item) != {"item_id", "verdict"}:
                raise ValueError("each item requires exactly item_id and verdict")
            item_id, verdict = item["item_id"], item["verdict"]
            if not isinstance(item_id, str) or not item_id or item_id in item_ids \
                    or isinstance(verdict, bool) or verdict not in (0, 1):
                raise ValueError("item ids must be unique and verdicts binary")
            item_ids.add(item_id)
            items.append(ItemResult(item_id, verdict))
        reliability = payload["reliability"]
        if not isinstance(reliability, dict) \
                or set(reliability) != {"n_trials", "ci95", "noise_floor"}:
            raise ValueError("reliability must contain the complete v1 schema")
        trials = reliability["n_trials"]
        if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
            raise ValueError("n_trials must be a positive integer")
        ci95 = reliability["ci95"]
        if ci95 is not None and (not isinstance(ci95, list) or len(ci95) != 2
                                 or not all(_finite_number(value) for value in ci95)):
            raise ValueError("ci95 must be null or two finite numbers")
        noise_floor = reliability["noise_floor"]
        if noise_floor is not None and not _finite_number(noise_floor):
            raise ValueError("noise_floor must be null or finite")
        return validate_eval_result(EvalResult(
            candidate_id=candidate_id, head_sha=head_sha, items=items,
            combined_score=float(payload["combined_score"]),
            public=dict(payload["public"]), private=dict(payload["private"]),
            text_feedback=payload["text_feedback"],
            reliability=ReliabilityMeta(trials, tuple(ci95) if ci95 is not None else None,
                                        noise_floor),
            evaluator_version=payload["evaluator_version"],
            evaluation_context=payload.get("evaluation_context", "")),
            candidate_id=candidate_id, head_sha=head_sha,
            evaluation_context=evaluation_context)

    def _persist(self, record: dict, status: str, detail: str,
                 result: dict | None = None, usage: dict | None = None) -> None:
        request_path, response_path = Path(record["request_path"]), Path(record["response_path"])
        outcome_path = request_path.parent / "native-outcome.json"
        outcome = {"schema_version": 1, "execution_id": record["execution_id"],
                   "candidate_id": record["candidate_id"], "head_sha": record["head_sha"],
                   "status": status, "detail": detail[-4000:],
                   "request_sha256": _digest(request_path),
                   "response_sha256": _digest(response_path),
                   "result": result, "token_usage": usage}
        _atomic_json(outcome_path, outcome)
        self.evidence_store.append("external_evaluator_outcome", {
            **outcome, "outcome_path": str(outcome_path)})

    def _complete_process(self, record: dict, completed: dict) -> EvalResult:
        reset_usage(self)
        execution_id = record["execution_id"]
        usage = None
        try:
            envelope = json.loads(Path(record["response_path"]).read_text(encoding="utf-8"))
            if isinstance(envelope, dict) and envelope.get("schema_version") == 1:
                usage = self._usage(envelope.get("token_usage"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            envelope = None
        self.last_usage = usage
        if completed["timeout"]:
            detail = "external evaluator exceeded time_limit"
            self._persist(record, "timeout", detail, usage=usage)
            raise ExternalEvaluatorError(EvalStatus.TIMEOUT, detail, execution_id)
        if completed["returncode"] != 0:
            detail = (completed["stderr"] or completed["stdout"]
                      or completed.get("wrapper_error") or "external evaluator failed")
            self._persist(record, "failed_to_run", detail, usage=usage)
            raise ExternalEvaluatorError(EvalStatus.FAILED_TO_RUN, detail, execution_id)
        try:
            if not isinstance(envelope, dict) \
                    or set(envelope) != {"schema_version", "result", "token_usage"} \
                    or envelope["schema_version"] != 1:
                raise ValueError("external response must be a version-1 result envelope")
            result_payload = envelope["result"]
            result = self._result(result_payload, record["candidate_id"], record["head_sha"],
                                  evaluation_context=self.evaluation_context)
            usage = self._usage(envelope["token_usage"])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            detail = f"invalid external evaluator response: {error}"
            self._persist(record, "invalid", detail, usage=usage)
            raise ExternalEvaluatorError(EvalStatus.INVALID, detail, execution_id) from error
        self.last_usage = usage
        self._persist(record, "ok", "external evaluation completed", result_payload, usage)
        return result

    def outcome(self, record: dict) -> dict:
        """Load one persisted native outcome without executing its command again."""
        execution_id = record["execution_id"]
        rows = [row["payload"] for row in self.evidence_store.read(
            "external_evaluator_outcome") if row["payload"].get("execution_id") == execution_id]
        if len(rows) != 1:
            raise RuntimeError(f"external native outcome is not unique: {execution_id}")
        payload = rows[0]
        status = payload["status"]
        if status == "ok":
            result = self._result(payload["result"], record["candidate_id"], record["head_sha"],
                                  evaluation_context=self.evaluation_context)
            self._usage(payload["token_usage"])
            error = None
        else:
            result = None
            status_enum = {"timeout": EvalStatus.TIMEOUT, "invalid": EvalStatus.INVALID}.get(
                status, EvalStatus.FAILED_TO_RUN)
            error = ExternalEvaluatorError(status_enum, payload["detail"], execution_id)
        return {"record": record, "result": result, "error": error,
                "token_usage": payload["token_usage"]}

    def recover_inflight(self, wait: bool = True) -> list[dict]:
        """Finalize detached process results exactly once; never launch a replacement."""
        finalized = {row["payload"].get("execution_id")
                     for row in self.evidence_store.read("external_evaluator_outcome")}
        recovered = []
        for record in self.processes.started():
            if record.get("process_kind", "m0_external_evaluator") != "m0_external_evaluator":
                continue
            execution_id = record["execution_id"]
            if execution_id in finalized:
                continue
            while True:
                if execution_id in self.processes.finished_ids():
                    completed = self.processes.completed_result(record)
                    state = {"status": "finished", **completed}
                else:
                    state = self.processes.recover(record)
                if state["status"] == "pending":
                    if not wait:
                        break
                    time.sleep(0.05)
                    continue
                if state["status"] == "lost":
                    detail = state["detail"]
                    self.processes.fail(record, detail)
                    self._persist(record, "failed_to_run", detail)
                else:
                    try:
                        self._complete_process(record, state)
                    except ExternalEvaluatorError:
                        pass  # The structured native failure is already durable.
                recovered.append(self.outcome(record))
                break
        return recovered

    def __call__(self, candidate_id: str, head_sha: str, prompt: str) -> EvalResult:
        if not candidate_id or not head_sha or not isinstance(prompt, str):
            raise ValueError("external evaluation requires candidate/head and string prompt")
        reset_usage(self)
        self.last_execution_id = None
        directory = self.evaluation_root / uuid.uuid4().hex
        directory.mkdir(parents=True)
        request_path, response_path = directory / "request.json", directory / "response.json"
        request = {"schema_version": 1, "candidate_id": candidate_id,
                   "head_sha": head_sha, "prompt": prompt}
        if self.evaluation_context:
            request["evaluation_context"] = self.evaluation_context
        _atomic_json(request_path, request)
        args = [*self.command, str(request_path), str(response_path)]
        env = dict(os.environ)
        env["AR_FIDELITY"] = "dev"
        seccomp_policy = None
        if self.sandbox is not None:
            args = self.sandbox.wrap(args, self.workdir, self.protected_paths,
                                     self.data_dir, env)
            policy_factory = getattr(self.sandbox, "seccomp_spec", None)
            if callable(policy_factory):
                seccomp_policy = policy_factory()
        proc, record = self.processes.launch(
            args, self.workdir, env, self.time_limit,
            {"candidate_id": candidate_id, "head_sha": head_sha, "attempt": 1,
             "process_kind": "m0_external_evaluator",
             "sandbox_policy": self.sandbox_policy,
             "resource_policy": self.resource_limits,
             "execution_ref": self._evaluation_context.get(
                 "cohort_id", "m0_external_evaluator"),
             "request_path": str(request_path),
             "response_path": str(response_path), "started_wall": time.time(),
             "evaluation_context": self._evaluation_context},
            resource_limits=self.resource_limits, seccomp_policy=seccomp_policy)
        self.last_execution_id = record["execution_id"]
        completed = self.processes.wait(proc, record)
        return self._complete_process(record, completed)
