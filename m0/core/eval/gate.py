"""M9 gate (M0): flip_count + noise_floor_zero only. Deterministic adjudication.
Aggregate scores, public feedback and trajectory text are unreachable here (B2/分歧2).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict

from core.eval.types import (EvalResult, GateEvidenceRecord, ItemResult, Receipt, Verdict,
                            validate_eval_comparison, validate_eval_result)
from core.x1.store import AppendOnlyStore


def _binary_snapshot(result: EvalResult) -> dict:
    """Freeze only admissible evidence, independently of mutable transport objects."""
    return {
        "candidate_id": result.candidate_id,
        "head_sha": result.head_sha,
        "evaluator_version": result.evaluator_version,
        "evaluation_context": result.evaluation_context,
        "items": [{"item_id": item.item_id, "verdict": item.verdict}
                  for item in sorted(result.items, key=lambda item: item.item_id)],
        "cascade_stopped": result.private.get("cascade_stopped", False),
    }


def _context_id(context: dict) -> str:
    encoded = json.dumps(context, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _restore_binary_snapshot(snapshot: dict) -> EvalResult:
    expected = {"candidate_id", "head_sha", "evaluator_version", "evaluation_context",
                "items", "cascade_stopped"}
    if not isinstance(snapshot, dict) or set(snapshot) != expected:
        raise ValueError("invalid receipt evidence snapshot")
    items = snapshot["items"]
    if not isinstance(items, list) or any(
            not isinstance(item, dict) or set(item) != {"item_id", "verdict"}
            for item in items):
        raise ValueError("invalid receipt item snapshot")
    return validate_eval_result(EvalResult(
        snapshot["candidate_id"], snapshot["head_sha"],
        [ItemResult(item["item_id"], item["verdict"]) for item in items],
        private={"cascade_stopped": snapshot["cascade_stopped"]},
        evaluator_version=snapshot["evaluator_version"],
        evaluation_context=snapshot["evaluation_context"]))


def validate_receipt_evidence(receipt: dict, evidence: dict) -> None:
    """Rebuild a versioned decision from its immutable context without writing it."""
    if not isinstance(evidence, dict):
        raise ValueError("invalid gate evidence schema")
    context = evidence.get("decision_context")
    if not isinstance(context, dict) or context.get("schema_version") != 2 \
            or type(context.get("schema_version")) is not int:
        raise ValueError("legacy or missing receipt decision context cannot be certified")
    expected_keys = {"schema_version", "candidate", "incumbent", "noise_floor",
                     "forced_reject", "rule_id", "verdict"}
    if set(context) != expected_keys or not isinstance(receipt, dict):
        raise ValueError("invalid receipt decision context schema")
    if receipt.get("receipt_id") != _context_id(context):
        raise ValueError("receipt identity does not bind its decision context")
    candidate = _restore_binary_snapshot(context["candidate"])
    incumbent = (_restore_binary_snapshot(context["incumbent"])
                 if context["incumbent"] is not None else None)
    rebuilt, rebuilt_evidence = AdmissionGate(None, context["noise_floor"]).evaluate(
        candidate, incumbent, context["forced_reject"])
    if _context_id(receipt) != _context_id(asdict(rebuilt)) \
            or _context_id(evidence) != _context_id(asdict(rebuilt_evidence)):
        raise ValueError("receipt or gate evidence differs from its reproducible decision")


class AdmissionGate:
    def __init__(self, store: AppendOnlyStore, noise_floor: float = 0.0):
        if isinstance(noise_floor, bool) or not isinstance(noise_floor, (int, float)) \
                or not math.isfinite(noise_floor) or noise_floor < 0:
            raise ValueError("noise_floor must be a finite non-negative number")
        self.store = store
        self.noise_floor = max(0.0, float(noise_floor))

    @staticmethod
    def flip_counts(result: EvalResult, incumbent: EvalResult) -> tuple[int, int, int]:
        """F = per-item wins, B = losses, N = comparable items. Gate, not rank."""
        validate_eval_comparison(result, incumbent)
        base = {it.item_id: it.verdict for it in incumbent.items}
        f = b = n = 0
        for it in result.items:
            n += 1
            d = it.verdict - base[it.item_id]
            f += d > 0
            b += d < 0
        return f, b, n

    def evaluate(self, result: EvalResult, incumbent: EvalResult | None,
                 forced_reject: str | None = None) -> tuple[Receipt, GateEvidenceRecord]:
        """Pure adjudication, also used to validate an interrupted durable verdict."""
        validate_eval_result(result)
        if incumbent is not None:
            validate_eval_result(incumbent)
        if forced_reject is not None and (
                not isinstance(forced_reject, str) or not forced_reject.strip()):
            raise ValueError("forced_reject must be a non-empty reason string")
        if forced_reject is not None:
            verdict, f, b, n = Verdict("REJECT", rationale_ref=forced_reject), 0, 0, 0
            rule = "extension_veto"
        elif result.private.get("cascade_stopped"):
            # A shallow screen can save cost, never substitute for full adjudication.
            verdict, f, b, n = Verdict(
                "REJECT", rationale_ref="cascade stopped before full evaluation"), 0, 0, 0
            rule = "cascade_incomplete"
        elif incumbent is None:
            verdict, f, b, n = Verdict("ACCEPT", rationale_ref="genesis candidate"), 0, 0, 0
            rule = "genesis"
        else:
            f, b, n = self.flip_counts(result, incumbent)
            # Effect is computed from per-item outcomes, never an aggregate metric.
            effect = (f - b) / n if n else 0.0
            # B7: below-noise effects count as zero, regardless of flip direction.
            if abs(effect) < self.noise_floor:
                verdict = Verdict("REJECT", rationale_ref="effect below noise floor")
            elif f > b:
                verdict = Verdict("ACCEPT", rationale_ref=f"flip_count |F|={f}>|B|={b}")
            else:
                verdict = Verdict("REJECT", rationale_ref=f"flip_count |F|={f}<=|B|={b}")
            rule = "flip_count+noise_floor_zero"
        decision_context = {
            "schema_version": 2,
            "candidate": _binary_snapshot(result),
            "incumbent": _binary_snapshot(incumbent) if incumbent is not None else None,
            "noise_floor": self.noise_floor,
            "forced_reject": forced_reject,
            "rule_id": rule,
            "verdict": asdict(verdict),
        }
        context_id = _context_id(decision_context)
        receipt = Receipt(receipt_id=context_id,
                          verdict=verdict, head_sha=result.head_sha,
                          evaluator_version=result.evaluator_version,
                          evidence_refs=[context_id])
        evidence = GateEvidenceRecord(
            candidate_id=result.candidate_id, receipt_id=receipt.receipt_id,
            transition="verdict", rule_id=rule,
            signals_snapshot={"F": f, "B": b, "N": n, "noise_floor": self.noise_floor},
            decision_context=decision_context)
        return receipt, evidence

    def judge(self, result: EvalResult, incumbent: EvalResult | None,
              forced_reject: str | None = None) -> Receipt:
        receipt, evidence = self.evaluate(result, incumbent, forced_reject)
        self.store.append("gate_evidence", asdict(evidence))
        self.store.append("receipt", asdict(receipt))
        return receipt


# M1 consumes verdicts only through this table (H-查表).
STOP_ACTION_TABLE = {
    ("ACCEPT", "global"): "promote",
    ("REJECT", "global"): "continue",
    ("REJECT", "budget_exhausted"): "stop",
    ("ACCEPT", "budget_exhausted"): "stop",
}


def stop_action(verdict_kind: str, scope: str) -> str:
    return STOP_ACTION_TABLE[(verdict_kind, scope)]
