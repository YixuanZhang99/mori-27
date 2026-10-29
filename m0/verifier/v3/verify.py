#!/usr/bin/env python3
"""Verifier v3: v2 plus evaluation governance and multi-currency behavior."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.budget.currency import MultiCurrencyBudgetLedger
from core.budget.types import AccountingStamp, CurrencyAccount, ExchangeRateTable
from core.eval.cascade import CascadingEvaluator
from core.eval.gate import AdmissionGate
from core.eval.judge import IsotonicCalibrator, cohens_kappa, position_swap_probe
from core.eval.meta_gate import (AnchorCase, EvaluatorMetaGate, EvoEvaluatorChannel,
                                 EvolutionPreconditions, HeldOutAnchor)
from core.eval.types import EvalResult, ItemResult
from core.policy.scheduler import make_intent
from core.x1.store import AppendOnlyStore


class BaseEvaluator:
    evaluator_version = "cascade-det-v1"

    def __init__(self):
        self.last_usage = {"total_tokens": 0}

    def __call__(self, candidate_id, head_sha, prompt, item_limit=None):
        values = [1, 1, 1] if prompt == "good" else [0, 0, 0]
        values = values if item_limit is None else values[:item_limit]
        self.last_usage = {"total_tokens": len(values)}
        return EvalResult(candidate_id, head_sha,
                          [ItemResult(f"i{i}", v) for i, v in enumerate(values)],
                          combined_score=sum(values) / len(values),
                          evaluator_version=self.evaluator_version)


class AnchorEvaluator:
    def __init__(self, version, verdicts=(1, 0)):
        self.evaluator_version = version
        self.verdicts = verdicts
        self.last_usage = {"total_tokens": 0}

    def __call__(self, candidate_id, head_sha, prompt):
        return EvalResult(candidate_id, head_sha,
                          [ItemResult(f"a{i}", v) for i, v in enumerate(self.verdicts)],
                          combined_score=sum(self.verdicts) / len(self.verdicts),
                          evaluator_version=self.evaluator_version)


def meta_fixture(path):
    store = AppendOnlyStore(path / "x1.jsonl")
    anchor = HeldOutAnchor("anchor-v1", (AnchorCase("anchor", "sha", "task"),))
    gate = EvaluatorMetaGate(anchor, store)
    current = AnchorEvaluator("eval-v1")
    receipt = AdmissionGate(store).judge(current("old", "sha", "task"), None)
    evidence = EvolutionPreconditions("anchor-v1", True, True, "measured:eval-bound")
    return store, gate, current, receipt, evidence


def check_cascade(root):
    base = BaseEvaluator()
    cascade = CascadingEvaluator(base, shallow_items=1)
    good = cascade("good", "sha", "good")
    bad = cascade("bad", "sha", "bad")
    verdict = AdmissionGate(AppendOnlyStore(root / "cascade.jsonl")).judge(bad, good)
    passed = (cascade.shallow_count == 2 and cascade.full_count == 1
              and len(bad.items) == 1 and cascade.last_usage["total_tokens"] == 1
              and verdict.verdict.kind == "REJECT"
              and verdict.verdict.rationale_ref == "cascade stopped before full evaluation")
    return passed, {"shallow": cascade.shallow_count, "full": cascade.full_count,
                    "last_tokens": cascade.last_usage["total_tokens"],
                    "stopped_verdict": verdict.verdict.kind}


def check_judge(_root):
    stable = position_swap_probe(lambda a, b: "a" if a > b else "b", [("b", "a")])
    biased = position_swap_probe(lambda a, b: "a", [("b", "a")])
    kappa = cohens_kappa([1, 0, 1, 0], [1, 1, 1, 0])
    calibrated = [IsotonicCalibrator().fit([0, 1, 2, 3], [0, 1, 0, 1]).predict(x)
                  for x in (0, 1, 2, 3)]
    passed = (stable["accepted"] and not biased["accepted"]
              and abs(kappa - 0.5) < 1e-9 and calibrated == [0, 0.5, 0.5, 1])
    return passed, {"stable_flip_rate": stable["flip_rate"],
                    "biased_flip_rate": biased["flip_rate"],
                    "kappa": kappa, "calibrated": calibrated}


def check_meta_gate(root):
    store, gate, current, old, evidence = meta_fixture(root / "meta")
    rejected = gate.promote(current, AnchorEvaluator("eval-bad", (0, 1)), 1, evidence)
    accepted = gate.promote(current, AnchorEvaluator("eval-v2", (1, 1)), 1, evidence)
    hard_receipts = len(list(store.read("receipt")))
    invalidations = len(list(store.read("receipt_invalidation")))
    passed = (not rejected.accepted and accepted.accepted
              and accepted.invalidated_receipt_ids == [old.receipt_id]
              and not gate.is_receipt_valid(old.receipt_id)
              and hard_receipts == 1 and invalidations == 1 and gate.epoch == 1)
    return passed, {"regression_accepted": rejected.accepted,
                    "promotion_accepted": accepted.accepted,
                    "hard_receipts": hard_receipts, "invalidations": invalidations}


def check_evo_preconditions(root):
    store, gate, current, old, evidence = meta_fixture(root / "evo")
    closed = EvoEvaluatorChannel(gate).promote(
        current, AnchorEvaluator("eval-v2", (1, 1)), 1, evidence)
    missing_results = []
    for field, value in (("anchor_ref", "wrong"), ("meta_gate_enabled", False),
                         ("cascade_invalidation_ready", False),
                         ("bottleneck_evidence_ref", "")):
        _, fresh_gate, fresh_current, _, fresh_evidence = meta_fixture(
            root / f"evo-{field}")
        decision = EvoEvaluatorChannel(fresh_gate, enabled=True).promote(
            fresh_current, AnchorEvaluator("eval-v2", (1, 1)), 1,
            replace(fresh_evidence, **{field: value}))
        missing_results.append(not decision.accepted)
    passed = (not closed.accepted and "disabled by default" in closed.reason
              and all(missing_results) and gate.is_receipt_valid(old.receipt_id))
    return passed, {"closed_rejected": not closed.accepted,
                    "each_missing_rejected": missing_results}


def check_currency(root):
    store = AppendOnlyStore(root / "currency.jsonl")
    accounts = {"token": CurrencyAccount("token", 1_000, floor=10),
                "usd": CurrencyAccount("usd", 10),
                "eval_count": CurrencyAccount("eval_count", 5)}
    exchange = ExchangeRateTable("fx-v1", {("usd", "token"): 100,
                                           ("eval_count", "token"): 50}, "token")
    ledger = MultiCurrencyBudgetLedger(accounts, 0.05,
        AccountingStamp("mock", "m1", "t1", "p1", "2026-10-26"), store, exchange)
    intent = make_intent("m0", "cand", 1, "snap")
    intent.requested_amounts = {"token": 100, "usd": 1, "eval_count": 1}
    before = ledger.account_summary()["available_main"]
    intent.requested_amounts["usd"] = 20
    rejected = ledger.quote_reserve(intent)
    atomic = not ledger.reserves and ledger.account_summary()["available_main"] == before
    intent.requested_amounts["usd"] = 1
    granted = ledger.quote_reserve(intent)
    ledger.settle(intent, {"token": 80, "usd": 0.8, "eval_count": 1})
    summary = ledger.account_summary()
    fx_event = list(store.read("exchange_rate_table"))[0]["payload"]
    passed = (rejected.verdict == "rejected_budget" and atomic
              and granted.verdict == "granted"
              and summary["by_unit"]["token"]["explore"] == 80
              and abs(summary["standard_spent"] - 210) < 1e-9
              and fx_event["table_version"] == "fx-v1")
    return passed, {"atomic_rejection": atomic, "standard_spent": summary["standard_spent"],
                    "exchange_version": fx_event["table_version"]}


def main() -> int:
    checks: dict[str, bool] = {}
    values: dict = {}
    v2 = subprocess.run([sys.executable, "verifier/v2/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v2_complete"] = v2.returncode == 0
    values["v2_exit"] = v2.returncode
    if v2.returncode:
        values["v2_stderr"] = v2.stderr[-2000:]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("cascade_cost_and_admission", check_cascade),
                         ("judge_probes_and_calibration", check_judge),
                         ("anchor_meta_gate_and_invalidation", check_meta_gate),
                         ("evo_evaluator_four_preconditions", check_evo_preconditions),
                         ("atomic_multi_currency_ledger", check_currency)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:  # failed runs must still be auditable
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}

    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v3/verify.py", "version": "v3",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values}
    with (ROOT / "verifier/runs/v3.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
