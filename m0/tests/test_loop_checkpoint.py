"""Framework cycle checkpoint/resume drills against uninterrupted controls."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.archive import IslandArchive
from core.extensions import H2MonitorExtension
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "checkpointed toy research"
COMPARE = ("best_prompt", "best_score", "self_attestation", "governance_audit",
           "main_scores", "baseline_scores",
           "accepted_candidate_ids", "generations", "ledger", "health",
           "archive_health")


def config(stop=None, resume=False, generations=8):
    return LoopConfig(max_generations=generations, baseline_every=2,
                      checkpoint_enabled=True, resume_from_checkpoint=resume,
                      stop_after_generation=stop)


def assert_same_run(actual, expected):
    for key in COMPARE:
        assert actual[key] == expected[key], key


def test_interrupted_framework_resume_matches_uninterrupted_control(tmp_path):
    reference = Framework(MockLLM(), toy_evaluator, config(), str(tmp_path / "reference"))
    expected = reference.evolve(TASK)

    interrupted_dir = tmp_path / "interrupted"
    partial_fw = Framework(MockLLM(), toy_evaluator, config(stop=3), str(interrupted_dir))
    partial = partial_fw.evolve(TASK)
    assert partial["completed"] is False and partial["next_generation"] == 4
    checkpoint = json.loads((interrupted_dir / "checkpoint.json").read_text())
    assert checkpoint["schema_version"] == 1
    assert checkpoint["payload"]["next_generation"] == 4
    assert checkpoint["payload"]["inflight_executor"] == []
    assert not (interrupted_dir / "checkpoint.json.tmp").exists()

    resumed_fw = Framework(MockLLM(), toy_evaluator, config(resume=True), str(interrupted_dir))
    resumed = resumed_fw.evolve(TASK)
    assert resumed["completed"] is True and resumed["resumed"] is True
    assert_same_run(resumed, expected)
    assert len(list(resumed_fw.store.read("run_start"))) == 1
    assert len(list(resumed_fw.store.read("run_resume"))) == 1
    genesis = [record for record in resumed_fw.store.read("gate_evidence")
               if record["payload"]["rule_id"] == "genesis"]
    assert len(genesis) == 1
    replay = resumed_fw.replay()
    assert_same_run(replay, expected)


def test_island_archive_and_h2_extension_state_resume_without_drift(tmp_path):
    def framework(path, cfg):
        return Framework(MockLLM(), toy_evaluator, cfg, str(path),
                         extensions=[H2MonitorExtension(window=3, min_effective_parents=2)],
                         archive=IslandArchive(num_islands=2, migration_interval=2))

    expected_fw = framework(tmp_path / "island-reference", config())
    expected = expected_fw.evolve(TASK)
    partial_fw = framework(tmp_path / "island-resume", config(stop=3))
    partial_fw.evolve(TASK)
    resumed_fw = framework(tmp_path / "island-resume", config(resume=True))
    resumed = resumed_fw.evolve(TASK)
    assert_same_run(resumed, expected)
    expected_alarms = [r["payload"] for r in expected_fw.store.read("extension_alarm")]
    resumed_alarms = [r["payload"] for r in resumed_fw.store.read("extension_alarm")]
    assert resumed_alarms == expected_alarms
    assert resumed["archive_health"]["migration_count"] >= 1


def test_completed_checkpoint_resume_is_a_noop_for_search_and_receipts(tmp_path):
    run_dir = tmp_path / "complete"
    first_fw = Framework(MockLLM(), toy_evaluator, config(generations=4), str(run_dir))
    first = first_fw.evolve(TASK)
    receipts = len(list(first_fw.store.read("receipt")))
    resumed_fw = Framework(MockLLM(), toy_evaluator,
                           config(resume=True, generations=4), str(run_dir))
    resumed = resumed_fw.evolve(TASK)
    assert_same_run(resumed, first)
    assert len(list(resumed_fw.store.read("receipt"))) == receipts
    assert len(list(resumed_fw.store.read("run_checkpoint"))) == 5


def test_checkpoint_integrity_task_and_config_mismatch_are_refused(tmp_path):
    run_dir = tmp_path / "refusals"
    fw = Framework(MockLLM(), toy_evaluator, config(stop=1), str(run_dir))
    fw.evolve(TASK)
    path = run_dir / "checkpoint.json"
    original = path.read_bytes()

    tampered = json.loads(original)
    tampered["payload"]["main_scores"][0] = 999
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="integrity"):
        Framework(MockLLM(), toy_evaluator, config(resume=True), str(run_dir)).evolve(TASK)

    path.write_bytes(original)
    with pytest.raises(ValueError, match="LoopConfig"):
        Framework(MockLLM(), toy_evaluator,
                  config(resume=True, generations=9), str(run_dir)).evolve(TASK)
    with pytest.raises(ValueError, match="task/profile"):
        Framework(MockLLM(), toy_evaluator, config(resume=True), str(run_dir)).evolve("other task")
    with pytest.raises(ValueError, match="checkpoint_enabled"):
        Framework(MockLLM(), toy_evaluator,
                  LoopConfig(resume_from_checkpoint=True, checkpoint_enabled=False),
                  str(run_dir)).evolve(TASK)
