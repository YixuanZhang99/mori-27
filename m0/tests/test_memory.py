"""M5 scoped memory, lifecycle, two-stage read and invalidation tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory.store import MemoryError, ScopedMemory
from core.memory.types import (MemoryEntry, MemoryQuery, Payload, Provenance,
                               ScopeContext, ScopeUpgradeEvidence, TimeMeta,
                               UtilitySignals)
from core.x1.store import AppendOnlyStore

CTX = ScopeContext("run-1", "task-1", "domain-1")


def entry(entry_id, body, evidence=("r1",), scope="task", context=CTX,
          helpful=0, harmful=0, trust="verified"):
    return MemoryEntry(entry_id, Payload("text", body),
        Provenance("run-1", evidence_refs=list(evidence), trust_tier=trust),
        TimeMeta(created_at=1, ttl=10), context, scope=scope,
        utility=UtilitySignals(helpful_count=helpful, harmful_count=harmful))


def test_scoped_visibility_and_global_promotion_prerequisites(tmp_path):
    memory = ScopedMemory(AppendOnlyStore(tmp_path / "x1.jsonl"))
    memory.write(entry("m1", "shared lesson"), at=1)
    memory.transition("m1", "active", "test")
    other_task = MemoryQuery("shared", ScopeContext("run-2", "task-2", "domain-1"))
    assert memory.retrieve(other_task, at=2) == []
    incomplete = ScopeUpgradeEvidence(True, True, "snapshot-1")
    memory.promote_scope("m1", "domain", incomplete)
    assert [e.id for e in memory.retrieve(other_task, at=2)] == ["m1"]
    with pytest.raises(MemoryError, match="prerequisites"):
        memory.promote_scope("m1", "global", incomplete)


def test_two_stage_utility_rerank_and_negative_filter(tmp_path):
    memory = ScopedMemory(AppendOnlyStore(tmp_path / "x1.jsonl"), utility_weight=1.0)
    memory.write(entry("helpful", "alpha beta", helpful=5), at=1)
    memory.write(entry("harmful", "alpha", harmful=5), at=1)
    memory.transition("helpful", "active", "test")
    memory.transition("harmful", "active", "test")
    query = MemoryQuery("alpha", CTX)
    assert [e.id for e in memory.retrieve(query, at=2)] == ["helpful", "harmful"]
    negative_free = MemoryQuery("alpha", CTX, include_negative=False)
    assert [e.id for e in memory.retrieve(negative_free, at=3)] == ["helpful"]


def test_evidence_invalidation_demotes_without_deleting(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    memory = ScopedMemory(store)
    memory.write(entry("m1", "lesson", evidence=("receipt-1",)), at=1)
    memory.transition("m1", "active", "test")
    assert memory.invalidate_evidence({"receipt-1"}, "evaluator-v2") == ["m1"]
    assert "m1" in memory.entries
    assert memory.entries["m1"].state == "demoted"
    assert memory.retrieve(MemoryQuery("lesson", CTX), at=2) == []
    assert len(list(store.read("memory_invalidation"))) == 1
    assert list(store.read("memory_evidence"))


def test_ttl_demotes_and_hygiene_delete_is_only_physical_delete(tmp_path):
    memory = ScopedMemory(AppendOnlyStore(tmp_path / "x1.jsonl"))
    memory.write(entry("m1", "lesson"), at=1)
    memory.transition("m1", "active", "test")
    assert memory.expire(12) == ["m1"]
    assert memory.entries["m1"].state == "demoted"
    assert not hasattr(memory, "delete")
    with pytest.raises(MemoryError, match="confirmation"):
        memory.hygiene_delete("m1", "")
    memory.hygiene_delete("m1", "human-poisoning-confirmation")
    assert "m1" not in memory.entries
