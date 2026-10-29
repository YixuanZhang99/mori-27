"""B9/N2 evaluator-change governance: frozen anchors, meta-gate, soft invalidation.

The anchor is an external, immutable evaluation input. A challenger must not lose
on any anchor item; aggregate scores cannot authorize promotion. Passing a change
appends invalidation records for every old receipt while preserving hard evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from core.eval.types import validate_eval_result
from core.x1.store import AppendOnlyStore


@dataclass(frozen=True)
class AnchorCase:
    candidate_id: str
    head_sha: str
    prompt: str


@dataclass(frozen=True)
class HeldOutAnchor:
    anchor_id: str
    cases: tuple[AnchorCase, ...]

    def __post_init__(self):
        if not self.anchor_id or not self.cases:
            raise ValueError("a held-out anchor requires an id and at least one case")

    @property
    def digest(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvolutionPreconditions:
    """All four gates are evidence-bearing; True/empty values cannot be inferred."""
    anchor_ref: str
    meta_gate_enabled: bool
    cascade_invalidation_ready: bool
    bottleneck_evidence_ref: str

    def missing(self, expected_anchor: str) -> list[str]:
        missing = []
        if self.anchor_ref != expected_anchor:
            missing.append("held_out_anchor")
        if not self.meta_gate_enabled:
            missing.append("meta_gate")
        if not self.cascade_invalidation_ready:
            missing.append("cascade_invalidation")
        if not self.bottleneck_evidence_ref:
            missing.append("measured_evaluator_bottleneck")
        return missing


@dataclass
class MetaGateDecision:
    accepted: bool
    epoch: int
    old_version: str
    new_version: str
    reason: str
    invalidated_receipt_ids: list[str]


class EvaluatorMetaGate:
    def __init__(self, anchor: HeldOutAnchor, store: AppendOnlyStore):
        self.anchor = anchor
        self.store = store
        self.epoch = 0
        self.active_version = ""
        self.invalidated_receipt_ids: set[str] = set()
        self.store.append("anchor_registration", {
            "anchor_id": anchor.anchor_id, "digest": anchor.digest,
            "cases": [asdict(case) for case in anchor.cases]})

    def _decision(self, accepted: bool, epoch: int, old: str, new: str,
                  reason: str, invalidated: list[str] | None = None) -> MetaGateDecision:
        decision = MetaGateDecision(accepted, epoch, old, new, reason, invalidated or [])
        self.store.append("meta_gate", asdict(decision))
        return decision

    def promote(self, current_evaluator, challenger_evaluator, epoch: int,
                evidence: EvolutionPreconditions) -> MetaGateDecision:
        old = getattr(current_evaluator, "evaluator_version", "")
        new = getattr(challenger_evaluator, "evaluator_version", "")
        if not old or not new or old == new:
            return self._decision(False, epoch, old, new,
                                  "distinct pinned evaluator versions required")
        if epoch <= self.epoch:
            return self._decision(False, epoch, old, new,
                                  "evaluator changes only at a later epoch boundary")
        missing = evidence.missing(self.anchor.anchor_id)
        if missing:
            return self._decision(False, epoch, old, new,
                                  "missing preconditions: " + ",".join(missing))

        comparisons = []
        regressions = []
        for case in self.anchor.cases:
            try:
                before = validate_eval_result(
                    current_evaluator(case.candidate_id, case.head_sha, case.prompt),
                    candidate_id=case.candidate_id, head_sha=case.head_sha,
                    evaluator_version=old)
                after = validate_eval_result(
                    challenger_evaluator(case.candidate_id, case.head_sha, case.prompt),
                    candidate_id=case.candidate_id, head_sha=case.head_sha,
                    evaluator_version=new)
            except ValueError as error:
                return self._decision(False, epoch, old, new,
                                      f"invalid held-out anchor evaluation: {error}")
            old_items = {item.item_id: item.verdict for item in before.items}
            new_items = {item.item_id: item.verdict for item in after.items}
            if set(old_items) != set(new_items):
                regressions.append(f"{case.candidate_id}:item_coverage")
                continue
            for item_id in sorted(old_items):
                delta = new_items[item_id] - old_items[item_id]
                comparisons.append({"case": case.candidate_id, "item_id": item_id,
                                    "old": old_items[item_id], "new": new_items[item_id]})
                if delta < 0:
                    regressions.append(f"{case.candidate_id}:{item_id}")
        self.store.append("anchor_regression", {
            "epoch": epoch, "anchor_id": self.anchor.anchor_id,
            "anchor_digest": self.anchor.digest, "old_version": old,
            "new_version": new, "comparisons": comparisons,
            "regressions": regressions})
        if regressions:
            return self._decision(False, epoch, old, new,
                                  "held-out anchor regression: " + ",".join(regressions))

        invalidated = []
        for record in self.store.read("receipt"):
            receipt = record["payload"]
            if receipt.get("evaluator_version") != old:
                continue
            receipt_id = receipt["receipt_id"]
            invalidated.append(receipt_id)
            self.invalidated_receipt_ids.add(receipt_id)
            event = {"receipt_id": receipt_id, "from_evaluator": old,
                     "to_evaluator": new, "epoch": epoch,
                     "reason": "evaluator promotion; soft evidence invalidated"}
            self.store.append("receipt_invalidation", event)
            self.store.append("gate_evidence", {
                "candidate_id": "", "receipt_id": receipt_id,
                "transition": "invalidate:evaluator_version",
                "rule_id": "meta_gate_epoch_boundary", "signals_snapshot": event})
        self.epoch = epoch
        self.active_version = new
        self.store.append("evaluator_epoch", {
            "epoch": epoch, "active_version": new,
            "anchor_id": self.anchor.anchor_id, "anchor_digest": self.anchor.digest})
        return self._decision(True, epoch, old, new, "anchor non-regression passed",
                              invalidated)

    def is_receipt_valid(self, receipt_id: str) -> bool:
        return receipt_id not in self.invalidated_receipt_ids


class EvoEvaluatorChannel:
    """Opt-in evolutionary evaluator channel; closed unless explicitly installed."""

    def __init__(self, meta_gate: EvaluatorMetaGate, enabled: bool = False):
        self.meta_gate = meta_gate
        self.enabled = enabled

    def promote(self, current_evaluator, challenger_evaluator, epoch: int,
                evidence: EvolutionPreconditions) -> MetaGateDecision:
        if not self.enabled:
            old = getattr(current_evaluator, "evaluator_version", "")
            new = getattr(challenger_evaluator, "evaluator_version", "")
            return self.meta_gate._decision(
                False, epoch, old, new, "EvoEvaluator channel is disabled by default")
        return self.meta_gate.promote(current_evaluator, challenger_evaluator,
                                      epoch, evidence)
