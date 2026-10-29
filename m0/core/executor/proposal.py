"""Durable detached LLM proposal calls with operation-bound exactly-once adoption.

The command is a trusted adapter, not a filesystem/network/credential sandbox. It receives
a request and response path, inherits credentials without serializing them, and writes an
atomic JSON envelope. The target defaults to the direct-prctl seccomp denylist while
retaining network and environment access. A stable operation identity lets a restarted owner wait
for and adopt the original call instead of issuing another provider request.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from core.executor.process import ProcessJournal
from core.executor.resources import ResourcePolicy
from core.executor.seccomp import SECCOMP_DIRECT_PRCTL, build_seccomp_policy
from core.executor.types import EvalStatus
from core.llm import reset_usage, take_usage
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


class ExternalProposalError(RuntimeError):
    def __init__(self, status: EvalStatus, detail: str, execution_id: str | None = None):
        super().__init__(detail[-4000:])
        self.status = status
        self.execution_id = execution_id


class ExternalCommandLLM:
    """Run one durable external command per context-bound LLM operation."""

    durable_operation_recovery = True

    def __init__(self, command: list[str], workdir: str | Path,
                 evidence_store: AppendOnlyStore, *, time_limit: int | None = 120,
                 fallback_llm=None, resource_policy: ResourcePolicy | None = None,
                 seccomp: bool = True):
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("external proposer command must be a non-empty argv list")
        if isinstance(time_limit, bool) or not isinstance(time_limit, int) or time_limit <= 0:
            raise ValueError("external proposer time_limit must be a positive integer")
        if resource_policy is not None and not isinstance(resource_policy, ResourcePolicy):
            raise TypeError("resource_policy must be ResourcePolicy or None")
        if not isinstance(seccomp, bool):
            raise TypeError("external proposer seccomp must be explicitly boolean")
        self.command = list(command)
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.evidence_store = evidence_store
        self.time_limit = time_limit
        self.fallback_llm = fallback_llm
        self.resource_policy = resource_policy
        self.resource_limits = resource_policy.as_dict() if resource_policy else {}
        self.seccomp = seccomp
        self.seccomp_policy = build_seccomp_policy() if seccomp else None
        self.processes = ProcessJournal(evidence_store)
        self.root = evidence_store.path.parent / "proposal-calls"
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_usage = None
        self._operation_context = {}

    def fork(self, workdir: str | Path, evidence_store: AppendOnlyStore):
        """Bind certified replay to independent request/process/outcome evidence."""
        return type(self)(self.command, workdir, evidence_store,
                          time_limit=self.time_limit, fallback_llm=self.fallback_llm,
                          resource_policy=self.resource_policy, seccomp=self.seccomp)

    def set_operation_context(self, context: dict) -> None:
        if self._operation_context:
            raise RuntimeError("external proposal operation context is already active")
        if not isinstance(context, dict) or not context.get("candidate_id") \
                or not context.get("cohort_id"):
            raise ValueError("external proposal requires cohort and candidate identity")
        self._operation_context = dict(context)

    def clear_operation_context(self) -> None:
        self._operation_context = {}

    @staticmethod
    def _usage(payload) -> dict[str, int]:
        if not isinstance(payload, dict) or set(payload) != {"total_tokens"}:
            raise ValueError("token_usage requires exactly total_tokens")
        total = payload["total_tokens"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("total_tokens must be a non-negative integer")
        return {"total_tokens": total}

    def _outcomes(self, context: dict) -> list[dict]:
        return [row["payload"] for row in self.evidence_store.read("external_proposer_outcome")
                if row["payload"].get("execution_ref") == context["cohort_id"]
                and row["payload"].get("operation_id") == context["candidate_id"]]

    def _return_outcome(self, payload: dict, request_sha: str) -> str:
        if payload.get("request_sha256") != request_sha:
            raise RuntimeError("external proposal outcome differs from its operation request")
        usage = payload.get("token_usage")
        self.last_usage = self._usage(usage) if usage is not None else None
        if payload.get("status") == "ok":
            self.last_usage = self._usage(usage)
            content = payload.get("content")
            if not isinstance(content, str):
                raise RuntimeError("successful external proposal outcome lacks text")
            return content
        status = {"timeout": EvalStatus.TIMEOUT, "invalid": EvalStatus.INVALID}.get(
            payload.get("status"), EvalStatus.FAILED_TO_RUN)
        raise ExternalProposalError(status, str(payload.get("detail") or "proposal failed"),
                                    payload.get("execution_id"))

    def _persist(self, record: dict, status: str, detail: str, *,
                 content: str | None = None, usage: dict | None = None) -> dict:
        response_path = Path(record["response_path"])
        outcome_path = response_path.parent / "native-proposal-outcome.json"
        outcome = {"schema_version": 1, "execution_id": record["execution_id"],
                   "execution_ref": record["execution_ref"],
                   "operation_id": record["operation_id"],
                   "candidate_id": record["candidate_id"], "status": status,
                   "detail": detail[-4000:], "content": content,
                   "request_sha256": _digest(Path(record["request_path"])),
                   "response_sha256": _digest(response_path),
                   "token_usage": usage}
        existing = [row["payload"] for row in self.evidence_store.read(
            "external_proposer_outcome")
            if row["payload"].get("execution_id") == record["execution_id"]]
        if outcome_path.exists():
            durable = json.loads(outcome_path.read_text(encoding="utf-8"))
            if durable != outcome:
                raise RuntimeError("external proposal outcome file differs from completion")
        else:
            _atomic_json(outcome_path, outcome)
        payload = {**outcome, "outcome_path": str(outcome_path)}
        if not existing:
            self.evidence_store.append("external_proposer_outcome", payload)
        elif len(existing) != 1 or existing[0] != payload:
            raise RuntimeError("duplicate or mismatched external proposal outcome")
        return payload

    def _complete(self, record: dict, completed: dict) -> dict:
        # A failed adapter may still provide an explicit final usage meter. A
        # missing/malformed meter remains unknown, including after timeouts.
        usage = None
        try:
            envelope = json.loads(Path(record["response_path"]).read_text(encoding="utf-8"))
            if isinstance(envelope, dict) and envelope.get("schema_version") == 1:
                usage = self._usage(envelope.get("token_usage"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            envelope = None
        if completed["timeout"]:
            payload = self._persist(record, "timeout", "external proposal exceeded time_limit",
                                    usage=usage)
        elif completed["returncode"] != 0:
            detail = (completed["stderr"] or completed["stdout"]
                      or completed.get("wrapper_error") or "external proposal failed")
            payload = self._persist(record, "failed_to_run", detail, usage=usage)
        else:
            try:
                if not isinstance(envelope, dict) \
                        or set(envelope) != {"schema_version", "content", "token_usage"} \
                        or envelope["schema_version"] != 1 \
                        or not isinstance(envelope["content"], str):
                    raise ValueError("external response must be a version-1 proposal envelope")
                usage = self._usage(envelope["token_usage"])
                payload = self._persist(record, "ok", "external proposal completed",
                                        content=envelope["content"], usage=usage)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                payload = self._persist(record, "invalid",
                                        f"invalid external proposal response: {error}", usage=usage)
        self._return_outcome(payload, _digest(Path(record["request_path"])))
        return payload

    def __call__(self, prompt: str) -> str:
        reset_usage(self)
        if not self._operation_context:
            if self.fallback_llm is None:
                raise RuntimeError("external proposal requires an operation context")
            reset_usage(self.fallback_llm)
            try:
                return self.fallback_llm(prompt)
            finally:
                self.last_usage = {"total_tokens": take_usage(self.fallback_llm)}
        context = self._operation_context
        operation = hashlib.sha256(
            f"{context['cohort_id']}\0{context['candidate_id']}".encode()).hexdigest()
        directory = self.root / operation
        directory.mkdir(parents=True, exist_ok=True)
        request_path, response_path = directory / "request.json", directory / "response.json"
        request = {"schema_version": 1, "execution_ref": context["cohort_id"],
                   "operation_id": context["candidate_id"], "prompt": prompt}
        if request_path.exists():
            if json.loads(request_path.read_text(encoding="utf-8")) != request:
                raise RuntimeError("external proposal operation request has changed")
        else:
            _atomic_json(request_path, request)
        request_sha = _digest(request_path)
        outcomes = self._outcomes(context)
        if len(outcomes) > 1:
            raise RuntimeError("duplicate external proposal operation outcomes")
        if outcomes:
            return self._return_outcome(outcomes[0], request_sha)
        records = [record for record in self.processes.started(context["cohort_id"])
                   if record.get("process_kind") == "m0_external_proposer"
                   and record.get("operation_id") == context["candidate_id"]]
        if len(records) > 1:
            raise RuntimeError("duplicate external proposal operation processes")
        if records:
            record, proc = records[0], None
            if record.get("request_path") != str(request_path) \
                    or record.get("proposal_context") != context:
                raise RuntimeError("external proposal recovery context mismatch")
        else:
            args = [*self.command, str(request_path), str(response_path)]
            proc, record = self.processes.launch(
                args, self.workdir, dict(os.environ), self.time_limit,
                {"candidate_id": context["candidate_id"], "attempt": 1,
                 "process_kind": "m0_external_proposer",
                 "execution_ref": context["cohort_id"],
                 "operation_id": context["candidate_id"],
                 "resource_policy": self.resource_limits,
                 "request_path": str(request_path), "response_path": str(response_path),
                 "proposal_context": context}, resource_limits=self.resource_limits,
                seccomp_policy=self.seccomp_policy,
                seccomp_delivery=SECCOMP_DIRECT_PRCTL if self.seccomp else None)
        while True:
            outcomes = self._outcomes(context)
            if outcomes:
                return self._return_outcome(outcomes[0], request_sha)
            if proc is not None:
                completed = self.processes.wait(proc, record)
                proc = None
            elif record["execution_id"] in self.processes.finished_ids():
                completed = self.processes.completed_result(record)
            else:
                state = self.processes.recover(record)
                if state["status"] == "pending":
                    time.sleep(0.05)
                    continue
                if state["status"] == "lost":
                    self.processes.fail(record, state["detail"])
                    payload = self._persist(record, "failed_to_run", state["detail"])
                    return self._return_outcome(payload, request_sha)
                completed = state
            return self._return_outcome(self._complete(record, completed), request_sha)
