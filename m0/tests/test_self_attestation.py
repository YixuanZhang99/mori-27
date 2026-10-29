"""v25 B1 terminal self-attestation: strict increment over resident IID-RS."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM

TASK = "B1 honest terminal self-attestation"


def run_case(tmp_path, main_score, control_scores, noise_floor,
             max_generations=2, baseline_every=1):
    probe = Framework(MockLLM(), None, LoopConfig(), str(tmp_path / "probe"))
    controls = {probe._proposal_id(TASK, f"control:{generation}"): score
                for generation, score in enumerate(control_scores, start=1)}
    evaluator_calls = []

    def evaluator(candidate_id, head_sha, _prompt):
        evaluator.last_usage = {"total_tokens": 0}
        evaluator_calls.append(candidate_id)
        score = controls.get(candidate_id, main_score)
        return EvalResult(candidate_id=candidate_id, head_sha=head_sha,
                          items=[ItemResult("item", 1)], combined_score=score,
                          text_feedback="controlled B1 fixture",
                          reliability=ReliabilityMeta(n_trials=1))

    fw = Framework(MockLLM(), evaluator,
                   LoopConfig(max_generations=max_generations,
                              baseline_every=baseline_every, noise_floor=noise_floor),
                   str(tmp_path / "run"))
    out = fw.evolve(TASK)
    assert out["baseline_scores"] == list(control_scores[:max_generations // baseline_every])
    assert evaluator_calls
    return fw, fw.inspect()


@pytest.mark.parametrize("main,controls,floor,verdict,passed,increment", [
    # The old all-baselines-below-best rule rejects this; the B1 mean increment passes.
    (0.875, [0.25, 0.75], 0.25, "PASS", True, 0.375),
    (0.75, [0.25, 0.25], 0.5, "INADJUDICABLE", False, 0.5),
    (0.5, [0.5, 0.5], 0.0, "INADJUDICABLE", False, 0.0),
    (0.375, [0.5, 0.5], 0.25, "INADJUDICABLE", False, -0.125),
    (0.125, [0.75, 0.75], 0.25, "FAIL", False, -0.625),
])
def test_b1_verdict_uses_mean_increment_and_strict_noise_floor(
        tmp_path, main, controls, floor, verdict, passed, increment):
    fw, inspection = run_case(tmp_path, main, controls, floor)
    evidence = inspection["self_attestation"]
    assert evidence["verdict"] == verdict
    assert inspection["self_attestation_pass"] is passed
    assert evidence["baseline_count"] == len(controls)
    assert evidence["baseline_mean"] == pytest.approx(sum(controls) / len(controls))
    assert evidence["best_score"] == main
    assert evidence["increment"] == pytest.approx(increment)
    assert evidence["noise_floor"] == floor
    assert evidence["noise_floor_source"] == "LoopConfig.noise_floor"
    assert evidence["comparison"] == "best_score_minus_iid_rs_mean"
    persisted = list(fw.store.read("self_attestation"))
    assert len(persisted) == 1 and persisted[0]["payload"] == evidence


def test_b1_missing_resident_baseline_is_insufficient_not_a_pass(tmp_path):
    fw, inspection = run_case(tmp_path, 1.0, [], 0.0,
                              max_generations=1, baseline_every=5)
    evidence = inspection["self_attestation"]
    assert evidence["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert evidence["baseline_count"] == 0
    assert evidence["baseline_mean"] is None
    assert evidence["increment"] is None
    assert inspection["self_attestation_pass"] is False
    assert list(fw.store.read("self_attestation"))[0]["payload"] == evidence


@pytest.mark.parametrize("floor", [-0.1, math.nan, math.inf, -math.inf, True, "0"])
def test_b1_noise_floor_must_be_finite_nonnegative_number(tmp_path, floor):
    fw = Framework(MockLLM(), lambda *_args: None,
                   LoopConfig(noise_floor=floor), str(tmp_path))
    with pytest.raises(ValueError, match="noise_floor must be a finite non-negative number"):
        fw.evolve(TASK)
    assert not list(fw.store.read("run_start"))
    assert not list(fw.store.read("self_attestation"))
