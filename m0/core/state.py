"""Single serial M4/M5 write path for validated StateMutation objects."""
from __future__ import annotations

import threading
from dataclasses import asdict, is_dataclass
from enum import Enum

from core.executor.types import Candidate, EvidenceRecord
from core.frontier.research import MUTABLE_FIELDS, ResearchFrontier
from core.memory.store import ScopedMemory
from core.memory.types import MemoryEntry
from core.policy.types import MutationOp, StateMutation
from core.x1.store import AppendOnlyStore


class MutationError(ValueError):
    pass


def _jsonable(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return value


class StateApplier:
    """A semaphore-one writer; validation and audit share the same critical section."""

    def __init__(self, frontier: ResearchFrontier, memory: ScopedMemory,
                 store: AppendOnlyStore):
        self.frontier = frontier
        self.memory = memory
        self.store = store
        self._lock = threading.Lock()

    def apply(self, mutation: StateMutation) -> dict:
        with self._lock:
            try:
                result = self._apply_validated(mutation)
            except Exception as exc:
                self.store.append("state_mutation_rejected", {
                    "op": getattr(mutation, "op", None).value
                    if isinstance(getattr(mutation, "op", None), Enum)
                    else str(getattr(mutation, "op", "unknown")),
                    "target": getattr(mutation, "target", ""),
                    "rationale": getattr(mutation, "rationale", ""),
                    "error": str(exc)})
                raise
            receipt = {"op": mutation.op.value, "target": mutation.target,
                       "rationale": mutation.rationale, "result": result}
            self.store.append("state_mutation", {
                **_jsonable(mutation), "result": result})
            return receipt

    def replay(self, mutation: StateMutation) -> dict:
        """Rebuild post-checkpoint memory state without appending duplicate evidence."""
        with self._lock:
            return self._apply_validated(mutation)

    async def apply_async(self, mutation: StateMutation) -> dict:
        return self.apply(mutation)

    def apply_all(self, mutations: list[StateMutation]) -> list[dict]:
        return [self.apply(mutation) for mutation in mutations]

    def _apply_validated(self, mutation: StateMutation) -> dict:
        if not isinstance(mutation, StateMutation) or not mutation.rationale.strip():
            raise MutationError("StateMutation with non-empty rationale is required")
        if not mutation.target:
            raise MutationError("mutation target is required")
        if not isinstance(mutation.op, MutationOp):
            raise MutationError("mutation op must be a MutationOp")
        op = mutation.op
        if op is MutationOp.ADD_NODE:
            cand = mutation.fields.get("candidate")
            evidence = mutation.fields.get("evidence")
            if not isinstance(cand, Candidate) or cand.id != mutation.target:
                raise MutationError("ADD_NODE requires the matching Candidate")
            if evidence is not None and not isinstance(evidence, EvidenceRecord):
                raise MutationError("ADD_NODE evidence has the wrong type")
            self.frontier.add(cand, evidence)
            return {"node": cand.id, "status": self.frontier.nodes[cand.id].status}
        if op is MutationOp.UPDATE_NODE:
            fields = mutation.fields
            if not fields or not set(fields).issubset(MUTABLE_FIELDS):
                raise MutationError("UPDATE_NODE fields violate the mutable-field whitelist")
            node = self.frontier._node(mutation.target)
            from core.frontier.population import PopulationFrontier
            if isinstance(self.frontier, PopulationFrontier):
                self.frontier.update_node(mutation.target, fields)
                return {"node": node.id, "updated": sorted(fields)}
            for key, value in fields.items():
                setattr(node, key, value)
            return {"node": node.id, "updated": sorted(fields)}
        if op is MutationOp.POPULATION_FINALIZE:
            from core.frontier.population import PopulationFrontier
            if not isinstance(self.frontier, PopulationFrontier) or set(mutation.fields) != {
                    "admitted", "reason", "selected_id", "decision_ref"}:
                raise MutationError("POPULATION_FINALIZE requires the complete driver admission outcome")
            return self.frontier.finalize(mutation.target, **mutation.fields)
        if op is MutationOp.PRUNE:
            if set(mutation.fields) - {"reason"}:
                raise MutationError("PRUNE only accepts a reason field")
            reason = mutation.fields.get("reason", mutation.rationale)
            return {"cascade": self.frontier.prune(mutation.target, reason)}
        if op is MutationOp.MERGE:
            if mutation.fields:
                raise MutationError("MERGE carries no field payload")
            node = self.frontier._node(mutation.target)
            if node.status != "done" or node.eval_status != "ok":
                raise MutationError("only successfully evaluated done nodes can merge")
            node.status = "merged"
            return {"node": node.id, "status": node.status}
        if op is MutationOp.WRITE_MEMORY:
            if set(mutation.fields) != {"entry", "at"}:
                raise MutationError("WRITE_MEMORY requires exactly entry and at")
            entry, at = mutation.fields["entry"], mutation.fields["at"]
            if not isinstance(entry, MemoryEntry) or entry.id != mutation.target:
                raise MutationError("WRITE_MEMORY requires the matching MemoryEntry")
            self.memory.write(entry, at)
            return {"memory": entry.id, "level": entry.level, "state": entry.state}
        if op is MutationOp.PROMOTE_MEMORY:
            if set(mutation.fields) != {"target_level", "delta"}:
                raise MutationError("PROMOTE_MEMORY requires target_level and delta")
            entry = self.memory.promote_level(
                mutation.target, mutation.fields["target_level"],
                mutation.fields["delta"], mutation.rationale)
            return {"memory": entry.id, "level": entry.level, "state": entry.state}
        raise MutationError(f"unsupported mutation: {op}")
