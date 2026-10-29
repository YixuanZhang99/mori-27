"""Framework main-loop absorption, admission mutations and governed-state recovery."""
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import Framework, LoopConfig
from core.memory import MemoryEntry, ScopeContext, ScopedMemory
from core.memory.types import Payload, Provenance, TimeMeta
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "governed main-loop state"


class StaticLLM:
    """Produces the same candidate so M9 rejects every post-genesis improvement."""

    def __call__(self, prompt: str) -> str:
        self.last_usage = {"total_tokens": 1000}  # explicit simulated call
        return "Solve the problem carefully."


def checkpoint_state(workdir):
    payload = json.loads((Path(workdir) / "checkpoint.json").read_text())["payload"]
    return payload["frontier_checkpoint"], payload["memory"]


def test_every_main_candidate_is_absorbed_and_admission_mutation_is_applied(tmp_path):
    fw = Framework(StaticLLM(), toy_evaluator,
                   LoopConfig(max_generations=4, baseline_every=2), str(tmp_path))
    result = fw.evolve(TASK)
    state = result["governed_state"]
    assert state["frontier_nodes"] == 5
    assert state["merged_ids"] == result["accepted_candidate_ids"]
    assert len(state["merged_ids"]) == 1 and len(state["pruned_ids"]) == 4
    assert state["memory_entries"] == 5
    assert state["memory_levels"] == {"L1": 0, "L2": 5, "L3": 0}
    assert state["mutation_receipts"] == 25
    assert state["baseline_in_frontier"] is False

    operations = Counter(record["payload"]["op"]
                         for record in fw.store.read("state_mutation"))
    assert operations == {"add_node": 5, "update_node": 5, "write_memory": 5,
                          "promote_memory": 5, "merge": 1, "prune": 4}
    frontier_raw, memory_state = checkpoint_state(tmp_path)
    frontier = json.loads(frontier_raw)["payload"]
    node_ids = {node["id"] for node in frontier["nodes"]}
    baseline_ids = {record["payload"]["candidate_id"]
                    for record in fw.store.read("baseline")}
    assert len(baseline_ids) == 2 and not baseline_ids.intersection(node_ids)
    assert len(memory_state["entries"]) == 5
    assert fw.inspect()["governed_state"] == state


def test_resume_restores_frontier_and_memory_without_duplicate_mutations(tmp_path):
    cfg = LoopConfig(max_generations=6, baseline_every=2)
    reference_dir = tmp_path / "reference"
    reference = Framework(MockLLM(), toy_evaluator, cfg, str(reference_dir))
    expected = reference.evolve(TASK)

    run_dir = tmp_path / "resumed"
    partial = Framework(MockLLM(), toy_evaluator,
                        LoopConfig(max_generations=6, baseline_every=2,
                                   stop_after_generation=3), str(run_dir))
    partial.evolve(TASK)
    partial_mutations = len(list(partial.store.read("state_mutation")))

    resumed = Framework(MockLLM(), toy_evaluator,
                        LoopConfig(max_generations=6, baseline_every=2,
                                   resume_from_checkpoint=True), str(run_dir))
    actual = resumed.evolve(TASK)
    assert actual["governed_state"] == expected["governed_state"]
    assert checkpoint_state(run_dir) == checkpoint_state(reference_dir)
    assert len(list(resumed.store.read("state_mutation"))) == 35
    assert partial_mutations == 20

    completed = Framework(MockLLM(), toy_evaluator,
                          LoopConfig(max_generations=6, baseline_every=2,
                                     resume_from_checkpoint=True), str(run_dir))
    no_op = completed.evolve(TASK)
    assert no_op["governed_state"] == expected["governed_state"]
    assert len(list(completed.store.read("state_mutation"))) == 35
    assert checkpoint_state(run_dir) == checkpoint_state(reference_dir)


def test_memory_checkpoint_roundtrip_is_side_effect_free_and_validated(tmp_path):
    store = AppendOnlyStore(tmp_path / "source.jsonl")
    memory = ScopedMemory(store)
    context = ScopeContext("run", "task", "domain")
    entry = MemoryEntry("lesson", Payload("text", "raw"), Provenance("run"),
                        TimeMeta(created_at=1), context, level="L1")
    memory.write(entry, 1)
    state = memory.checkpoint_state()

    restored_store = AppendOnlyStore(tmp_path / "restored.jsonl")
    restored = ScopedMemory(restored_store)
    restored.restore_state(deepcopy(state))
    assert restored.checkpoint_state() == state
    assert list(restored_store.read()) == []

    invalid = deepcopy(state)
    invalid["seq"] = 0
    with pytest.raises(Exception, match="sequence predates"):
        ScopedMemory(AppendOnlyStore(tmp_path / "invalid.jsonl")).restore_state(invalid)
