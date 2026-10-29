"""M4 tree ResearchFrontier with isolated edge semantics and portable checkpoints."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Literal

from core.executor.types import Candidate, EvalStatus, EvidenceRecord
from core.x1.store import AppendOnlyStore

SamplingStrategy = Literal["greedy", "uniform"]
NodeStatus = Literal["pending", "running", "done", "merged", "pruned"]
MUTABLE_FIELDS = frozenset({
    "depth", "hypothesis", "status", "insight", "result", "score",
    "score_split", "test_score", "code_ref", "grounding", "related_work",
    "eval_status", "attempt", "cost", "uncertainty", "prune_reason",
})


@dataclass
class FrontierNode:
    id: str
    parent_ids: list[str]
    children_ids: list[str] = field(default_factory=list)
    depth: int = 0
    hypothesis: str | None = None
    status: NodeStatus = "pending"
    insight: str | None = None
    result: dict | None = None
    score: float | None = None
    score_split: dict[str, float] = field(default_factory=dict)
    test_score: float | None = None
    code_ref: str | None = None
    grounding: list[str] = field(default_factory=list)
    related_work: list[str] = field(default_factory=list)
    eval_status: str | None = None
    attempt: int = 0
    cost: dict[str, float] = field(default_factory=dict)
    uncertainty: float | None = None
    operator: str = "draft"
    created_cycle: int = 0
    prune_reason: str | None = None


def _canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(payload) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True)
class FrontierCheckpoint:
    schema_version: int
    payload: dict
    payload_sha256: str

    def to_bytes(self) -> bytes:
        return _canonical({"schema_version": self.schema_version,
                           "payload": self.payload,
                           "payload_sha256": self.payload_sha256})

    @classmethod
    def from_bytes(cls, raw: bytes) -> "FrontierCheckpoint":
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid frontier checkpoint encoding") from exc
        if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
            raise ValueError("unsupported frontier checkpoint schema")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or envelope.get("payload_sha256") != _digest(payload):
            raise ValueError("frontier checkpoint integrity check failed")
        return cls(1, payload, envelope["payload_sha256"])


class ResearchFrontier:
    """A tree/DAG-ready node store whose credit topology is skeleton-only."""

    def __init__(self, metric: str = "dev/score",
                 direction: Literal["maximize", "minimize"] = "maximize",
                 sample_seed: int = 0, store: AppendOnlyStore | None = None,
                 git_state: dict | None = None, messages: list | None = None):
        if not metric or direction not in {"maximize", "minimize"}:
            raise ValueError("frontier requires a metric and valid direction")
        self.metric = metric
        self.direction = direction
        self.sample_seed = sample_seed
        self.store = store
        self.git_state = dict(git_state or {})
        self.messages = list(messages or [])
        self.nodes: dict[str, FrontierNode] = {}
        self.edges: dict[str, object] = {"skeleton": set(), "reference": []}

    def _emit(self, kind: str, payload: dict) -> None:
        if self.store is not None:
            self.store.append(kind, payload)

    def add(self, cand: Candidate, evidence: EvidenceRecord | None) -> None:
        cand.validate()
        if evidence is not None and evidence.candidate_id != cand.id:
            raise ValueError("evidence candidate does not match frontier candidate")
        existing = self.nodes.get(cand.id)
        if existing is not None:
            if evidence is None or existing.status not in {"pending", "running"}:
                raise ValueError("candidate is already materialized in frontier")
            if existing.parent_ids != list(cand.parents):
                raise ValueError("candidate skeleton cannot change during completion")
            self._apply_evidence(existing, evidence)
            self._emit("frontier_completed", {"candidate_id": cand.id,
                                              "eval_status": existing.eval_status})
            return
        if cand.id in cand.parents:
            raise ValueError("candidate cannot parent itself")
        missing = [parent for parent in cand.parents if parent not in self.nodes]
        if missing:
            raise ValueError("missing skeleton parents: " + ", ".join(missing))
        depth = 1 + max((self.nodes[parent].depth for parent in cand.parents), default=-1)
        node = FrontierNode(cand.id, list(cand.parents), depth=depth,
                            hypothesis=cand.hypothesis, operator=cand.operator,
                            created_cycle=cand.created_cycle)
        self.nodes[cand.id] = node
        for parent in cand.parents:
            self.nodes[parent].children_ids.append(cand.id)
            self.nodes[parent].children_ids.sort()
            self.edges["skeleton"].add((parent, cand.id))
        if evidence is not None:
            self._apply_evidence(node, evidence)
        self._emit("frontier_added", {"candidate_id": cand.id,
                                      "parents": list(cand.parents),
                                      "status": node.status})

    def _apply_evidence(self, node: FrontierNode, evidence: EvidenceRecord) -> None:
        result = evidence.eval_result
        node.status = "done"
        node.insight = evidence.insight
        node.result = {"metrics": dict(result.metrics),
                       "text_feedback": result.text_feedback,
                       "result_text": evidence.result_text}
        node.score_split = dict(result.metrics)
        node.eval_status = result.status.value
        node.attempt = evidence.attempt
        node.code_ref = evidence.branch_ref
        node.cost = asdict(result.cost)
        node.uncertainty = result.uncertainty
        node.test_score = next((value for key, value in result.metrics.items()
                                if key.startswith("test/")), None)
        if result.status is EvalStatus.OK and self.metric in result.metrics:
            node.score = float(result.metrics[self.metric])

    def start(self, node: str) -> None:
        target = self._node(node)
        if target.status != "pending":
            raise ValueError("only pending nodes can enter running state")
        target.status = "running"
        self._emit("frontier_running", {"candidate_id": node})

    def add_reference(self, source: str, target: str, rationale: str) -> None:
        self._node(source)
        self._node(target)
        if source == target or not rationale:
            raise ValueError("reference edge requires distinct nodes and rationale")
        edge = {"source": source, "target": target, "rationale": rationale}
        if edge in self.edges["reference"]:
            raise ValueError("duplicate reference edge")
        self.edges["reference"].append(edge)
        self.edges["reference"].sort(key=lambda item: (item["source"], item["target"],
                                                       item["rationale"]))
        self._emit("frontier_reference_added", edge)

    def _node(self, node: str) -> FrontierNode:
        if node not in self.nodes:
            raise ValueError(f"unknown frontier node: {node}")
        return self.nodes[node]

    def _descendants(self, node: str) -> set[str]:
        found = {node}
        stack = [node]
        while stack:
            current = stack.pop()
            for child in self.nodes[current].children_ids:
                if child not in found:
                    found.add(child)
                    stack.append(child)
        return found

    def _eligible(self, scope: str | None = None) -> list[FrontierNode]:
        ids = self._descendants(scope) if scope is not None else set(self.nodes)
        return [self.nodes[node] for node in ids
                if self.nodes[node].status in {"done", "merged"}
                and self.nodes[node].eval_status == EvalStatus.OK.value
                and self.nodes[node].score is not None]

    def _ranked(self, scope: str | None = None) -> list[FrontierNode]:
        eligible = self._eligible(scope)
        return sorted(eligible, key=lambda node: (node.score, node.id),
                      reverse=self.direction == "maximize")

    def get_best(self, scope: str | None = None) -> str | None:
        ranked = self._ranked(scope)
        return ranked[0].id if ranked else None

    def sample(self, k: int, strategy: SamplingStrategy = "greedy") -> list[str]:
        if k < 0:
            raise ValueError("sample size cannot be negative")
        eligible = self._eligible()
        if strategy == "greedy":
            ordered = self._ranked()
        elif strategy == "uniform":
            ordered = sorted(eligible, key=lambda node: hashlib.sha256(
                f"{self.sample_seed}\0{node.id}".encode()).hexdigest())
        else:
            raise ValueError("unknown sampling strategy")
        return [node.id for node in ordered[:k]]

    def prune(self, node: str, reason: str) -> list[str]:
        self._node(node)
        if not reason:
            raise ValueError("soft prune requires a reason")
        pruned = []
        for descendant in sorted(self._descendants(node)):
            target = self.nodes[descendant]
            if target.status != "pruned":
                target.status = "pruned"
                target.prune_reason = reason if descendant == node else f"ancestor:{node}"
                pruned.append(descendant)
        self._emit("frontier_pruned", {"candidate_id": node, "reason": reason,
                                       "cascade": pruned, "hard_deleted": False})
        return pruned

    def view(self, projection: Literal["json", "compact", "constraints", "markdown"]) -> str:
        if projection == "json":
            return json.dumps({"nodes": [asdict(self.nodes[key]) for key in sorted(self.nodes)],
                               "edges": self._edge_payload()}, ensure_ascii=False,
                              sort_keys=True, indent=2)
        if projection == "compact":
            return "\n".join(f"{node.id} {node.status} score={node.score}"
                             for node in (self.nodes[key] for key in sorted(self.nodes)))
        if projection == "constraints":
            return "\n".join(f"PRUNE {node.id}: {node.prune_reason}"
                             for node in (self.nodes[key] for key in sorted(self.nodes))
                             if node.status == "pruned")
        if projection == "markdown":
            lines = ["| id | status | depth | score |", "|---|---|---:|---:|"]
            lines.extend(f"| {node.id} | {node.status} | {node.depth} | {node.score} |"
                         for node in (self.nodes[key] for key in sorted(self.nodes)))
            return "\n".join(lines)
        raise ValueError("unknown frontier projection")

    def _edge_payload(self) -> dict:
        return {"skeleton": [{"parent": parent, "child": child}
                             for parent, child in sorted(self.edges["skeleton"])],
                "reference": list(self.edges["reference"])}

    def checkpoint(self) -> bytes:
        payload = {"config": {"metric": self.metric, "direction": self.direction,
                              "sample_seed": self.sample_seed, "structure": "tree"},
                   "git_state": self.git_state,
                   "inflight_executor": sorted(node.id for node in self.nodes.values()
                                               if node.status == "running"),
                   "messages": self.messages,
                   "nodes": [asdict(self.nodes[key]) for key in sorted(self.nodes)],
                   "edges": self._edge_payload()}
        checkpoint = FrontierCheckpoint(1, payload, _digest(payload))
        self._emit("frontier_checkpoint", {"payload_sha256": checkpoint.payload_sha256,
                                           "nodes": len(self.nodes),
                                           "inflight": len(payload["inflight_executor"])})
        return checkpoint.to_bytes()

    @classmethod
    def restore(cls, raw: bytes, store: AppendOnlyStore | None = None) -> "ResearchFrontier":
        checkpoint = FrontierCheckpoint.from_bytes(raw)
        payload = checkpoint.payload
        config = payload["config"]
        if config.get("structure") != "tree":
            raise ValueError("checkpoint is not a tree frontier")
        frontier = cls(config["metric"], config["direction"], config["sample_seed"], store,
                       payload.get("git_state"), payload.get("messages"))
        for data in payload["nodes"]:
            node = FrontierNode(**data)
            if node.id in frontier.nodes:
                raise ValueError("duplicate node in checkpoint")
            frontier.nodes[node.id] = node
        for edge in payload["edges"]["skeleton"]:
            parent, child = edge["parent"], edge["child"]
            if parent not in frontier.nodes or child not in frontier.nodes:
                raise ValueError("checkpoint skeleton references unknown node")
            if parent not in frontier.nodes[child].parent_ids:
                raise ValueError("checkpoint skeleton/node parent mismatch")
            frontier.edges["skeleton"].add((parent, child))
        for node in frontier.nodes.values():
            if node.status not in {"pending", "running", "done", "merged", "pruned"}:
                raise ValueError("checkpoint contains unknown node status")
            if not node.parent_ids and node.depth != 0:
                raise ValueError("checkpoint root depth must be zero")
            for parent in node.parent_ids:
                if parent not in frontier.nodes:
                    raise ValueError("checkpoint node references unknown parent")
                if (parent, node.id) not in frontier.edges["skeleton"]:
                    raise ValueError("checkpoint parent lacks skeleton edge")
            if node.parent_ids:
                expected = 1 + max(frontier.nodes[p].depth for p in node.parent_ids)
                if node.depth != expected:
                    raise ValueError("checkpoint depth mismatch")
            if node.children_ids != sorted(node.children_ids):
                raise ValueError("checkpoint children are not canonical")
            for child in node.children_ids:
                if child not in frontier.nodes or node.id not in frontier.nodes[child].parent_ids:
                    raise ValueError("checkpoint child/parent relation is not reciprocal")
        for edge in payload["edges"]["reference"]:
            if edge["source"] not in frontier.nodes or edge["target"] not in frontier.nodes:
                raise ValueError("checkpoint reference references unknown node")
        frontier.edges["reference"] = list(payload["edges"]["reference"])
        inflight = sorted(node.id for node in frontier.nodes.values() if node.status == "running")
        if payload.get("inflight_executor") != inflight:
            raise ValueError("checkpoint inflight executor set mismatch")
        frontier._emit("frontier_restored", {"payload_sha256": checkpoint.payload_sha256,
                                             "nodes": len(frontier.nodes)})
        return frontier
