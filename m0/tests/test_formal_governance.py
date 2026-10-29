"""v28 C3 formal-run residence and C4 certified replay acceptance."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "C3 formal residence and C4 certified replay"


def framework(path, **kwargs):
    values = dict(max_generations=4, baseline_every=2)
    values.update(kwargs)
    return Framework(MockLLM(), toy_evaluator, LoopConfig(**values), str(path))


def test_formal_run_requires_resident_control_without_weakening_c1_c2(tmp_path):
    formal = framework(tmp_path / "formal")
    formal.evolve(TASK)
    inspection = formal.inspect()
    baseline = inspection["governance_audit"]["baseline_residence"]
    assert inspection["governance_pass"] is True
    assert inspection["formal_governance_pass"] is True
    assert inspection["baseline_resident"] is True
    assert baseline["baseline_count"] == baseline["unique_baseline_count"] == 2
    assert baseline["control_spent"] > 0
    assert baseline["baseline_in_frontier"] is False
    assert formal._last_result["governed_state"]["baseline_in_frontier"] is False

    short = framework(tmp_path / "short", max_generations=1, baseline_every=5)
    short.evolve(TASK)
    inspection = short.inspect()
    assert inspection["governance_pass"] is True
    assert inspection["formal_governance_pass"] is False
    assert inspection["baseline_resident"] is False
    assert inspection["governance_audit"]["baseline_residence"]["baseline_count"] == 0


def test_baseline_frontier_leak_and_unspent_control_fail_formal_audit(tmp_path):
    leaked = framework(tmp_path / "leaked")
    leaked.evolve(TASK)
    baseline_id = list(leaked.store.read("baseline"))[0]["payload"]["candidate_id"]
    leaked.store.append("state_mutation", {"op": "add_node", "target": baseline_id})
    inspection = leaked.inspect()
    assert inspection["governance_pass"] is True
    assert inspection["formal_governance_pass"] is False
    assert inspection["governance_audit"]["baseline_residence"][
        "baseline_in_frontier"] is True

    unspent = framework(tmp_path / "unspent", max_generations=1, baseline_every=5)
    unspent.evolve(TASK)
    unspent.store.append("baseline", {"generation": 1, "candidate_id": "forged-control",
                                      "score": 0.25, "main_score": 1.0})
    inspection = unspent.inspect()
    baseline = inspection["governance_audit"]["baseline_residence"]
    assert inspection["governance_pass"] is True
    assert inspection["formal_governance_pass"] is False
    assert baseline["baseline_count"] == 1 and baseline["control_spent"] == 0


def test_successful_replay_certifies_snapshot_receipts_results_and_governance(tmp_path):
    fw = framework(tmp_path / "run")
    original = fw.evolve(TASK)
    replayed = fw.replay()
    certificate = fw.inspect()["replay_certificate"]
    assert fw.inspect()["replay_certified"] is True
    assert certificate["passed"] is True
    for key in ("snapshot_match", "receipt_chain_match", "result_match",
                "original_governance_pass", "replay_governance_pass"):
        assert certificate[key] is True
    assert certificate["snapshot_ref"].startswith("sha256:")
    assert certificate["snapshot_ref"] == certificate["replay_snapshot_ref"]
    assert certificate["receipt_chain_sha256"] == certificate[
        "replay_receipt_chain_sha256"]
    assert replayed["replay_certificate"] == certificate
    assert original["replay_certificate"] == certificate
    assert list(fw.store.read("replay_certificate"))[-1]["payload"] == certificate


def test_replay_score_drift_leaves_failed_certificate_and_raises(tmp_path):
    drift = {"enabled": False}

    def evaluator(candidate_id, head_sha, prompt):
        score = 0.99 if drift["enabled"] else toy_evaluator(
            candidate_id, head_sha, prompt).combined_score
        return EvalResult(candidate_id=candidate_id, head_sha=head_sha,
                          items=[ItemResult("item", 1)], combined_score=score,
                          text_feedback="C4 controlled evaluator",
                          reliability=ReliabilityMeta(n_trials=1))

    fw = Framework(MockLLM(), evaluator, LoopConfig(max_generations=4, baseline_every=2),
                   str(tmp_path / "run"))
    fw.evolve(TASK)
    drift["enabled"] = True
    with pytest.raises(RuntimeError, match="certified replay mismatch"):
        fw.replay()
    inspection = fw.inspect()
    certificate = inspection["replay_certificate"]
    assert inspection["replay_certified"] is False
    assert certificate["passed"] is False
    assert certificate["snapshot_match"] is False
    # This drift changes scores, not the flip-only admission Receipt payloads.
    assert certificate["receipt_chain_match"] is True
    assert certificate["result_match"] is False
    persisted = list(fw.store.read("replay_certificate"))
    assert len(persisted) == 1 and persisted[0]["payload"] == certificate


def test_certified_replay_refuses_runs_without_checkpoint(tmp_path):
    fw = framework(tmp_path / "run", checkpoint_enabled=False)
    fw.evolve(TASK)
    with pytest.raises(RuntimeError, match="integrity-checked checkpoint"):
        fw.replay()
    assert not list(fw.store.read("replay_certificate"))
