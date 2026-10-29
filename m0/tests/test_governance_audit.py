"""v26 C1/C2 live reconciliation and adversarial append-only evidence tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.types import COST_ACCOUNTS
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "C1 C2 governance reconciliation"


def framework(tmp_path, **kwargs):
    values = dict(max_generations=4, baseline_every=2)
    values.update(kwargs)
    return Framework(MockLLM(), toy_evaluator, LoopConfig(**values), str(tmp_path))


def test_sequential_run_reconciles_every_settlement_and_admission(tmp_path):
    fw = framework(tmp_path)
    fw.evolve(TASK)
    inspection = fw.inspect()
    audit = inspection["governance_audit"]
    assert inspection["governance_pass"] is True
    assert inspection["ledger_reconciliation_pass"] is True
    assert inspection["accepted_receipt_coverage"] is True
    assert inspection["stop_action_replay_pass"] is True
    ledger = audit["ledger_reconciliation"]
    assert ledger["zero_gap"] is True and ledger["open_reserve_count"] == 0
    assert ledger["unmapped_settlement_count"] == 0
    assert set(ledger["settled_by_account"]) == set(COST_ACCOUNTS)
    assert ledger["settled_intent_count"] == ledger["settlement_count"] > 0
    receipts = audit["receipt_coverage"]
    assert receipts["gated_candidate_count"] == receipts["admission_decision_count"]
    assert receipts["accepted_decision_count"] == inspection["accepted_candidates"]
    assert list(fw.store.read("governance_audit"))[-1]["payload"] == audit


def test_batch_and_rejected_decisions_have_exact_receipt_bindings(tmp_path):
    fw = framework(tmp_path, max_generations=20, batch_size=3, max_inflight=3)
    fw.evolve(TASK)
    audit = fw.inspect()["governance_audit"]
    assert audit["passed"] is True
    receipts = audit["receipt_coverage"]
    assert receipts["rejected_decision_count"] > 0
    assert receipts["gated_candidate_count"] == receipts["admission_decision_count"]
    gated = {row["payload"]["candidate_id"]: row["payload"]["receipt_id"]
             for row in fw.store.read("gate_evidence")}
    bound = {row["payload"]["candidate_id"]: row["payload"]["receipt_id"]
             for row in fw.store.read("admission_receipt")}
    assert bound == gated


def test_budget_stop_is_journaled_and_reproduced_from_stop_table(tmp_path):
    fw = framework(tmp_path, total_budget=2_100, intent_cost=1_000,
                   reeval_floor=100, max_generations=10)
    out = fw.evolve(TASK)
    stops = list(fw.store.read("stop_action"))
    assert len(stops) == 1
    assert stops[0]["payload"]["verdict_kind"] == "REJECT"
    assert stops[0]["payload"]["scope"] == "budget_exhausted"
    assert stops[0]["payload"]["action"] == "stop"
    audit = out["governance_audit"]
    assert audit["stop_action_replay"] == {
        "passed": True, "table_driven_stop_count": 1,
        "replayed_stop_count": 1, "errors": []}
    assert fw.inspect()["governance_pass"] is True


def test_orphan_settlement_fails_c1_without_hiding_other_results(tmp_path):
    fw = framework(tmp_path)
    fw.evolve(TASK)
    fw.store.append("ledger", {"account": "exploit", "unit": "token",
                               "intent_id": "orphan-intent", "entry_kind": "settle",
                               "settled": 7})
    inspection = fw.inspect()
    audit = inspection["governance_audit"]
    assert inspection["governance_pass"] is False
    assert inspection["ledger_reconciliation_pass"] is False
    assert audit["ledger_reconciliation"]["unmapped_settlement_count"] == 1
    assert audit["ledger_reconciliation"]["zero_gap"] is False
    assert audit["receipt_coverage"]["passed"] is True


def test_reconcile_delta_must_match_the_original_reserve_and_settlement(tmp_path):
    fw = framework(tmp_path)
    fw.evolve(TASK)
    settled = list(fw.store.read("ledger"))
    original = next(row["payload"] for row in settled
                    if row["payload"]["entry_kind"] == "settle")
    fw.store.append("ledger", {"account": original["account"], "unit": "token",
                               "intent_id": original["intent_id"],
                               "entry_kind": "reconcile_delta", "settled": 1})
    audit = fw.inspect()["governance_audit"]["ledger_reconciliation"]
    assert audit["passed"] is False
    assert any("reconcile delta" in error for error in audit["errors"])


def test_fake_gate_and_conflicting_admission_fail_c2(tmp_path):
    fw = framework(tmp_path / "fake-gate")
    fw.evolve(TASK)
    fw.store.append("gate_evidence", {
        "candidate_id": "forged-candidate", "receipt_id": "forged-receipt",
        "transition": "verdict", "rule_id": "genesis", "signals_snapshot": {}})
    audit = fw.inspect()["governance_audit"]
    assert audit["passed"] is False and audit["receipt_coverage"]["passed"] is False
    assert audit["ledger_reconciliation"]["passed"] is True

    other = framework(tmp_path / "conflicting-admission")
    other.evolve(TASK)
    original = list(other.store.read("admission_receipt"))[0]["payload"]
    other.store.append("admission_receipt", {**original, "receipt_id": "wrong-receipt"})
    audit = other.inspect()["governance_audit"]
    assert audit["passed"] is False and audit["receipt_coverage"]["passed"] is False


def test_false_stop_action_cannot_be_certified(tmp_path):
    fw = framework(tmp_path)
    fw.evolve(TASK)
    fw.store.append("stop_action", {"verdict_kind": "ACCEPT", "scope": "global",
                                    "action": "stop"})
    inspection = fw.inspect()
    assert inspection["stop_action_replay_pass"] is False
    assert inspection["governance_pass"] is False
    assert inspection["governance_audit"]["stop_action_replay"][
        "replayed_stop_count"] == 0
