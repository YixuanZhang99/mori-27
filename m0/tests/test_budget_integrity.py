"""Budget boundary validation, intent binding, and durable replay regressions."""
from copy import deepcopy
from dataclasses import replace

import pytest

from core.budget.currency import MultiCurrencyBudgetLedger
from core.budget.ledger import BudgetError, BudgetLedger
from core.budget.types import AccountingStamp, CurrencyAccount, ExchangeRateTable
from core.policy.types import AllocationIntent
from core.x1.store import AppendOnlyStore


STAMP = AccountingStamp("test", "m1", "t1", "p1", "2026-10-29")
INVALID_AMOUNTS = [-1, float("nan"), float("inf"), float("-inf"),
                   True, False, None, "10", [], {}, 10 ** 1000]


def make_ledger(tmp_path, multi=False, name="journal"):
    store = AppendOnlyStore(tmp_path / f"{name}.jsonl")
    if multi:
        return MultiCurrencyBudgetLedger(
            {"token": CurrencyAccount("token", 1000), "usd": CurrencyAccount("usd", 10)},
            0.1, STAMP, store, ExchangeRateTable("fx-v1", {("usd", "token"): 100}))
    return BudgetLedger(1000, 0.1, 10, STAMP, store)


def make_intent(multi=False):
    return AllocationIntent("allocation", "policy", "candidate", 100,
                            requested_amounts={"token": 100, "usd": 1} if multi else {})


def state(ledger):
    return deepcopy((ledger.spent, ledger.reserves, ledger.settled_intents,
                     list(ledger.store.read("ledger"))))


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("amount", [0, *INVALID_AMOUNTS])
def test_invalid_scalar_reservation_leaves_all_evidence_unchanged(tmp_path, multi, amount):
    ledger = make_ledger(tmp_path, multi)
    intent = replace(make_intent(multi), requested=amount)
    before = state(ledger)
    assert ledger.quote_reserve(intent).verdict == "rejected_invalid"
    assert state(ledger) == before


@pytest.mark.parametrize("multi", [False, True])
def test_duplicate_open_reservation_cannot_replace_original(tmp_path, multi):
    ledger, intent = make_ledger(tmp_path, multi), make_intent(multi)
    assert ledger.quote_reserve(intent).verdict == "granted"
    before = state(ledger)
    assert ledger.quote_reserve(intent).verdict == "rejected_invalid"
    assert ledger.quote_reserve(replace(intent, account="control")).verdict == "rejected_invalid"
    assert state(ledger) == before
    ledger.release_for(intent)
    assert ledger.quote_reserve(intent).verdict == "granted"


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("amount", INVALID_AMOUNTS)
def test_invalid_actual_cost_preserves_reserve_spend_and_journal(tmp_path, multi, amount):
    ledger, intent = make_ledger(tmp_path, multi), make_intent(multi)
    ledger.quote_reserve(intent)
    before = state(ledger)
    actual = {"token": 80, "usd": amount} if multi else amount
    with pytest.raises(BudgetError, match="finite"):
        ledger.settle(intent, actual)
    assert state(ledger) == before
    ledger.settle(intent, {"token": 0, "usd": 0} if multi else 0)
    assert not ledger.reserves


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("field,value", [
    ("account", "control"), ("account", "unknown"), ("requested", 101),
    ("candidate_ref", "other"), ("policy_id", "other"), ("snapshot_ref", "other"),
    ("requested_amounts", {"token": 1}),
])
@pytest.mark.parametrize("operation", ["settle", "release"])
def test_modified_intent_cannot_consume_another_reserve(tmp_path, multi, field, value, operation):
    ledger, intent = make_ledger(tmp_path, multi), make_intent(multi)
    ledger.quote_reserve(intent)
    before = state(ledger)
    forged = replace(intent, **{field: value})
    with pytest.raises(BudgetError):
        if operation == "settle":
            ledger.settle(forged, {"token": 80, "usd": 0.5} if multi else 80)
        else:
            ledger.release_for(forged)
    assert state(ledger) == before
    ledger.release_for(intent)
    assert not ledger.reserves


def test_multi_receipt_cannot_mutate_the_reserved_basket(tmp_path):
    ledger, intent = make_ledger(tmp_path, True), make_intent(True)
    receipt = ledger.quote_reserve(intent)
    receipt.granted_amounts["token"] = 999
    assert ledger.reserves[intent.intent_id].amounts["token"] == 100
    ledger.settle(intent, {"token": 80, "usd": 0.5})
    assert ledger.spent["token"]["explore"] == 80


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("kind", ["settle", "reserve_released"])
def test_replay_rejects_changed_account_without_restoring_partial_state(tmp_path, multi, kind):
    original, intent = make_ledger(tmp_path, multi), make_intent(multi)
    original.quote_reserve(intent)
    recovered = make_ledger(tmp_path, multi, "recovery")
    entries = [row["payload"] for row in original.store.read("ledger")]
    for entry in entries:
        recovered.store.append("ledger", entry)
    bad = dict(entries[0], account="control", entry_kind=kind, settled=50)
    recovered.store.append("ledger", bad)
    before = state(recovered)
    with pytest.raises(BudgetError):
        recovered.restore_from_journal()
    assert state(recovered) == before


