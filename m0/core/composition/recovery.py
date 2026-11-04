"""Strict continuation of a journal prefix, without repeating paid invocations.

The checkpoint is the pure decision-state base. Already durable events must be
reproduced byte-for-byte (canonical JSON); external worktree events are verified
by their own operation protocol. Missing provider completion is never retried.
This is process-crash recovery, not a claim of recovery from lost disk writes.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

from core.llm import ProviderBudgetExhausted, UsageError
from core.x1.checkpoint import RunCheckpoint, payload_digest
from core.x1.store import AppendOnlyStore


def detached(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def recover_checkpoint(workdir):
    """Complete a durable checkpoint commit whose pointer swap was interrupted."""
    root = Path(workdir)
    pending, current = root / "checkpoint.pending.json", root / "checkpoint.json"
    if pending.exists():
        candidate = RunCheckpoint.load(pending)
        boundaries = list(AppendOnlyStore(root / "x1.jsonl").read("composed_checkpoint"))
        if boundaries and boundaries[-1]["payload"]["sha256"] == candidate.payload_sha256:
            if boundaries[-1]["payload"].get("next_cycle") != candidate.payload.get("next_cycle"):
                raise ValueError("pending checkpoint boundary differs from its contents")
            os.replace(pending, current)
    return RunCheckpoint.load(current)


def save_checkpoint(checkpoint, workdir, store):
    root = Path(workdir)
    pending = root / "checkpoint.pending.json"
    checkpoint.save(pending)
    with pending.open("rb") as stream:
        os.fsync(stream.fileno())
    store.append("composed_checkpoint", {"next_cycle": checkpoint.payload["next_cycle"],
                                        "sha256": checkpoint.payload_sha256})
    os.replace(pending, root / "checkpoint.json")


class ContinuationStore(AppendOnlyStore):
    """Expose the validated prefix during restore, then consume its suffix once."""
    diagnostics = {"frontier_checkpoint", "composed_resumed", "replay_certificate"}

    def __init__(self, path, checkpoint=None):
        super().__init__(path)
        self.rows = list(super().read())
        self.cursor = len(self.rows)
        self.restoring = checkpoint is not None
        if checkpoint is not None:
            matches = [i for i, row in enumerate(self.rows)
                       if row["kind"] == "composed_checkpoint"
                       and row["payload"]["sha256"] == checkpoint.payload_sha256]
            if not matches:
                raise ValueError("checkpoint has no durable journal boundary")
            self.cursor = matches[-1] + 1
        self.boundary = self.cursor
        self.replayed_starts = set()

    @staticmethod
    def external(kind):
        return kind.startswith("worktree_")

    def _diagnostic(self, row):
        return row["kind"] in self.diagnostics or (
            row["kind"] == "governed_component" and row["payload"].get("lane") == "main"
            and row["payload"].get("component") == "frontier"
            and row["payload"].get("kind") == "frontier_checkpoint")

    def _advance(self):
        if not self.restoring:
            while self.cursor < len(self.rows) and (self.external(self.rows[self.cursor]["kind"])
                    or self._diagnostic(self.rows[self.cursor])):
                self.cursor += 1

    def peek(self):
        self._advance()
        return self.rows[self.cursor] if self.cursor < len(self.rows) else None

    def resume(self):
        self.restoring = False
        self._advance()

    def read(self, kind=None):
        # Worktree's immutable operation manifests independently validate its
        # complete durable transcript, including the currently running process.
        visible = self.rows if kind and self.external(kind) else self.rows[:self.cursor]
        for row in visible:
            if kind is None or row["kind"] == kind:
                yield detached(row)

    def _write(self, record):
        super().append(record["kind"], record["payload"])
        with self.path.open("rb") as stream:
            os.fsync(stream.fileno())
        self.rows.append(record)

    def append(self, kind, payload):
        record = detached({"kind": kind, "payload": payload})
        if self.restoring:
            if kind == "composed_resumed":
                return
            raise ValueError("state restoration cannot append journal events")
        if self.external(kind):
            self._write(record)
            self._advance()
            return
        if self._diagnostic(record):
            if self.peek() is None:
                self._write(record)
                self.cursor = len(self.rows)
            return
        previous = self.peek()
        if previous is not None:
            if previous != record:
                raise ValueError(f"durable continuation diverged at {kind}")
            if kind == "hierarchical_budget" and payload.get("event") == "start":
                self.replayed_starts.add(payload["data"]["intent_id"])
            self.cursor += 1
        else:
            self._write(record)
            self.cursor = len(self.rows)

    def measurement(self, identity, elapsed):
        old = self.peek()
        if old is not None:
            if old["kind"] != "composed_operation_measurement" or old["payload"]["identity"] != identity:
                raise ValueError("operation measurement differs from durable invocation")
            elapsed = old["payload"]["elapsed"]
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise UsageError("operation has no valid durable wall-time measurement")
        self.append("composed_operation_measurement", {"identity": identity, "elapsed": elapsed})
        return elapsed

    def provider_call(self, provider, invoke, args, kwargs):
        request = {"args": args, "kwargs": kwargs}
        governed = provider.__dict__.get("current_invocation_binding")
        request_sha256 = payload_digest(request)
        if governed is not None:
            request = {"request_sha256": request_sha256, "invocation": governed}
        binding = payload_digest(request)
        was_recorded = self.peek() is not None
        self.append("composed_provider_started", {"binding": binding,
            **({"invocation": governed, "request_sha256": request_sha256} if governed is not None else {})})
        if was_recorded:
            row = self.peek()
            if row is None or row["kind"] != "composed_provider_completed" \
                    or row["payload"].get("binding") != binding:
                raise UsageError("provider invocation has no durable completion; refusing paid retry")
            return self._adopt_provider(provider, row["payload"], governed=governed)
        before = provider.usage_total
        refusal, failed = None, None
        try:
            result = invoke(*args, **kwargs)
        except ProviderBudgetExhausted as error:
            refusal = error
            result = str(error)
        except UsageError:
            raise
        except Exception as error:
            if governed is None:
                raise
            # Only a stable public error category is journaled; arbitrary
            # supplier exception bodies can contain requests or credentials.
            category = type(error).__name__ if type(error) in (ValueError, RuntimeError, TypeError) else "Exception"
            failed = RuntimeError("provider invocation failed (" + category + ")")
            result = str(failed)
        if type(result) is not str:
            raise UsageError("recoverable provider must return text")
        save = getattr(provider.raw_provider, "checkpoint_state", None)
        data = {"binding": binding, "result": result, "tokens": provider.usage_total - before,
                "state": detached(save()) if callable(save) else None}
        if governed is not None:
            try:
                data["observed_binding_sha256"] = payload_digest(provider.governance_binding())
            except Exception:
                data["observed_binding_sha256"] = None
        if refusal is not None:
            data["outcome"] = "budget_exhausted"
        if failed is not None:
            data["outcome"] = "failed"
        self.append("composed_provider_completed", data)
        if refusal is not None:
            raise refusal
        if failed is not None:
            raise failed
        return result

    def _adopt_provider(self, provider, data, *, governed, propagate=True):
        if type(data["tokens"]) is not int or data["tokens"] < 0 or type(data["result"]) is not str:
            raise ValueError("invalid durable provider completion")
        outcome = data.get("outcome", "returned")
        if outcome not in ("returned", "budget_exhausted", "failed") or outcome == "failed" and governed is None:
            raise ValueError("invalid durable provider outcome")
        restore = getattr(provider.raw_provider, "restore_state", None)
        if data["state"] is not None:
            if not callable(restore):
                raise ValueError("provider cannot restore its durable completion state")
            restore(data["state"])
        provider._usage_total += data["tokens"]
        provider.last_usage = {"total_tokens": data["tokens"]}
        measurement = provider.__dict__.get("governance_measurement")
        if measurement is not None:
            if "observed_binding_sha256" not in data:
                raise ValueError("governed provider completion lost its observed binding")
            measurement(data["tokens"], data["observed_binding_sha256"])
        self.append("composed_provider_completed", data)
        if propagate and outcome == "budget_exhausted":
            raise ProviderBudgetExhausted(data["result"])
        if propagate and outcome == "failed":
            raise RuntimeError(data["result"])
        return data["result"]

    def _adopt_nested_provider(self, provider):
        data = self.peek()["payload"]
        base = provider.__dict__.get("invocation_binding")
        expected = {**(base or {}), "ordinal": provider.__dict__.get("invocation_ordinal")}
        if base is None or data.get("invocation") != expected or data.get("binding") != payload_digest({
                "request_sha256": data.get("request_sha256"), "invocation": expected}):
            raise ValueError("nested provider receipt differs from evaluation invocation")
        provider.invocation_ordinal += 1
        self.append("composed_provider_started", data)
        row = self.peek()
        if row is None or row["kind"] != "composed_provider_completed" or row["payload"].get("binding") != data["binding"]:
            raise UsageError("nested provider has no completion; evaluator retry forbidden")
        self._adopt_provider(provider, row["payload"], governed=expected, propagate=False)

    async def evaluation_call(self, identity, invoke, *, provider=None, domain=None):
        """Adopt canonical native evidence; never retry an opaque started call."""
        from core.composition.evaluation import decode_evidence, encode_evidence
        identity = detached(identity)
        was_recorded = self.peek() is not None
        self.append("governed_evaluation_started", {"identity": identity})
        if was_recorded:
            while self.peek() is not None and self.peek()["kind"] == "composed_provider_started":
                if provider is None:
                    raise UsageError("evaluation cannot adopt unbound provider receipts")
                self._adopt_nested_provider(provider)
            row = self.peek()
            if row is None or row["kind"] != "governed_evaluation_completed" or \
                    row["payload"].get("identity") != identity:
                raise UsageError("native evaluation has no durable completion; refusing retry")
            data = row["payload"]
            elapsed = data.get("elapsed")
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("invalid durable native evaluation measurement")
            evidence = decode_evidence(data["evidence"])
            if data.get("domain_state") is not None:
                restore = getattr(domain, "restore_state", None)
                if not callable(restore):
                    raise ValueError("native domain cannot restore its terminal state")
                restore(data["domain_state"])
            self.append("governed_evaluation_completed", data)
            return evidence, elapsed
        started = time.monotonic()
        evidence = await invoke()
        elapsed = time.monotonic() - started
        save = getattr(domain, "checkpoint_state", None)
        self.append("governed_evaluation_completed", {"identity": identity,
            "evidence": encode_evidence(evidence), "elapsed": elapsed,
            "domain_state": detached(save()) if callable(save) else None})
        return evidence, elapsed


class RecordedOutcomeStore(ContinuationStore):
    """Consume a frozen transcript; an absent outcome never permits execution."""

    def __init__(self, path, rows):
        base = AppendOnlyStore(path)
        for row in rows:
            base.append(row["kind"], row["payload"])
        super().__init__(path)
        self.cursor = self.boundary = 0

    def _write(self, record):
        if self._diagnostic(record):
            return
        raise ValueError("recorded replay exhausted its authoritative transcript")

    def provider_call(self, provider, invoke, args, kwargs):
        if self.peek() is None:
            raise UsageError("recorded replay has no provider outcome; live dispatch forbidden")
        def forbidden(*args, **kwargs):
            raise UsageError("recorded replay cannot dispatch a provider")
        return super().provider_call(provider, forbidden, args, kwargs)

    async def evaluation_call(self, identity, invoke, *, provider=None, domain=None):
        if self.peek() is None:
            raise UsageError("recorded replay has no evaluation outcome; live execution forbidden")
        async def forbidden():
            raise UsageError("recorded replay cannot dispatch an evaluator")
        return await super().evaluation_call(identity, forbidden, provider=provider, domain=domain)


@contextmanager
def coordinator_lock(workdir):
    path = Path(workdir) / "coordinator.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another coordinator owns this run") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def register_worktree(registry):
    from core.composition.command_domain import CommandDomain
    from core.composition.worktree import WorktreeCommandExecutor

    def validate(options, required, allowed):
        if type(options) is not dict or not required <= set(options) or set(options) - allowed:
            raise ValueError("invalid command/worktree configuration keys")

    domain_keys = {"command", "evaluator_version", "data_dir", "split_paths", "fidelities",
                   "measured_cost_units", "time_limit", "supports_resume"}
    executor_keys = {"base_repo", "run_root", "base_ref", "artifact_path", "protected_paths",
                     "sandbox", "resource_limits"}
    registry.register("domain", "command", lambda ctx, opts: CommandDomain(**opts),
        validate_options=lambda opts: validate(opts, {"command", "evaluator_version", "data_dir", "split_paths"}, domain_keys),
        governance={"schema_version": 1, "fresh_session": True, "state_independent": True})
    registry.register("executor", "git_worktree", lambda ctx, opts: WorktreeCommandExecutor(
        store=ctx.store, **{"run_root": str(Path(ctx.workdir) / "worktrees"), **opts}),
        validate_options=lambda opts: validate(opts, {"base_repo"}, executor_keys))
