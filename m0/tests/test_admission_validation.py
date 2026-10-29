"""Reject malformed per-item evidence before it can authorize admission."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.gate import AdmissionGate
from core.eval.meta_gate import (AnchorCase, EvaluatorMetaGate, EvolutionPreconditions,
                                 HeldOutAnchor)
from core.eval.types import EvalResult, ItemResult, validate_eval_result
from core.x1.store import AppendOnlyStore


def evaluation(candidate_id="candidate", *, verdicts=(1, 0), version="eval-v1"):
    return EvalResult(candidate_id, "head", [ItemResult("a", verdicts[0]),
                                            ItemResult("b", verdicts[1])],
                      evaluator_version=version)


def test_duplicate_candidate_cannot_turn_tie_into_acceptance(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    gate = AdmissionGate(store)
    baseline = evaluation("baseline", verdicts=(0, 1))
    candidate = evaluation()
    # The former implementation counted this as two wins and one loss.
    candidate.items.insert(1, ItemResult("a", 1))
    with pytest.raises(ValueError, match="unique"):
        gate.judge(candidate, baseline)
    assert not list(store.read())


def test_malformed_incumbent_is_validated_before_dictionary_conversion(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    baseline = evaluation("baseline", verdicts=(0, 1))
    baseline.items.append(ItemResult("a", 1))
    with pytest.raises(ValueError, match="unique"):
        AdmissionGate(store).judge(evaluation(), baseline)
    assert not list(store.read())


@pytest.mark.parametrize("items", [
    [ItemResult("a", 1)],
    [ItemResult("a", 1), ItemResult("b", 0), ItemResult("c", 1)],
    [ItemResult("c", 1), ItemResult("d", 1)],
], ids=["subset", "superset", "disjoint"])
def test_final_comparison_requires_exact_sample_universe(tmp_path, items):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    candidate = replace(evaluation(), items=items)
    with pytest.raises(ValueError, match="identical item ids"):
        AdmissionGate(store).judge(candidate, evaluation("baseline", verdicts=(0, 1)))
    assert not list(store.read())


def test_reordered_unique_samples_are_comparable():
    candidate = evaluation()
    candidate.items.reverse()
    assert AdmissionGate.flip_counts(candidate, evaluation("baseline", verdicts=(0, 1))) == (1, 1, 2)


def test_evaluator_version_change_requires_new_comparable_incumbent(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    with pytest.raises(ValueError, match="same evaluator version"):
        AdmissionGate(store).judge(evaluation(version="eval-v2"), evaluation("baseline"))
    assert not list(store.read())


@pytest.mark.parametrize("verdict", [True, False, 0.0, 1.0, -1, 2, "1", None])
def test_binary_evidence_requires_actual_zero_or_one_integers(tmp_path, verdict):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    candidate = evaluation()
    candidate.items[0].verdict = verdict
    with pytest.raises(ValueError, match="binary integers"):
        AdmissionGate(store).judge(candidate, None)
    assert not list(store.read())


@pytest.mark.parametrize("items", [[], None, (ItemResult("a", 1),),
                                    [ItemResult("", 1)], [ItemResult("  ", 1)],
                                    [ItemResult(7, 1)], [{"item_id": "a", "verdict": 1}]])
def test_invalid_item_shapes_and_ids_fail_closed(items):
    with pytest.raises(ValueError):
        validate_eval_result(replace(evaluation(), items=items))


@pytest.mark.parametrize("field", ["candidate_id", "head_sha", "evaluator_version"])
def test_operation_identity_must_be_nonempty_and_match_expected_value(field):
    with pytest.raises(ValueError, match="non-empty string"):
        validate_eval_result(replace(evaluation(), **{field: " "}))
    with pytest.raises(ValueError, match="binding mismatch"):
        validate_eval_result(evaluation(), **{field: "another-operation"})


@pytest.mark.parametrize("mutation", [{"private": None}, {"public": []},
                                      {"private": {"cascade_stopped": "false"}}])
def test_gate_control_metadata_has_typed_schema(mutation):
    with pytest.raises(ValueError):
        validate_eval_result(replace(evaluation(), **mutation))


def test_mutation_after_initial_validation_is_rechecked_at_judgment(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    candidate = validate_eval_result(evaluation(), candidate_id="candidate", head_sha="head",
                                     evaluator_version="eval-v1")
    candidate.items.append(ItemResult("a", 1))
    with pytest.raises(ValueError, match="unique"):
        AdmissionGate(store).judge(candidate, None)
    assert not list(store.read())


@pytest.mark.parametrize("reason", ["cascade", "forced"])
def test_explicit_rejection_can_keep_valid_partial_evidence(tmp_path, reason):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    candidate = replace(evaluation(), items=[ItemResult("a", 0)])
    if reason == "cascade":
        candidate.private["cascade_stopped"] = True
    receipt = AdmissionGate(store).judge(
        candidate, evaluation("baseline"), forced_reject="extension veto" if reason == "forced" else None)
    assert receipt.verdict.kind == "REJECT"
    assert len(list(store.read("receipt"))) == 1


@pytest.mark.parametrize("floor", [float("nan"), float("inf"), -0.1, True, "0"])
def test_direct_gate_rejects_invalid_noise_floor(floor):
    with pytest.raises(ValueError, match="finite non-negative"):
        AdmissionGate(None, noise_floor=floor)


class AnchorEvaluator:
    def __init__(self, version, mutation=None):
        self.evaluator_version = version
        self.mutation = mutation

    def __call__(self, candidate_id, head_sha, _prompt):
        result = evaluation(candidate_id, version=self.evaluator_version)
        result.head_sha = head_sha
        if self.mutation is not None:
            self.mutation(result)
        return result


@pytest.mark.parametrize("target", ["current", "challenger"])
@pytest.mark.parametrize("mutation", [
    lambda result: result.items.append(ItemResult("a", 0)),
    lambda result: setattr(result, "candidate_id", "foreign-candidate"),
    lambda result: setattr(result, "head_sha", "foreign-head"),
    lambda result: setattr(result, "evaluator_version", "undeclared-version"),
], ids=["duplicate-item", "candidate-binding", "head-binding", "version-binding"])
def test_evaluator_promotion_refuses_malformed_anchor_results(tmp_path, target, mutation):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    anchor = HeldOutAnchor("anchor-v1", (AnchorCase("anchor", "head", "task"),))
    gate = EvaluatorMetaGate(anchor, store)
    evidence = EvolutionPreconditions("anchor-v1", True, True, "profile:measurement")
    current = AnchorEvaluator("eval-v1", mutation if target == "current" else None)
    challenger = AnchorEvaluator("eval-v2", mutation if target == "challenger" else None)
    decision = gate.promote(current, challenger, 1, evidence)
    assert decision.accepted is False
    assert "invalid held-out anchor evaluation" in decision.reason
    assert not list(store.read("receipt_invalidation"))
    assert not list(store.read("evaluator_epoch"))
    assert gate.epoch == 0
