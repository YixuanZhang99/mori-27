"""M1 absorb and serial StateMutation application into M4/M5."""
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import Candidate, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.memory import MemoryEntry, ScopeContext, ScopedMemory
from core.memory.types import Payload, Provenance, TimeMeta
from core.policy import BestFirstPolicy, MutationOp, StateMutation
from core.state import MutationError, StateApplier
from core.x1.store import AppendOnlyStore

CTX = ScopeContext("run-1", "task-1", "domain-1")


def evidence(node="c1", status=EvalStatus.OK, executor_status="scored"):
    return EvidenceRecord(node, EvalResult(status, {"dev/score": .75},
                                           text_feedback="evaluation feedback"),
                          f"branch/{node}", executor_status, 2,
                          insight="distilled lesson", result_text="raw execution result")


def fixture(tmp_path):
    store = AppendOnlyStore(tmp_path / "state.jsonl")
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    return frontier, memory, StateApplier(frontier, memory, store), store


def test_best_first_absorb_writes_l1_then_incremental_l2_and_node_view(tmp_path):
    frontier, memory, applier, store = fixture(tmp_path)
    ev = evidence()
    applier.apply(StateMutation(MutationOp.ADD_NODE, "c1",
                                {"candidate": Candidate("c1"), "evidence": ev}, "add evidence"))
    policy = BestFirstPolicy(CTX)
    mutations = asyncio.run(policy.absorb(ev))
    assert [mutation.op for mutation in mutations] == [
        MutationOp.UPDATE_NODE, MutationOp.WRITE_MEMORY, MutationOp.PROMOTE_MEMORY]
    applier.apply_all(mutations)
    entry = memory.entries[mutations[1].target]
    assert entry.level == "L2" and entry.state == "active"
    assert "raw execution result" in entry.payload.body
    assert "distilled lesson" in entry.payload.body
    assert entry.provenance.source_branch == "branch/c1"
    assert frontier.nodes["c1"].insight == "distilled lesson"
    assert frontier.nodes["c1"].attempt == 2
    assert len(list(store.read("state_mutation"))) == 4
    assert len(list(store.read("memory_promotion"))) == 1
    assert asyncio.run(policy.select(frontier)) == ["c1"]


def test_failed_evidence_remains_unpromoted_l1(tmp_path):
    frontier, memory, applier, _ = fixture(tmp_path)
    ev = evidence("failed", EvalStatus.FAILED_TO_RUN, "failed_to_run")
    applier.apply(StateMutation(MutationOp.ADD_NODE, "failed",
                                {"candidate": Candidate("failed"), "evidence": ev}, "add failure"))
    mutations = asyncio.run(BestFirstPolicy(CTX).absorb(ev))
    assert len(mutations) == 2
    applier.apply_all(mutations)
    entry = memory.entries[mutations[1].target]
    assert entry.level == "L1" and entry.state == "candidate"
    assert entry.provenance.trust_tier == "ungated"


def test_whitelist_rationale_and_incremental_delta_are_enforced(tmp_path):
    frontier, memory, applier, store = fixture(tmp_path)
    applier.apply(StateMutation(MutationOp.ADD_NODE, "c1",
                                {"candidate": Candidate("c1"), "evidence": evidence()}, "add"))
    before = frontier.checkpoint()
    with pytest.raises(MutationError, match="rationale"):
        applier.apply(StateMutation(MutationOp.UPDATE_NODE, "c1", {"insight": "x"}, ""))
    with pytest.raises(MutationError, match="whitelist"):
        applier.apply(StateMutation(MutationOp.UPDATE_NODE, "c1",
                                    {"parent_ids": ["other"]}, "illegal lineage edit"))
    assert frontier.checkpoint() == before

    entry = MemoryEntry("raw", Payload("text", "original"),
                        Provenance("run-1"), TimeMeta(created_at=1), CTX, level="L1")
    applier.apply(StateMutation(MutationOp.WRITE_MEMORY, "raw",
                                {"entry": entry, "at": 1}, "write raw"))
    with pytest.raises(Exception, match="incremental delta"):
        applier.apply(StateMutation(MutationOp.PROMOTE_MEMORY, "raw",
                                    {"target_level": "L2", "delta": {"body": "replace"}},
                                    "attempt whole replacement"))
    assert memory.entries["raw"].payload.body == "original"
    assert memory.entries["raw"].level == "L1"
    assert len(list(store.read("state_mutation_rejected"))) == 3


def test_merge_requires_scored_done_node_and_prune_remains_soft(tmp_path):
    frontier, _, applier, _ = fixture(tmp_path)
    applier.apply(StateMutation(MutationOp.ADD_NODE, "c1",
                                {"candidate": Candidate("c1"), "evidence": evidence()}, "add"))
    applier.apply(StateMutation(MutationOp.MERGE, "c1", {}, "admission approved"))
    assert frontier.nodes["c1"].status == "merged"
    result = applier.apply(StateMutation(MutationOp.PRUNE, "c1", {}, "later regression"))
    assert result["result"]["cascade"] == ["c1"]
    assert frontier.nodes["c1"].status == "pruned"
    assert "c1" in frontier.nodes


def test_state_applier_serializes_real_threaded_memory_writes(tmp_path):
    _, memory, applier, store = fixture(tmp_path)

    def write(index):
        entry = MemoryEntry(f"m{index}", Payload("text", f"lesson {index}"),
                            Provenance("run-1"), TimeMeta(created_at=1), CTX)
        applier.apply(StateMutation(MutationOp.WRITE_MEMORY, entry.id,
                                    {"entry": entry, "at": 1}, f"write {index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))
    assert len(memory.entries) == 24
    records = list(store.read("state_mutation"))
    memory_events = list(store.read("memory_evidence"))
    assert len(records) == 24 and len(memory_events) == 24
    assert sorted(record["payload"]["seq"] for record in memory_events) == list(range(1, 25))
