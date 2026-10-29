"""Reject invalid loop configuration before provider calls or durable effects."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator


class ForbiddenCall:
    def __init__(self):
        self.calls = 0

    def __call__(self, *_args):
        self.calls += 1
        raise AssertionError("invalid configuration must fail before provider calls")


def assert_rejected_before_effects(tmp_path, config, message, *, mutate=None):
    llm, evaluator = ForbiddenCall(), ForbiddenCall()
    framework = Framework(llm, evaluator, config, str(tmp_path))
    if mutate is not None:
        mutate(framework)
    with pytest.raises(ValueError, match=re.escape(message)):
        framework.evolve("configuration admission test")
    assert llm.calls == evaluator.calls == 0
    assert list(framework.store.read()) == []
    assert not framework.store.path.exists()
    assert not (tmp_path / "checkpoint.json").exists()


INTEGER_FIELDS = {
    "total_budget": 1, "reeval_floor": 0, "intent_cost": 1,
    "baseline_every": 1, "max_generations": 0, "batch_size": 1, "max_inflight": 1,
}


@pytest.mark.parametrize("field,minimum", INTEGER_FIELDS.items())
@pytest.mark.parametrize("invalid", [True, False, 1.5, float("nan"), float("inf"),
                                     float("-inf"), "1", None, []],
                         ids=["true", "false", "fraction", "nan", "inf", "neg-inf",
                              "text", "none", "list"])
def test_integer_fields_reject_invalid_types_before_any_call(tmp_path, field, minimum, invalid):
    qualifier = "positive" if minimum else "non-negative"
    assert_rejected_before_effects(
        tmp_path, LoopConfig(**{field: invalid}),
        f"{field} must be a {qualifier} integer")


@pytest.mark.parametrize("field,minimum", INTEGER_FIELDS.items())
def test_integer_fields_enforce_lower_boundary_before_any_call(tmp_path, field, minimum):
    qualifier = "positive" if minimum else "non-negative"
    assert_rejected_before_effects(
        tmp_path, LoopConfig(**{field: minimum - 1}),
        f"{field} must be a {qualifier} integer")


@pytest.mark.parametrize("field", ["control_share", "noise_floor"])
@pytest.mark.parametrize("invalid", [True, False, float("nan"), float("inf"),
                                     float("-inf"), "0.1", None, [], 10 ** 1000],
                         ids=["true", "false", "nan", "inf", "neg-inf", "text",
                              "none", "list", "overflow"])
def test_numeric_fields_require_finite_numbers(tmp_path, field, invalid):
    assert_rejected_before_effects(
        tmp_path, LoopConfig(**{field: invalid}),
        f"{field} must be a finite non-negative number")


@pytest.mark.parametrize("invalid", [-1, 0, 1, 2])
def test_control_share_requires_open_unit_interval(tmp_path, invalid):
    assert_rejected_before_effects(tmp_path, LoopConfig(control_share=invalid),
                                   "control_share must be in (0,1)")


def test_negative_noise_floor_fails_before_provider_calls(tmp_path):
    assert_rejected_before_effects(tmp_path, LoopConfig(noise_floor=-0.1),
                                   "noise_floor must be a finite non-negative number")


@pytest.mark.parametrize("field", ["checkpoint_enabled", "resume_from_checkpoint"])
@pytest.mark.parametrize("invalid", [0, 1, "false", None, [], float("nan"), float("inf")],
                         ids=["zero", "one", "text", "none", "list", "nan", "inf"])
def test_checkpoint_flags_require_actual_booleans(tmp_path, field, invalid):
    assert_rejected_before_effects(tmp_path, LoopConfig(**{field: invalid}),
                                   f"{field} must be a boolean")


@pytest.mark.parametrize("invalid", [True, False, -1, 1.5, "1", [],
                                     float("nan"), float("inf"), float("-inf")],
                         ids=["true", "false", "negative", "fraction", "text", "list",
                              "nan", "inf", "neg-inf"])
def test_optional_stop_generation_requires_nonnegative_integer(tmp_path, invalid):
    assert_rejected_before_effects(
        tmp_path, LoopConfig(stop_after_generation=invalid),
        "stop_after_generation must be a non-negative integer or None")


def test_reevaluation_reserve_cannot_exceed_entire_budget(tmp_path):
    assert_rejected_before_effects(tmp_path, LoopConfig(total_budget=999, reeval_floor=1000),
                                   "reeval_floor cannot exceed total_budget")


def test_resume_requires_enabled_checkpointing_before_work_begins(tmp_path):
    assert_rejected_before_effects(
        tmp_path, LoopConfig(checkpoint_enabled=False, resume_from_checkpoint=True),
        "resume requires checkpoint_enabled=True")


@pytest.mark.parametrize("field,value,message", [
    ("baseline_every", 0, "baseline_every must be a positive integer"),
    ("max_generations", 1.5, "max_generations must be a non-negative integer"),
    ("intent_cost", 0, "intent_cost must be a positive integer"),
    ("intent_cost", -1, "intent_cost must be a positive integer"),
    ("noise_floor", float("nan"), "noise_floor must be a finite non-negative number"),
    ("checkpoint_enabled", 1, "checkpoint_enabled must be a boolean"),
    ("reeval_floor", 60_001, "reeval_floor cannot exceed total_budget"),
])
def test_mutating_valid_config_after_framework_construction_is_revalidated(
        tmp_path, field, value, message):
    config = LoopConfig()
    config.validate()
    assert_rejected_before_effects(
        tmp_path, config, message,
        mutate=lambda framework: setattr(framework.cfg, field, value))


def test_replacing_configuration_object_is_rejected_before_effects(tmp_path):
    assert_rejected_before_effects(
        tmp_path, LoopConfig(), "config must be a LoopConfig",
        mutate=lambda framework: setattr(framework, "cfg", {}))


@pytest.mark.parametrize("checkpoint_enabled,stop_after_generation", [
    (True, None), (False, None), (True, 0), (False, 0),
])
def test_zero_generations_and_zero_reevaluation_reserve_are_valid(
        tmp_path, checkpoint_enabled, stop_after_generation):
    class CountingLLM(MockLLM):
        calls = 0

        def __call__(self, prompt):
            self.calls += 1
            return super().__call__(prompt)

    class CountingEvaluator:
        calls = 0

        def __call__(self, candidate_id, head_sha, prompt):
            self.calls += 1
            self.last_usage = {"total_tokens": 0}
            return toy_evaluator(candidate_id, head_sha, prompt)

    llm, evaluator = CountingLLM(), CountingEvaluator()
    config = LoopConfig(max_generations=0, reeval_floor=0, noise_floor=0,
                        checkpoint_enabled=checkpoint_enabled,
                        stop_after_generation=stop_after_generation)
    framework = Framework(llm, evaluator, config, str(tmp_path))
    result = framework.evolve("valid genesis only")
    assert result["completed"] is (stop_after_generation is None)
    assert llm.calls == evaluator.calls == 1
    assert framework.inspect()["governance_pass"] is True
    assert len(list(framework.store.read("receipt"))) == 1


def test_positive_minima_and_full_reevaluation_reserve_are_valid_configuration():
    # Configuration validation permits these documented edges, even when there
    # is no free operational budget for a subsequent proposal.
    LoopConfig(total_budget=1, reeval_floor=1, intent_cost=1, baseline_every=1,
               max_generations=0, batch_size=1, max_inflight=1).validate()
