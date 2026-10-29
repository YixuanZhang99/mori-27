#!/usr/bin/env python3
"""Offline read-only audit probes for the supplied AutoResearch m0 source.

Usage: PYTHONDONTWRITEBYTECODE=1 python3 this_file.py /path/to/m0
Only temporary evidence directories are written; they are removed on exit.
Exit 0 means these observations were reproduced, NOT that production is correct.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(sys.argv[1]).resolve()))

from core.budget.ledger import BudgetLedger
from core.budget.types import AccountingStamp
from core.eval.gate import AdmissionGate
from core.eval.types import EvalResult, ItemResult
from core.llm import OpenAICompatibleLLM
from core.loop import Framework, LoopConfig
from core.policy.types import AllocationIntent


class NullStore:
    def append(self, *args):
        pass


class MockLLM:
    def __init__(self, usage):
        self.usage = usage
        self.last_usage = {}

    def __call__(self, prompt):
        self.last_usage = {} if self.usage is None else {"total_tokens": self.usage}
        return "candidate"


class MockEvaluator:
    def __init__(self, usage=5, duplicates=False):
        self.usage = usage
        self.duplicates = duplicates
        self.last_usage = {}
        self.count = 0

    def __call__(self, candidate_id, head_sha, prompt):
        self.count += 1
        self.last_usage = {} if self.usage is None else {"total_tokens": self.usage}
        items = [ItemResult("a", 0), ItemResult("b", 1)]
        if self.duplicates and self.count > 1:
            items = [ItemResult("a", 1), ItemResult("a", 1), ItemResult("b", 0)]
        return EvalResult(candidate_id, head_sha, items,
                          combined_score=0.5, text_feedback="offline audit")


def framework_probe(llm_usage=5, evaluator_usage=5, duplicates=False):
    with tempfile.TemporaryDirectory(prefix="autoresearch-audit-") as directory:
        fw = Framework(MockLLM(llm_usage), MockEvaluator(evaluator_usage, duplicates),
                       LoopConfig(total_budget=1000, intent_cost=100, reeval_floor=100,
                                  max_generations=1 if duplicates else 0,
                                  baseline_every=5), directory)
        result = fw.evolve("offline architecture probe")
        ledger = [row["payload"] for row in fw.store.read("ledger")]
        return {
            "run_returned": True,
            "accepted_count": len(result["accepted_candidate_ids"]),
            "governance_pass": result["governance_audit"]["passed"],
            "ledger_audit_errors": result["governance_audit"]["ledger_reconciliation"]["errors"],
            "settled_costs": [row["settled"] for row in ledger
                              if row["entry_kind"] == "settle"],
            "accounting_stamp": ledger[0]["stamp"],
            "improve_gate_signals": [row["payload"]["signals_snapshot"]
                                     for row in fw.store.read("gate_evidence")
                                     if row["payload"]["rule_id"] ==
                                     "flip_count+noise_floor_zero"],
        }


stamp = AccountingStamp("test", "test", "test", "test", "2026-10-29")
intent = AllocationIntent("same", "policy", "candidate", 100)
ledger = BudgetLedger(1000, 0.05, 100, stamp, NullStore())
first = ledger.quote_reserve(intent)
second = ledger.quote_reserve(intent)
ledger.settle(intent, 10)
duplicate_reserve = {
    "verdicts": [first.verdict, second.verdict],
    "actual_settlement": 10,
    "spent_after_settlement": ledger.spent["explore"],
}

negative_ledger = BudgetLedger(1000, 0.05, 100, stamp, NullStore())
negative_ledger.quote_reserve(intent)
negative_ledger.settle(intent, -20)

gate = AdmissionGate(None)  # evaluate is pure and never accesses the store.
incumbent = EvalResult("inc", "sha", [ItemResult("a", 0), ItemResult("b", 1)])
candidate = EvalResult("candidate", "sha", [ItemResult("a", 1),
                                            ItemResult("a", 1), ItemResult("b", 0)])
receipt, evidence = gate.evaluate(candidate, incumbent)

observations = {
    "duplicate_item_gate": {
        "verdict": receipt.verdict.kind,
        "signals": evidence.signals_snapshot,
    },
    "duplicate_items_through_framework": framework_probe(duplicates=True),
    "duplicate_reserve_public_ledger_api": duplicate_reserve,
    "negative_settlement_public_ledger_api": negative_ledger.spent["explore"],
    "negative_usage_through_framework": framework_probe(llm_usage=-10),
    "missing_provider_usage_parse": OpenAICompatibleLLM.parse_response(
        {"choices": [{"message": {"content": "offline"}}]})[1],
    "both_usage_missing_framework": framework_probe(llm_usage=None, evaluator_usage=None),
    "proposer_usage_missing_framework": framework_probe(llm_usage=None, evaluator_usage=5),
}
assert observations["duplicate_item_gate"]["verdict"] == "ACCEPT"
assert observations["duplicate_items_through_framework"]["accepted_count"] == 2
assert duplicate_reserve["verdicts"] == ["granted", "granted"]
assert duplicate_reserve["spent_after_settlement"] == 110
assert observations["negative_usage_through_framework"]["settled_costs"] == [-5]
assert observations["both_usage_missing_framework"]["settled_costs"] == [100]
assert observations["proposer_usage_missing_framework"]["settled_costs"] == [5]
print(json.dumps(observations, ensure_ascii=False, indent=2))