@pytest.mark.parametrize("multi", [False, True])
def test_missing_journal_settlement_amount_cannot_be_replayed_as_zero(tmp_path, multi):
    original, intent = make_ledger(tmp_path, multi), make_intent(multi)
    original.quote_reserve(intent)
    original.settle(intent, {"token": 0, "usd": 0} if multi else 0)
    recovered = make_ledger(tmp_path, multi, "recovery")
    for row in original.store.read("ledger"):
        entry = dict(row["payload"])
        if entry["entry_kind"] == "settle":
            entry.pop("settled")
        recovered.store.append("ledger", entry)
    before = state(recovered)
    with pytest.raises(BudgetError):
        recovered.restore_from_journal()
    assert state(recovered) == before


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_restored_open_reserve_keeps_original_account_binding(tmp_path, multi, legacy):
    original, intent = make_ledger(tmp_path, multi), make_intent(multi)
    original.quote_reserve(intent)
    recovered = make_ledger(tmp_path, multi, "recovery")
    for row in original.store.read("ledger"):
        entry = dict(row["payload"])
        if legacy:
            entry.pop("intent_fingerprint")
        recovered.store.append("ledger", entry)
    recovered.restore_from_journal()
    before = state(recovered)
    with pytest.raises(BudgetError):
        recovered.release_for(replace(intent, account="control"))
    assert state(recovered) == before
    recovered.settle(intent, {"token": 80, "usd": 0.5} if multi else 80)


def test_partial_multi_settlement_preserves_complete_intent_identity(tmp_path):
    original, intent = make_ledger(tmp_path, True), make_intent(True)
    original.quote_reserve(intent)
    original.settle(intent, {"token": 80, "usd": 0.5})
    recovered = make_ledger(tmp_path, True, "recovery")
    for row in original.store.read("ledger"):
        entry = row["payload"]
        if entry["entry_kind"] == "reserve" or entry["unit"] == "token":
            recovered.store.append("ledger", entry)
    recovered.restore_from_journal()
    assert recovered.reserves[intent.intent_id].amounts == {"usd": 1}
    before = state(recovered)
    with pytest.raises(BudgetError):
        recovered.settle(replace(intent, candidate_ref="forged"), {"usd": 0.5})
    assert state(recovered) == before
    recovered.settle(intent, {"usd": 0.5})
    assert recovered.spent == original.spent
    assert recovered.settled_intents == original.settled_intents


def test_partial_multi_settlement_cannot_be_renewed_by_releasing_remainder(tmp_path):
    original, intent = make_ledger(tmp_path, True), make_intent(True)
    original.quote_reserve(intent)
    original.settle(intent, {"token": 80, "usd": 0.5})
    recovered = make_ledger(tmp_path, True, "recovery")
    for row in original.store.read("ledger"):
        entry = row["payload"]
        if entry["entry_kind"] == "reserve" or entry["unit"] == "token":
            recovered.store.append("ledger", entry)
    recovered.restore_from_journal()
    recovered.release_for(intent)
    assert not recovered.reserves and intent.intent_id in recovered.settled_intents
    assert recovered.quote_reserve(intent).verdict == "rejected_invalid"


def test_releasing_decimal_currency_reserves_does_not_create_negative_roundoff(tmp_path):
    ledger = make_ledger(tmp_path, True)
    intents = [replace(make_intent(True), intent_id=f"fraction-{index}",
                       requested_amounts={"usd": amount})
               for index, amount in enumerate((0.9, 0.1))]
    for intent in intents:
        ledger.quote_reserve(intent)
    for intent in intents:
        ledger.release_for(intent)
    assert ledger.spent["usd"]["explore"] == 0
    ledger.pre_call_check()


def test_reconcile_validates_identity_and_cost_then_repairs_only_missing_delta(tmp_path):
    original, intent = make_ledger(tmp_path), make_intent()
    original.quote_reserve(intent)
    original.release_for(intent)
    original.quote_reserve(intent)
    original.settle(intent, 80)
    recovered = make_ledger(tmp_path, name="recovery")
    for row in original.store.read("ledger"):
        if row["payload"]["entry_kind"] != "reconcile_delta":
            recovered.store.append("ledger", row["payload"])
    recovered.restore_from_journal()
    before = state(recovered)
    for actual in INVALID_AMOUNTS:
        with pytest.raises(BudgetError):
            recovered.reconcile_settled(intent, actual)
        assert state(recovered) == before
    with pytest.raises(BudgetError):
        recovered.reconcile_settled(replace(intent, candidate_ref="forged"), 80)
    assert state(recovered) == before
    recovered.reconcile_settled(intent, 80)
    repaired = state(recovered)
    recovered.reconcile_settled(intent, 80)
    assert state(recovered) == repaired
    assert recovered.spent == original.spent


@pytest.mark.parametrize("multi", [False, True])
def test_replay_rejects_corrupt_reconcile_delta_atomically(tmp_path, multi):
    original, intent = make_ledger(tmp_path, multi), make_intent(multi)
    original.quote_reserve(intent)
    original.settle(intent, {"token": 80, "usd": 0.5} if multi else 80)
    recovered = make_ledger(tmp_path, multi, "recovery")
    for row in original.store.read("ledger"):
        entry = dict(row["payload"])
        if entry["entry_kind"] == "reconcile_delta":
            entry["settled"] = 999
        recovered.store.append("ledger", entry)
    before = state(recovered)
    with pytest.raises(BudgetError, match="reconcile"):
        recovered.restore_from_journal()
    assert state(recovered) == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "100"])
def test_invalid_budget_configuration_is_rejected(tmp_path, value):
    with pytest.raises(BudgetError):
        BudgetLedger(value, 0.1, 0, STAMP, AppendOnlyStore(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        CurrencyAccount("token", value)
    with pytest.raises(ValueError):
        ExchangeRateTable("fx-v1", {("usd", "token"): value})
