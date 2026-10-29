"""M8/M9 extension behavior: cascade, judge quality and evaluator meta-gate."""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.cascade import CascadingEvaluator
from core.eval.gate import AdmissionGate
from core.eval.judge import IsotonicCalibrator, cohens_kappa, position_swap_probe
from core.eval.meta_gate import (AnchorCase, EvaluatorMetaGate, EvoEvaluatorChannel,
                                 EvolutionPreconditions, HeldOutAnchor)
from core.eval.types import EvalResult, ItemResult
from core.x1.store import AppendOnlyStore


class TieredEvaluator:
    evaluator_version = "tiered-det-v1"

    def __init__(self):
        self.last_usage = {"total_tokens": 0}
        self.calls = []

    def __call__(self, candidate_id, head_sha, prompt, item_limit=None):
        self.calls.append((prompt, item_limit))
        verdicts = [1, 1, 1] if prompt == "good" else [0, 0, 0]
        if item_limit is not None:
            verdicts = verdicts[:item_limit]
        self.last_usage = {"total_tokens": 2 * len(verdicts)}
        return EvalResult(candidate_id, head_sha,
                          [ItemResult(f"i{i}", v) for i, v in enumerate(verdicts)],
                          combined_score=sum(verdicts) / len(verdicts),
                          evaluator_version=self.evaluator_version)


def test_cascade_escalates_good_and_stops_bad_with_metering(tmp_path):
    base = TieredEvaluator()
    cascade = CascadingEvaluator(base, shallow_items=1)
    good = cascade("g", "sha", "good")
    bad = cascade("b", "sha", "bad")
    assert good.public["tier"] == "full" and good.private["cascade_stopped"] is False
    assert bad.public["tier"] == "shallow" and bad.private["cascade_stopped"] is True
    assert len(bad.items) == 1 and cascade.last_usage["total_tokens"] == 2
    assert (cascade.shallow_count, cascade.full_count) == (2, 1)
    gate = AdmissionGate(AppendOnlyStore(tmp_path / "x1.jsonl"))
    receipt = gate.judge(bad, good)
    assert receipt.verdict.kind == "REJECT"
    assert receipt.verdict.rationale_ref == "cascade stopped before full evaluation"


def test_position_swap_kappa_and_isotonic_are_deterministic():
    consistent = lambda a, b: "a" if a > b else "b"
    positional = lambda a, b: "a"
    assert position_swap_probe(consistent, [("b", "a"), ("c", "b")])["accepted"]
    assert not position_swap_probe(positional, [("b", "a"), ("c", "b")],
                                   max_flip_rate=0.2)["accepted"]
    assert cohens_kappa([1, 0, 1, 0], [1, 1, 1, 0]) == pytest.approx(0.5)
    calibrator = IsotonicCalibrator().fit([0, 1, 2, 3], [0, 1, 0, 1])
    assert [calibrator.predict(x) for x in [0, 1, 2, 3]] == [0, 0.5, 0.5, 1]


class AnchorEvaluator:
    def __init__(self, version, second_verdict):
        self.evaluator_version = version
        self.second_verdict = second_verdict
        self.last_usage = {"total_tokens": 0}

    def __call__(self, candidate_id, head_sha, prompt):
        return EvalResult(candidate_id, head_sha,
                          [ItemResult("a0", 1), ItemResult("a1", self.second_verdict)],
                          combined_score=(1 + self.second_verdict) / 2,
                          evaluator_version=self.evaluator_version)


def evidence(anchor_id="heldout-v1"):
    return EvolutionPreconditions(anchor_ref=anchor_id, meta_gate_enabled=True,
                                  cascade_invalidation_ready=True,
                                  bottleneck_evidence_ref="profile:evaluator-bound")


def mk_meta(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    anchor = HeldOutAnchor("heldout-v1", (AnchorCase("anchor", "sha", "task"),))
    gate = EvaluatorMetaGate(anchor, store)
    current = AnchorEvaluator("eval-v1", 0)
    admission = AdmissionGate(store)
    old_receipt = admission.judge(current("old-candidate", "sha", "task"), None)
    return store, gate, current, old_receipt


def test_meta_gate_rejects_regression_and_preserves_old_receipt(tmp_path):
    store, gate, current, old = mk_meta(tmp_path)
    # A regressive evaluator loses the first anchor item.
    class Regressive(AnchorEvaluator):
        def __call__(self, candidate_id, head_sha, prompt):
            return EvalResult(candidate_id, head_sha,
                              [ItemResult("a0", 0), ItemResult("a1", 1)],
                              evaluator_version=self.evaluator_version)
    decision = gate.promote(current, Regressive("eval-v2-bad", 1), 1, evidence())
    assert not decision.accepted and not decision.invalidated_receipt_ids
    assert gate.is_receipt_valid(old.receipt_id)
    assert len(list(store.read("receipt"))) == 1
    assert not list(store.read("receipt_invalidation"))


def test_meta_gate_promotion_cascades_soft_invalidation_only(tmp_path):
    store, gate, current, old = mk_meta(tmp_path)
    challenger = AnchorEvaluator("eval-v2", 1)
    decision = gate.promote(current, challenger, 1, evidence())
    assert decision.accepted and decision.invalidated_receipt_ids == [old.receipt_id]
    assert not gate.is_receipt_valid(old.receipt_id)
    assert gate.active_version == "eval-v2" and gate.epoch == 1
    assert len(list(store.read("receipt"))) == 1  # hard evidence survives
    assert len(list(store.read("receipt_invalidation"))) == 1
    stale = gate.promote(challenger, AnchorEvaluator("eval-v3", 1), 1, evidence())
    assert not stale.accepted and "epoch boundary" in stale.reason


@pytest.mark.parametrize("field,value", [
    ("anchor_ref", "wrong-anchor"),
    ("meta_gate_enabled", False),
    ("cascade_invalidation_ready", False),
    ("bottleneck_evidence_ref", ""),
])
def test_evo_evaluator_requires_all_four_preconditions(tmp_path, field, value):
    _, gate, current, old = mk_meta(tmp_path)
    channel = EvoEvaluatorChannel(gate, enabled=True)
    decision = channel.promote(current, AnchorEvaluator("eval-v2", 1), 1,
                               replace(evidence(), **{field: value}))
    assert not decision.accepted and "missing preconditions" in decision.reason
    assert gate.is_receipt_valid(old.receipt_id)


def test_evo_evaluator_channel_is_closed_by_default(tmp_path):
    _, gate, current, _ = mk_meta(tmp_path)
    decision = EvoEvaluatorChannel(gate).promote(
        current, AnchorEvaluator("eval-v2", 1), 1, evidence())
    assert not decision.accepted and "disabled by default" in decision.reason
