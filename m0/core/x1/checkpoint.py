"""Versioned, integrity-checked and atomically replaced Framework checkpoints."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def payload_digest(payload) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


@dataclass(frozen=True)
class RunCheckpoint:
    schema_version: int
    payload: dict
    payload_sha256: str

    @classmethod
    def create(cls, payload: dict) -> "RunCheckpoint":
        required = {"git_state", "inflight_executor", "messages"}
        if not required.issubset(payload):
            raise ValueError("run checkpoint requires GitState, inflight executor and messages")
        return cls(1, payload, payload_digest(payload))

    def to_bytes(self) -> bytes:
        return canonical({"schema_version": self.schema_version,
                          "payload": self.payload,
                          "payload_sha256": self.payload_sha256})

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(self.to_bytes())
        os.replace(temporary, target)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "RunCheckpoint":
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid run checkpoint encoding") from exc
        if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
            raise ValueError("unsupported run checkpoint schema")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or envelope.get("payload_sha256") != payload_digest(payload):
            raise ValueError("run checkpoint integrity check failed")
        checkpoint = cls(1, payload, envelope["payload_sha256"])
        cls.create(payload)  # required run-context fields
        return checkpoint

    @classmethod
    def load(cls, path: str | Path) -> "RunCheckpoint":
        return cls.from_bytes(Path(path).read_bytes())


def certified_snapshot_ref(path: str | Path) -> str:
    """Hash deterministic run state, excluding resume controls and diagnostic timing."""
    from core.frontier.research import FrontierCheckpoint

    checkpoint = RunCheckpoint.load(path)
    payload = copy.deepcopy(checkpoint.payload)
    config = dict(payload.get("config") or {})
    for key in ("resume_from_checkpoint", "stop_after_generation"):
        config.pop(key, None)
    payload["config"] = config

    # Measured per-node wall time is diagnostic and cannot be bit-replayed. Keep
    # every score, cost account, edge and governance field, and rebind the nested
    # integrity digest after normalizing only that one observation.
    frontier = FrontierCheckpoint.from_bytes(payload["frontier_checkpoint"].encode("utf-8"))
    frontier_payload = copy.deepcopy(frontier.payload)
    for node in frontier_payload.get("nodes", []):
        cost = node.get("cost")
        if isinstance(cost, dict) and "wall_seconds" in cost:
            cost["wall_seconds"] = 0.0
    normalized_frontier = {
        "schema_version": frontier.schema_version,
        "payload": frontier_payload,
        "payload_sha256": payload_digest(frontier_payload)}
    payload["frontier_checkpoint"] = canonical(normalized_frontier).decode("utf-8")
    return "sha256:" + payload_digest(payload)
