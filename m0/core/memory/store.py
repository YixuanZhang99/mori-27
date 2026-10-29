"""M5 deterministic lifecycle, scoped two-stage retrieval and soft invalidation."""
from __future__ import annotations

import re
from dataclasses import asdict

from core.memory.types import (TRUST_ORDER, MemoryEntry, MemoryQuery, Payload,
                               Provenance, ScopeContext, ScopeUpgradeEvidence,
                               TimeMeta, UtilitySignals)
from core.x1.store import AppendOnlyStore


class MemoryError(Exception):
    pass


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 0.0


def within_scope(entry: MemoryEntry, query: MemoryQuery) -> bool:
    if entry.scope == "global":
        return True
    if entry.scope == "domain":
        return entry.context.domain_id == query.context.domain_id
    if entry.scope == "task":
        return entry.context.task_id == query.context.task_id
    return entry.context.run_id == query.context.run_id


class ScopedMemory:
    def __init__(self, store: AppendOnlyStore, utility_weight: float = 0.5):
        if not 0 <= utility_weight <= 1:
            raise ValueError("utility_weight must be in [0,1]")
        self.store = store
        self.utility_weight = utility_weight
        self.entries: dict[str, MemoryEntry] = {}
        self._seq = 0

    def checkpoint_state(self) -> dict:
        """JSON-only state for the enclosing integrity-checked RunCheckpoint."""
        return {"seq": self._seq,
                "entries": [asdict(self.entries[entry_id])
                            for entry_id in sorted(self.entries)]}

    def restore_state(self, state: dict) -> None:
        """Restore without replaying side effects or emitting new memory evidence."""
        if self.entries or self._seq:
            raise MemoryError("memory restore requires an empty store")
        if not isinstance(state, dict) or not isinstance(state.get("entries"), list):
            raise MemoryError("memory checkpoint requires an entry list")
        seq = state.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise MemoryError("memory checkpoint sequence must be a non-negative integer")
        restored = {}
        for data in state["entries"]:
            if not isinstance(data, dict):
                raise MemoryError("memory checkpoint entry must be an object")
            values = dict(data)
            try:
                values["payload"] = Payload(**values["payload"])
                values["provenance"] = Provenance(**values["provenance"])
                values["time"] = TimeMeta(**values["time"])
                values["context"] = ScopeContext(**values["context"])
                values["utility"] = UtilitySignals(**values.get("utility") or {})
                entry = MemoryEntry(**values)
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryError("invalid memory checkpoint entry") from exc
            if (not entry.id or entry.id in restored or entry.level not in {"L1", "L2", "L3"}
                    or entry.state not in {"candidate", "active", "demoted", "archived", "deleted"}
                    or entry.scope not in {"run", "task", "domain", "global"}
                    or entry.provenance.trust_tier not in TRUST_ORDER):
                raise MemoryError("memory checkpoint contains an invalid or duplicate entry")
            restored[entry.id] = entry
        if seq < len(restored):
            raise MemoryError("memory checkpoint sequence predates its entries")
        self.entries = restored
        self._seq = seq

    def _log(self, kind: str, entry: MemoryEntry, **payload):
        self._seq += 1
        self.store.append(kind, {"seq": self._seq, "entry_id": entry.id,
                                 "state": entry.state, **payload})

    def write(self, entry: MemoryEntry, at: float) -> MemoryEntry:
        if entry.id in self.entries or entry.state != "candidate":
            raise MemoryError("new memory must have a unique id and candidate state")
        if at < entry.time.created_at:
            raise MemoryError("write time predates entry creation")
        self.entries[entry.id] = entry
        self._log("memory_evidence", entry, transition="observe->candidate",
                  actor="write", run_context=asdict(entry.context))
        return entry

    def transition(self, entry_id: str, target: str, actor: str,
                   rationale_ref: str = "") -> MemoryEntry:
        entry = self.entries[entry_id]
        allowed = {("candidate", "active"), ("active", "demoted"),
                   ("demoted", "archived"), ("demoted", "active"),
                   ("archived", "active")}
        if (entry.state, target) not in allowed:
            raise MemoryError(f"illegal lifecycle transition: {entry.state}->{target}")
        old = entry.state
        entry.state = target
        self._log("memory_evidence", entry, transition=f"{old}->{target}",
                  actor=actor, rationale_ref=rationale_ref,
                  signals_snapshot=asdict(entry.utility),
                  run_context=asdict(entry.context))
        return entry

    def hygiene_delete(self, entry_id: str, confirmation_ref: str) -> None:
        """The only physical deletion path; evidence is appended before removal."""
        if not confirmation_ref:
            raise MemoryError("hygiene deletion requires confirmation evidence")
        entry = self.entries[entry_id]
        old = entry.state
        entry.state = "deleted"
        self._log("memory_evidence", entry, transition=f"{old}->deleted",
                  actor="human", rationale_ref=confirmation_ref,
                  run_context=asdict(entry.context))
        del self.entries[entry_id]

    def promote_level(self, entry_id: str, target: str, delta: dict,
                      rationale_ref: str) -> MemoryEntry:
        """Incrementally merge L1→L2→L3; whole-payload replacement is forbidden."""
        entry = self.entries[entry_id]
        expected = {"L1": "L2", "L2": "L3"}.get(entry.level)
        if target != expected:
            raise MemoryError("memory level promotion must be L1->L2->L3")
        if entry.state not in {"candidate", "active"} or not rationale_ref:
            raise MemoryError("level promotion requires candidate/active state and rationale")
        if not isinstance(delta, dict) or not delta or not set(delta).issubset(
                {"append_text", "fields", "utility"}):
            raise MemoryError("promotion requires an incremental delta")
        append_text = delta.get("append_text")
        fields = delta.get("fields")
        utility = delta.get("utility", {})
        if append_text is not None and (entry.payload.kind != "text"
                                       or not isinstance(append_text, str) or not append_text.strip()):
            raise MemoryError("append_text requires a text payload and non-empty increment")
        if fields is not None and (entry.payload.kind != "structured"
                                  or not isinstance(fields, dict) or not fields
                                  or not isinstance(entry.payload.body, dict)):
            raise MemoryError("fields requires a structured mapping payload")
        if not isinstance(utility, dict) or not utility and delta.get("utility") is not None:
            raise MemoryError("utility delta cannot be empty")
        if not set(utility).issubset({"helpful_count", "harmful_count"}) or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in utility.values()):
            raise MemoryError("utility delta only accepts non-negative helpful/harmful counts")
        if append_text is None and fields is None and not utility:
            raise MemoryError("promotion delta has no incremental content")
        if entry.state == "candidate":
            self.transition(entry_id, "active", "policy.absorb", rationale_ref)
        if append_text is not None:
            entry.payload.body = (entry.payload.body + "\n" + append_text.strip()).strip()
        if fields is not None:
            entry.payload.body.update(fields)
        for key, value in utility.items():
            setattr(entry.utility, key, getattr(entry.utility, key) + value)
        old_level = entry.level
        entry.level = target
        self._log("memory_promotion", entry, from_level=old_level, to_level=target,
                  delta=delta, rationale_ref=rationale_ref)
        return entry

    def promote_scope(self, entry_id: str, target: str,
                      evidence: ScopeUpgradeEvidence) -> MemoryEntry:
        if target not in ("domain", "global"):
            raise MemoryError("scope promotion target must be domain or global")
        entry = self.entries[entry_id]
        if entry.scope == "global" or (target == "domain" and entry.scope == "domain"):
            raise MemoryError("scope is already at or above the requested level")
        basic = (evidence.source_validated and evidence.demotion_path_ready
                 and bool(evidence.rollback_snapshot_ref))
        global_ok = evidence.cross_task_evidence_ref or evidence.human_confirmation
        if not basic or (target == "global" and not global_ok):
            raise MemoryError("scope upgrade prerequisites are incomplete")
        old = entry.scope
        entry.scope = target
        self._log("memory_scope_upgrade", entry, old_scope=old, new_scope=target,
                  evidence=asdict(evidence))
        return entry

    def expire(self, at: float) -> list[str]:
        expired = []
        for entry in self.entries.values():
            if (entry.state == "active" and entry.time.ttl is not None
                    and at > entry.time.created_at + entry.time.ttl):
                self.transition(entry.id, "demoted", "ttl_expiry")
                expired.append(entry.id)
        return expired

    def retrieve(self, query: MemoryQuery, k: int = 5, at: float = 0, *,
                 entry_ids: set[str] | None = None,
                 levels: tuple[str, ...] | None = None) -> list[MemoryEntry]:
        if k < 1:
            raise ValueError("k must be positive")
        if entry_ids is not None and (not isinstance(entry_ids, set)
                or any(type(value) is not str for value in entry_ids)):
            raise ValueError("memory entry_ids must be a set of strings")
        if levels is not None and (not isinstance(levels, tuple) or not levels
                or any(level not in {"L1", "L2", "L3"} for level in levels)):
            raise ValueError("memory levels must be a nonempty tuple of L1/L2/L3")
        self.expire(at)
        visible = []
        for entry in self.entries.values():
            if entry_ids is not None and entry.id not in entry_ids:
                continue
            if levels is not None and entry.level not in levels:
                continue
            allowed_states = ("active", "demoted", "archived") if query.include_archived else ("active", "demoted")
            if entry.state not in allowed_states or not within_scope(entry, query):
                continue
            if entry.time.superseded_by is not None:
                continue
            if TRUST_ORDER[entry.provenance.trust_tier] < TRUST_ORDER[query.trust_floor]:
                continue
            if not query.include_negative and entry.utility.harmful_count > entry.utility.helpful_count:
                continue
            visible.append(entry)
        # Stage 1: deterministic recall, deliberately broader than final k.
        recalled = sorted(visible, key=lambda e: (
            -similarity(query.text, str(e.payload.body)), e.id))[:3 * k]
        # Stage 2: mandatory utility rerank; demotion therefore has a real read effect.
        def rank(entry):
            sim = similarity(query.text, str(entry.payload.body))
            state_discount = 0.5 if entry.state == "demoted" else 1.0
            score = ((1 - self.utility_weight) * sim
                     + self.utility_weight * entry.utility.scalar()) * state_discount
            return (-score, entry.id)
        ranked = sorted(recalled, key=rank)[:k]
        for entry in ranked:
            entry.utility.hit_count += 1
            entry.time.last_hit_at = at
            self._log("memory_hit", entry, query=query.text, at=at)
        return ranked

    def update_utility(self, entry_id: str, reward: float, alpha: float = 0.3):
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0,1]")
        entry = self.entries[entry_id]
        old = entry.utility.q_value
        entry.utility.q_value = reward if old is None else old + alpha * (reward - old)
        entry.utility.helpful_count += reward > 0
        entry.utility.harmful_count += reward < 0
        self._log("memory_utility", entry, reward=reward, alpha=alpha)
        return entry.utility.q_value

    def invalidate_evidence(self, evidence_refs: set[str], reason: str) -> list[str]:
        """Soft-invalidate dependent lessons; original entries and logs remain."""
        if not reason:
            raise ValueError("invalidation reason is required")
        invalidated = []
        for entry in self.entries.values():
            if not evidence_refs.intersection(entry.provenance.evidence_refs):
                continue
            if entry.time.superseded_by is not None:
                continue
            if entry.state == "active":
                self.transition(entry.id, "demoted", "evidence_invalidation", reason)
            entry.time.superseded_by = f"invalidated:{reason}"
            invalidated.append(entry.id)
            self._log("memory_invalidation", entry,
                      evidence_refs=sorted(evidence_refs), reason=reason)
        return invalidated
