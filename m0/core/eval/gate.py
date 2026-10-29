"""M9 gate (M0): flip_count + noise_floor_zero only. Deterministic adjudication.
Aggregate scores, public feedback and trajectory text are unreachable here (B2/分歧2).
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict

from core.eval.types import (EvalResult, GateEvidenceRecord, Receipt, Verdict)
from core.x1.store import AppendOnlyStore


class AdmissionGate:
    def __init__(self, store: AppendOnlyStore, noise_floor: float = 0.0):
        self.store = store
        self.noise_floor = noise_floor

    @staticmethod
    def flip_counts(result: EvalResult, incumbent: EvalResult) -> tuple[int, int, int]:
        """F = per-item wins, B = losses, N = comparable items. Gate, not rank."""
        base = {it.item_id: it.verdict for it in incumbent.items}
        f = b = n = 0
        for it in result.items:
            if it.item_id not in base:
                continue
            n += 1
            d = it.verdict - base[it.item_id]
            f += d > 0
            b += d < 0
        return f, b, n

    def evaluate(self, result: EvalResult, incumbent: EvalResult | None,
                 forced_reject: str | None = None) -> tuple[Receipt, GateEvidenceRecord]:
        """Pure adjudication, also used to validate an interrupted durable verdict."""
        if not result.items:
            raise ValueError("EvalResult.items must be non-empty (gate-not-rank)")
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
        receipt_key = "\0".join((result.candidate_id, result.head_sha,
                                 result.evaluator_version, rule))
        receipt = Receipt(receipt_id=hashlib.sha256(receipt_key.encode()).hexdigest()[:12],
                          verdict=verdict, head_sha=result.head_sha,
                          evaluator_version=result.evaluator_version)
        evidence = GateEvidenceRecord(
            candidate_id=result.candidate_id, receipt_id=receipt.receipt_id,
            transition="verdict", rule_id=rule,
            signals_snapshot={"F": f, "B": b, "N": n, "noise_floor": self.noise_floor})
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
