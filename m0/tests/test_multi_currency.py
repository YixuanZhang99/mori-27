"""N1 atomic multi-currency reserve/settle and versioned conversion tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.currency import MultiCurrencyBudgetLedger
from core.budget.ledger import BudgetError
from core.budget.types import AccountingStamp, CurrencyAccount, ExchangeRateTable
from core.policy.scheduler import make_intent, reissue
from core.x1.store import AppendOnlyStore

STAMP = AccountingStamp("mock", "m1", "t1", "p1", "2026-10-26")


def mk_ledger(tmp_path):
    accounts = {
        "token": CurrencyAccount("token", 1_000, floor=10),
        "usd": CurrencyAccount("usd", 10),
        "eval_count": CurrencyAccount("eval_count", 5),
    }
    exchange = ExchangeRateTable(
        "fx-v1", {("usd", "token"): 100, ("eval_count", "token"): 50}, "token")
    return MultiCurrencyBudgetLedger(accounts, 0.05, STAMP,
                                     AppendOnlyStore(tmp_path / "x1.jsonl"), exchange)


def mk_intent(token=100, usd=1, evals=1, account="explore"):
    intent = make_intent("m0", "candidate", 1, "snap", account)
    intent.requested_amounts = {"token": token, "usd": usd, "eval_count": evals}
    return intent


def test_atomic_reservation_and_per_unit_settlement(tmp_path):
    ledger = mk_ledger(tmp_path)
    intent = mk_intent()
    receipt = ledger.quote_reserve(intent)
    assert receipt.verdict == "granted"
    assert receipt.granted_amounts == intent.requested_amounts
    ledger.pre_call_check()
    ledger.settle(intent, {"token": 80, "usd": 0.8, "eval_count": 1}, True)
    summary = ledger.account_summary()
    assert summary["by_unit"]["token"]["explore"] == 80
    assert summary["by_unit"]["usd"]["explore"] == pytest.approx(0.8)
    assert summary["by_unit"]["eval_count"]["explore"] == 1
    assert summary["standard_spent"] == pytest.approx(210)
    assert summary["exchange_table_version"] == "fx-v1"
    kinds = [r["payload"]["entry_kind"] for r in ledger.store.read("ledger")]
    assert kinds.count("reserve") == 3 and kinds.count("settle") == 3
    assert "reconcile_delta" in kinds


def test_any_insufficient_currency_rejects_without_partial_reservation(tmp_path):
    ledger = mk_ledger(tmp_path)
    before = ledger.account_summary()["available_main"]
    receipt = ledger.quote_reserve(mk_intent(token=100, usd=20))
    assert receipt.verdict == "rejected_budget" and "usd" in receipt.reason
    assert ledger.reserves == {}
    assert ledger.account_summary()["available_main"] == before
    assert not list(ledger.store.read("ledger"))


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_reservation_is_rejected_without_mutating_accounts(tmp_path, invalid):
    ledger = mk_ledger(tmp_path)
    intent = mk_intent()
    intent.requested_amounts["usd"] = invalid
    before = ledger.account_summary()["available_main"]
    receipt = ledger.quote_reserve(intent)
    assert receipt.verdict == "rejected_invalid" and "finite" in receipt.reason
    assert not ledger.reserves and not list(ledger.store.read("ledger"))
    assert ledger.account_summary()["available_main"] == before


def test_release_restores_every_currency_and_reissue_halves_basket(tmp_path):
    ledger = mk_ledger(tmp_path)
    intent = mk_intent(token=100, usd=2, evals=2)
    lowered = reissue(intent)
    assert lowered.requested_amounts == {"token": 50, "usd": 1, "eval_count": 1}
    assert ledger.quote_reserve(intent).verdict == "granted"
    ledger.release_for(intent)
    summary = ledger.account_summary()
    assert summary["available_main"] == {"token": 950, "usd": 9.5, "eval_count": 4.75}
    released = [r for r in ledger.store.read("ledger")
                if r["payload"]["entry_kind"] == "reserve_released"]
    assert {r["payload"]["unit"] for r in released} == {"token", "usd", "eval_count"}


def test_invalid_settlement_does_not_destroy_open_reserve(tmp_path):
    ledger = mk_ledger(tmp_path)
    intent = mk_intent()
    ledger.quote_reserve(intent)
    with pytest.raises(BudgetError, match="exactly"):
        ledger.settle(intent, {"token": 80})
    assert intent.intent_id in ledger.reserves
    with pytest.raises(BudgetError, match="finite"):
        ledger.settle(intent, {"token": 100, "usd": float("nan"), "eval_count": 1})
    assert intent.intent_id in ledger.reserves
    ledger.settle(intent, {"token": 100, "usd": 1, "eval_count": 1})


def test_exchange_table_is_versioned_and_unversioned_rates_are_rejected(tmp_path):
    ledger = mk_ledger(tmp_path)
    event = list(ledger.store.read("exchange_rate_table"))[0]["payload"]
    assert event["table_version"] == "fx-v1"
    assert event["standard_coin_anchor"] == "token"
    with pytest.raises(ValueError, match="versioned"):
        ExchangeRateTable("", {("usd", "token"): 100})
    with pytest.raises(ValueError, match="no explicit rate"):
        ledger.exchange.convert(1, "node", "token")
