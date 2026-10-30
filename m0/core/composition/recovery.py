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
from contextlib import contextmanager
from pathlib import Path

from core.llm import UsageError
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

    def _advance(self):
        if not self.restoring:
            while self.cursor < len(self.rows) and (self.external(self.rows[self.cursor]["kind"])
                    or self.rows[self.cursor]["kind"] in self.diagnostics):
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
        if kind in self.diagnostics:
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
        binding = payload_digest({"args": args, "kwargs": kwargs})
        was_recorded = self.peek() is not None
        self.append("composed_provider_started", {"binding": binding})
        if was_recorded:
            row = self.peek()
            if row is None or row["kind"] != "composed_provider_completed" \
                    or row["payload"].get("binding") != binding:
                raise UsageError("provider invocation has no durable completion; refusing paid retry")
            data = row["payload"]
            if type(data["tokens"]) is not int or data["tokens"] < 0 or type(data["result"]) is not str:
                raise ValueError("invalid durable provider completion")
            restore = getattr(provider.raw_provider, "restore_state", None)
            if data["state"] is not None:
                if not callable(restore):
                    raise ValueError("provider cannot restore its durable completion state")
                restore(data["state"])
            provider._usage_total += data["tokens"]
            provider.last_usage = {"total_tokens": data["tokens"]}
            self.append("composed_provider_completed", data)
            return data["result"]
        before = provider.usage_total
        result = invoke(*args, **kwargs)
        if type(result) is not str:
            raise UsageError("recoverable provider must return text")
        save = getattr(provider.raw_provider, "checkpoint_state", None)
        data = {"binding": binding, "result": result, "tokens": provider.usage_total - before,
                "state": detached(save()) if callable(save) else None}
        self.append("composed_provider_completed", data)
        return result


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
        validate_options=lambda opts: validate(opts, {"command", "evaluator_version", "data_dir", "split_paths"}, domain_keys))
    registry.register("executor", "git_worktree", lambda ctx, opts: WorktreeCommandExecutor(
        store=ctx.store, **{"run_root": str(Path(ctx.workdir) / "worktrees"), **opts}),
        validate_options=lambda opts: validate(opts, {"base_repo"}, executor_keys))
