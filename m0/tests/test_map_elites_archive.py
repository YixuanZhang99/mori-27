"""v49 MAP-Elites feature-grid archive, profile, checkpoint and replay acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.gate import AdmissionGate
from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.loop import Framework, LoopConfig
from core.map_elites import FeatureDimension, MapElitesArchive
from core.x1.store import AppendOnlyStore

TASK = "MAP-Elites governed prompt research"
COMPARE = ("best_prompt", "best_score", "self_attestation", "governance_audit",
           "main_scores", "baseline_scores", "accepted_candidate_ids", "generations",
           "ledger", "health", "archive_health", "governed_state")


def dimensions():
    return [FeatureDimension("novelty", 0.0, 1.0, 2),
            FeatureDimension("complexity", 0.0, 10.0, 3)]


def candidate(cid, score, novelty, complexity):
    return {"candidate_id": cid, "score": score, "prompt": cid,
            "result": SimpleNamespace(public={"features": {
                "novelty": novelty, "complexity": complexity}})}


def test_dimension_binning_clipping_and_invalid_values():
    dimension = FeatureDimension("x", -1.0, 1.0, 4)
    assert [dimension.index(value) for value in (-2, -1, -0.5, 0, 0.999, 1, 2)] \
        == [0, 0, 1, 2, 3, 3, 3]
    for value in (True, float("nan"), float("inf"), "0"):
        with pytest.raises(ValueError, match="finite number"):
            dimension.index(value)
    for payload in ({"name": "", "lower": 0, "upper": 1, "bins": 2},
                    {"name": "x", "lower": 1, "upper": 1, "bins": 2},
                    {"name": "x", "lower": 0, "upper": 1, "bins": True},
                    {"name": "x", "lower": 0, "upper": 1}):
        with pytest.raises(ValueError):
            FeatureDimension.from_dict(payload)


def test_unique_dimensions_and_public_feature_contract():
    with pytest.raises(ValueError, match="unique"):
        MapElitesArchive([FeatureDimension("x", 0, 1, 2),
                          FeatureDimension("x", 0, 1, 3)])
    archive = MapElitesArchive(dimensions())
    with pytest.raises(ValueError, match="missing: complexity"):
        archive.register({"candidate_id": "a", "score": 0.1,
                          "result": SimpleNamespace(public={"features": {"novelty": 0.2}})}, 0)
    with pytest.raises(ValueError, match="lacks public"):
        archive.register({"candidate_id": "b", "score": 0.2,
                          "result": SimpleNamespace(public={})}, 0)


def test_one_elite_per_cell_and_history_preserving_replacement():
    archive = MapElitesArchive(dimensions())
    low = candidate("low", 0.2, 0.1, 1.0)
    high = candidate("high", 0.8, 0.2, 2.0)
    other = candidate("other", 0.4, 0.9, 8.0)
    archive.register(low, 0)
    archive.register(high, 1)
    archive.register(other, 2)
    assert archive.cells == {(0, 0): "high", (1, 2): "other"}
    assert set(archive.entries) == {"low", "high", "other"}
    assert archive.replacement_count == 1
    assert archive.select_parent([low, high, other], 0)["candidate_id"] == "high"
    assert archive.select_parent([low, high, other], 1)["candidate_id"] == "other"
    assert archive.select_parent([low, high, other], 2)["candidate_id"] == "high"
    with pytest.raises(ValueError, match="duplicate"):
        archive.register(high, 3)


def test_equal_score_tiebreak_and_out_of_range_features_are_deterministic():
    archive = MapElitesArchive(dimensions())
    archive.register(candidate("a", 0.5, -5, 99), 0)
    archive.register(candidate("b", 0.5, 5, -99), 0)
    assert archive.cells == {(0, 2): "a", (1, 0): "b"}
    archive.register(candidate("c", 0.5, 5, -99), 1)
    assert archive.cells[(1, 0)] == "c"
    assert archive.replacement_count == 1


def test_soft_eviction_removes_only_current_elite_from_selection():
    archive = MapElitesArchive(dimensions())
    a, b = candidate("a", 0.2, 0.1, 1), candidate("b", 0.8, 0.1, 1)
    archive.register(a, 0)
    archive.register(b, 1)
    entry = archive.evict("b", "quality review")
    assert entry.soft_deleted and not entry.parent_eligible and not entry.deliver_eligible
    assert archive.entries["b"].eviction_reason == "quality review"
    assert archive.cells == {}
    assert archive.health()["soft_deleted"] == 1
    with pytest.raises(RuntimeError, match="no eligible"):
        archive.select_parent([a, b], 0)
    with pytest.raises(ValueError, match="reason"):
        archive.evict("a", "")


def test_checkpoint_roundtrip_and_fork_have_exact_independent_state():
    archive = MapElitesArchive(dimensions())
    archive.register(candidate("a", 0.2, 0.1, 1), 0)
    archive.register(candidate("b", 0.8, 0.1, 1), 1)
    archive.register(candidate("c", 0.4, 0.9, 8), 2)
    state = archive.checkpoint_state()
    restored = MapElitesArchive(dimensions())
    restored.restore_state(deepcopy(state))
    assert restored.checkpoint_state() == state
    assert restored.health() == archive.health()
    fork = archive.fork()
    assert fork.configuration() == archive.configuration()
    assert fork.entries == {} and fork.cells == {}


def test_checkpoint_tampering_and_topology_mismatch_fail_closed():
    archive = MapElitesArchive(dimensions())
    archive.register(candidate("a", 0.2, 0.1, 1), 0)
    archive.register(candidate("b", 0.8, 0.1, 1), 1)
    state = archive.checkpoint_state()
    wrong_elite = deepcopy(state)
    wrong_elite["cells"][0]["candidate_id"] = "a"
    with pytest.raises(ValueError, match="deterministic maximum"):
        MapElitesArchive(dimensions()).restore_state(wrong_elite)
    wrong_cell = deepcopy(state)
    wrong_cell["entries"][0]["cell"] = [1, 2]
    with pytest.raises(ValueError):
        MapElitesArchive(dimensions()).restore_state(wrong_cell)
    with pytest.raises(ValueError, match="topology"):
        MapElitesArchive([FeatureDimension("x", 0, 1, 2)]).restore_state(state)
    with pytest.raises(ValueError, match="schema"):
        MapElitesArchive(dimensions()).restore_state({"kind": "map_elites"})


class LevelLLM:
    """Stateless draft/improve load whose prompt encodes a deterministic level."""

    def __call__(self, prompt):
        self.last_usage = {"total_tokens": 1000}
        if prompt.startswith("[draft"):
            return "level=1"
        match = re.search(r"CURRENT PROMPT:\nlevel=(\d+)", prompt)
        assert match, prompt
        return f"level={int(match.group(1)) + 1}"


class LevelEvaluator:
    """Prompt-only scoring supports independent resume and fresh replay."""

    def __call__(self, candidate_id, head_sha, prompt):
        self.last_usage = {"total_tokens": 0}
        match = re.fullmatch(r"level=(\d+)", prompt)
        assert match, prompt
        solved = min(12, int(match.group(1)))
        digest = hashlib.sha256(candidate_id.encode()).digest()
        items = [ItemResult(f"item_{index}", int(index < solved)) for index in range(12)]
        return EvalResult(candidate_id, head_sha, items, solved / 12,
                          public={"features": {"novelty": digest[0] / 255,
                                               "complexity": digest[1] / 25.5}},
                          text_feedback="continue", reliability=ReliabilityMeta(1, noise_floor=0.0))


def framework(path, *, stop=None, resume=False, generations=8, batch_size=1):
    config = LoopConfig(max_generations=generations, baseline_every=3, batch_size=batch_size,
                        max_inflight=batch_size, stop_after_generation=stop,
                        resume_from_checkpoint=resume)
    return Framework.from_profile("map_elites_grid", LevelLLM(), LevelEvaluator(),
                                  config, str(path))


def test_profile_framework_checkpoint_resume_and_certified_replay(tmp_path):
    reference = framework(tmp_path / "reference")
    expected = reference.evolve(TASK)
    assert expected["archive_health"]["kind"] == "map_elites"
    assert expected["archive_health"]["occupied_cells"] >= 2
    interrupted_dir = tmp_path / "interrupted"
    partial = framework(interrupted_dir, stop=3).evolve(TASK)
    assert partial["completed"] is False
    payload = json.loads((interrupted_dir / "checkpoint.json").read_text())["payload"]
    assert payload["archive"]["kind"] == "map_elites"
    assert len(payload["archive"]["dimensions"]) == 2
    resumed_fw = framework(interrupted_dir, resume=True)
    resumed = resumed_fw.evolve(TASK)
    for key in COMPARE:
        assert resumed[key] == expected[key], key
    replay = resumed_fw.replay()
    for key in COMPARE:
        assert replay[key] == expected[key], key
    assert replay["replay_certificate"]["passed"] is True


def test_batch_cohorts_use_the_same_grid_without_changing_admission(tmp_path):
    fw = framework(tmp_path / "batch", generations=5, batch_size=2)
    result = fw.evolve(TASK)
    assert result["archive_health"]["kind"] == "map_elites"
    assert result["archive_health"]["occupied_cells"] >= 2
    assert result["governance_audit"]["passed"] is True
    replay = fw.replay()
    for key in COMPARE:
        assert replay[key] == result[key], key
    accepted = set(result["accepted_candidate_ids"])
    for row in fw.store.read("gate_evidence"):
        payload = row["payload"]
        if payload["rule_id"].startswith("flip_count") \
                and payload["candidate_id"] in accepted:
            assert payload["signals_snapshot"]["F"] > payload["signals_snapshot"]["B"]


def test_m9_verdict_is_flip_only_under_feature_and_score_mutation(tmp_path):
    incumbent = EvalResult("base", "head", [ItemResult("x", 0), ItemResult("y", 1)],
                           combined_score=0.9,
                           public={"features": {"novelty": 0.0, "complexity": 0.0}})
    winner = EvalResult("winner", "head", [ItemResult("x", 1), ItemResult("y", 1)],
                        combined_score=-999,
                        public={"features": {"novelty": 1.0, "complexity": 10.0}})
    loser = EvalResult("loser", "head", [ItemResult("x", 0), ItemResult("y", 0)],
                       combined_score=999,
                       public={"features": {"novelty": 1.0, "complexity": 10.0}})
    gate = AdmissionGate(AppendOnlyStore(tmp_path / "gate.jsonl"))
    assert gate.evaluate(winner, incumbent)[0].verdict.kind == "ACCEPT"
    assert gate.evaluate(loser, incumbent)[0].verdict.kind == "REJECT"
    for result in (winner, loser):
        evidence = gate.evaluate(result, incumbent)[1]
        assert evidence.signals_snapshot["N"] == 2
        assert "features" not in evidence.signals_snapshot


def test_feature_metadata_never_enters_m9_and_completed_resume_is_noop(tmp_path):
    run_dir = tmp_path / "run"
    fw = framework(run_dir, generations=4)
    result = fw.evolve(TASK)
    for row in fw.store.read("gate_evidence"):
        assert set(row["payload"]["signals_snapshot"]) == {"F", "B", "N", "noise_floor"}
        assert "features" not in row["payload"]["signals_snapshot"]
    receipts = len(list(fw.store.read("receipt")))
    archive = fw._last_result["archive_health"]
    resumed = framework(run_dir, resume=True, generations=4).evolve(TASK)
    assert resumed["archive_health"] == archive
    assert len(list(resumed["funnels"])) == len(result["funnels"])
    resumed_fw = framework(run_dir, resume=True, generations=4)
    # A second completed resume uses the same evidence history and adds no Receipt.
    resumed_fw.evolve(TASK)
    assert len(list(resumed_fw.store.read("receipt"))) == receipts
