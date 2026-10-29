"""M4 island archive, evolve-block structural guards and M3 health probe."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.archive import IslandArchive
from core.loop import Framework, LoopConfig
from core.operator.ops import (apply_evolve_block, evolve_block_improve,
                               EVOLVE_END, EVOLVE_START)
from core.operator.types import OperatorSpec
from examples.toy_gepa import MockLLM, toy_evaluator


def cand(cid, score):
    return {"candidate_id": cid, "score": score, "prompt": cid}


def test_evolve_block_patcher_preserves_frozen_skeleton():
    parent = f"HEADER\n{EVOLVE_START}\nold\n{EVOLVE_END}\nFOOTER"
    out = apply_evolve_block(parent, "new instruction")
    assert out.startswith("HEADER")
    assert out.endswith("FOOTER")
    assert "old" not in out and "new instruction" in out
    with pytest.raises(ValueError, match="boundaries"):
        apply_evolve_block("no markers", "new")


def test_evolve_block_operator_and_failed_apply_never_evaluates(tmp_path):
    spec = OperatorSpec("imp", "improve", prompt_version="1")
    parent = f"HEAD{EVOLVE_START}base{EVOLVE_END}TAIL"
    proposal = evolve_block_improve(lambda p: "replacement", spec, "p", parent,
                                    "failure trace", 0.2)
    assert proposal.apply_result == "ok"
    assert proposal.patch_text.startswith("HEAD")
    # A profile mismatch produces a failed proposal; the loop must not admit it.
    mismatched_llm = (lambda p: "Solve the problem carefully."
                      if p.startswith("[draft") else "replacement")
    fw = Framework.from_profile("funsearch_island", mismatched_llm, toy_evaluator,
                                LoopConfig(max_generations=2), str(tmp_path))
    out = fw.evolve("toy")
    improve_funnels = [f for f in out["funnels"] if f.operator == "improve"]
    assert all(f.runnable == 0 and f.admitted == 0 for f in improve_funnels)


def test_island_archive_selection_migration_and_soft_eviction():
    archive = IslandArchive(num_islands=2, migration_interval=2)
    a, b = cand("a", 0.5), cand("b", 0.9)
    archive.register(a, 0)  # island 0
    archive.register(b, 1)  # island 1
    assert archive.select_parent([a, b], 0)["candidate_id"] == "a"
    assert archive.select_parent([a, b], 1)["candidate_id"] == "b"
    events = archive.migrate_if_due(2)
    assert events and archive.migration_count >= 1
    archive.evict("a", "test eviction")
    assert archive.entries["a"].soft_deleted is True
    assert "a" in archive.entries  # hard evidence remains
    assert archive.health()["soft_deleted"] == 1


def test_island_framework_and_replay(tmp_path):
    archive = IslandArchive(num_islands=2, migration_interval=2)
    fw = Framework(MockLLM(), toy_evaluator, LoopConfig(max_generations=8),
                   str(tmp_path / "run"), archive=archive)
    first = fw.evolve("toy")
    assert first["archive_health"]["entries"] >= 2
    assert first["archive_health"]["migration_count"] >= 1
    replay = fw.replay()
    assert replay["main_scores"] == first["main_scores"]
    assert replay["archive_health"] == first["archive_health"]


def test_funsearch_offline_end_to_end(tmp_path):
    from examples.funsearch_offline import run
    out = run(workdir=str(tmp_path), generations=20)
    assert out["best_score"] == 1.0
    assert out["archive_health"]["migration_count"] >= 1
    improves = [f for f in out["funnels"] if f.operator == "improve"]
    assert all(f.applicable == 1 for f in improves)


def test_m3_health_probe_values(tmp_path):
    fw = Framework(MockLLM(), toy_evaluator, LoopConfig(max_generations=10),
                   str(tmp_path))
    out = fw.evolve("toy")
    health = out["health"]
    assert health["effective_budget_ratio"] == 1.0
    assert health["control_fulfillment_ratio"] == pytest.approx(2 / 3)
    assert health["reconcile_delta_ratio"] >= 0.0
    assert health["admitted"] > 0
    assert health["admitted_per_1k_tokens"] > 0
