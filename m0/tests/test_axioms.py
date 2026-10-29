"""Axiom-as-test suite (RUBRIC A4). Each test names the axiom it guards."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.ledger import BudgetError, BudgetLedger
from core.budget.types import AccountingStamp
from core.eval.gate import AdmissionGate, stop_action
from core.eval.types import EvalResult, ItemResult
from core.operator.ops import reflective_improve
from core.operator.types import OperatorSpec
from core.policy.scheduler import make_intent, reissue
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import run

STAMP = AccountingStamp("mock", "m1", "t1", "p1", "2026-10-26")


def mk_ledger(tmp_path, total=10_000, floor=100, share=0.05):
    return BudgetLedger(total, share, floor, STAMP,
                        AppendOnlyStore(tmp_path / "x1.jsonl"))


def mk_intent(requested=1_000, account="explore", **kw):
    return make_intent("m0", "cand", requested, "snap", account, **kw)


# ---- B1 / K6: full loop, main search must beat the resident baseline ----
def test_loop_beats_iid_rs_and_locks_control(tmp_path):
    out = run(workdir=str(tmp_path), max_generations=20)
    assert out["best_score"] == 1.0
    assert out["baseline_scores"], "IID-RS must be resident (K6)"
    assert all(s < out["best_score"] for s in out["baseline_scores"])
    assert out["ledger"]["spent"]["control"] > 0  # covenant (f): control spent


# ---- J7 / covenant (g): refuse to start below the reeval floor ----
def test_floor_refusal(tmp_path):
    with pytest.raises(BudgetError, match="预算不足"):
        mk_ledger(tmp_path, total=10, floor=100)


# ---- J8: main accounts cannot touch the control lock ----
def test_control_lock_untouchable(tmp_path):
    led = mk_ledger(tmp_path, total=10_000, share=0.05)
    rec = led.quote_reserve(mk_intent(requested=9_600))  # > 9,500 main available
    assert rec.verdict == "rejected_budget"
    assert led.account_summary()["available_control"] == 500


# ---- R4: reissue chain cap -> rejected_conflict ----
def test_reissue_cap(tmp_path):
    led = mk_ledger(tmp_path, total=1_500)
    intent = mk_intent(requested=1_000)
    assert led.quote_reserve(intent).verdict == "granted"
    led.settle(intent, actual_cost=1_000)
    for _ in range(3):
        intent = reissue(intent)
    rec = led.quote_reserve(intent)
    assert rec.verdict == "rejected_conflict"


# ---- R4(1) + J9: release restores budget; settled intent cannot renew ----
def test_release_and_no_renewal(tmp_path):
    led = mk_ledger(tmp_path)
    intent = mk_intent()
    led.quote_reserve(intent)
    led.release_for(intent)
    assert led.account_summary()["available_main"] == 9_500
    led.quote_reserve(intent)
    led.settle(intent, actual_cost=800)
    assert led.account_summary()["available_main"] == 9_500 - 800
    assert led.quote_reserve(intent).verdict == "rejected_invalid"


# ---- B7: effect below the noise floor counts as zero ----
def test_noise_floor_zero(tmp_path):
    gate = AdmissionGate(AppendOnlyStore(tmp_path / "x1.jsonl"), noise_floor=1.0)
    mk = lambda cid, score: EvalResult(cid, "sha", [ItemResult("i", 1)],
                                       combined_score=score, text_feedback="x")
    rec = gate.judge(mk("a", 0.5), mk("b", 0.4))
    assert rec.verdict.kind == "REJECT"


# ---- S-4: reflective improve without trajectory text is refused ----
def test_improve_requires_feedback():
    spec = OperatorSpec("imp", "improve", prompt_version="1")
    with pytest.raises(ValueError, match="S-4"):
        reflective_improve(lambda p: p, spec, "p", "base", "", 0.0)


# ---- H-查表: stop is a table lookup ----
def test_stop_table():
    assert stop_action("REJECT", "budget_exhausted") == "stop"
    assert stop_action("ACCEPT", "global") == "promote"


# ---- S-5 / I-谱系: the store exposes no mutation API ----
def test_append_only_store(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")
    store.append("t", {"a": 1})
    assert len(list(store.read())) == 1


# ---- J4: pre-call interception on hard ceiling ----
def test_pre_call_intercept(tmp_path):
    led = mk_ledger(tmp_path, total=1_000)
    intent = mk_intent(requested=950)
    assert led.quote_reserve(intent).verdict == "granted"
    led.spent["explore"] += 200  # simulate cost drift past the hard ceiling
    with pytest.raises(BudgetError):
        led.pre_call_check()
