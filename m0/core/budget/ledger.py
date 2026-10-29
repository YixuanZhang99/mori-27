"""M3 engine (M0): quote_reserve / settle / three-way reject / control lock /
reeval floor / hard cap pre-call intercept / intent reconciliation.

Boundary: M3 only quotes, reserves, settles, rejects. It NEVER downgrades an
intent (allocation semantics have a single author: M1). No LLM anywhere here.
"""
from __future__ import annotations

import math
import hashlib
import json
import uuid
from dataclasses import asdict

from core.budget.types import (COST_ACCOUNTS, AccountingStamp, LedgerEntry,
                               ReserveRecord, finite_number)
from core.policy.types import AllocationIntent, IntentReceipt
from core.x1.store import AppendOnlyStore


class BudgetError(Exception):
    pass


def intent_fingerprint(intent: AllocationIntent) -> str:
    """Bind each reserve to a durable copy of the complete allocation intent."""
    try:
        encoded = json.dumps(asdict(intent), sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BudgetError("intent must contain valid finite serializable values") from exc
    return hashlib.sha256(encoded).hexdigest()


def validate_intent(intent: AllocationIntent) -> None:
    if not isinstance(intent.intent_id, str) or not intent.intent_id:
        raise BudgetError("intent_id must be a non-empty string")
    if intent.account not in COST_ACCOUNTS:
        raise BudgetError(f"unknown account {intent.account}")
    if not finite_number(intent.requested) or intent.requested <= 0:
        raise BudgetError("requested must be finite and positive")
    if not isinstance(intent.requested_amounts, dict) or any(
            not isinstance(unit, str) or not finite_number(amount) or amount <= 0
            for unit, amount in intent.requested_amounts.items()):
        raise BudgetError("amounts must be finite, positive and use declared units")
    if isinstance(intent.reissue_count, bool) or not isinstance(intent.reissue_count, int) \
            or intent.reissue_count < 0:
        raise BudgetError("reissue_count must be a non-negative integer")


def validate_binding(intent: AllocationIntent, reserve: ReserveRecord) -> None:
    validate_intent(intent)
    if reserve.account != intent.account or reserve.intent_id != intent.intent_id \
            or reserve.status != "open":
        raise BudgetError("intent does not match the original reserve account or identity")
    if reserve.intent_fingerprint:
        if reserve.intent_fingerprint != intent_fingerprint(intent):
            raise BudgetError("intent does not match the original reserve identity")
    else:
        # Old journals predate fingerprints. Preserve recovery with every binding
        # those rows actually contain, including units remaining after a crash.
        amounts = intent.requested_amounts or {"token": intent.requested}
        reserved = reserve.amounts or {"token": reserve.amount}
        if any(amounts.get(unit) != amount for unit, amount in reserved.items()):
            raise BudgetError("intent amounts do not match the original reserve")


def checked_spend(values: dict[str, float], account: str,
                  reserved: float, actual: float) -> float:
    updated = values[account] - reserved + actual
    if updated < 0 and math.isclose(updated, 0.0, rel_tol=0.0, abs_tol=1e-9):
        updated = 0.0  # Releasing decimal-unit baskets can leave roundoff dust.
    if not finite_number(updated) or not finite_number(
            sum(value for name, value in values.items() if name != account) + updated) \
            or updated < 0:
        raise BudgetError("settlement would produce nonfinite spend")
    return updated


class BudgetLedger:
    def __init__(self, total_budget: int, control_share: float,
                 reeval_floor: int, stamp: AccountingStamp,
                 store: AppendOnlyStore):
        if not finite_number(control_share) or not 0 < control_share < 1:
            raise BudgetError("control_share must be in (0,1)")
        if not finite_number(total_budget) or total_budget <= 0 \
                or not finite_number(reeval_floor) or reeval_floor < 0:
            raise BudgetError("budget and floor must be finite non-negative numbers")
        # J7 / covenant (g): refuse to start when the budget cannot support
        # an adjudicable conclusion; never silently compress evaluation.
        if total_budget < reeval_floor:
            raise BudgetError(
                "预算不足以产生可证结论: total_budget < reeval_floor")
        self.total = total_budget
        self.stamp = stamp
        self.store = store
        self.spent: dict[str, float] = {a: 0.0 for a in COST_ACCOUNTS}
        self.locked_control = total_budget * control_share  # J8: locked at start
        self.reeval_floor = reeval_floor
        self.reserves: dict[str, ReserveRecord] = {}
        self.settled_intents: set[str] = set()

    # ---- internals -------------------------------------------------------
    def _write(self, **kw) -> LedgerEntry:
        entry = LedgerEntry(entry_id=uuid.uuid4().hex[:12], stamp=self.stamp, **kw)
        self.store.append("ledger", asdict(entry))
        return entry

    def _available(self, account: str) -> float:
        if account == "control":
            return self.locked_control - self.spent["control"]
        # Main accounts may not touch the control lock (J8 hard rule).
        return (self.total - self.locked_control
                - sum(v for k, v in self.spent.items() if k != "control"))

    # ---- sync path: quote / reserve / reject (arithmetic only) -----------
    def quote_reserve(self, intent: AllocationIntent) -> IntentReceipt:
        try:
            validate_intent(intent)
            if intent.requested_amounts and intent.requested_amounts != {"token": intent.requested}:
                raise BudgetError("single-currency ledger cannot reserve a cost basket; token amounts must match")
            fingerprint = intent_fingerprint(intent)
        except BudgetError as exc:
            return IntentReceipt(intent.intent_id, "rejected_invalid", reason=str(exc))
        if intent.intent_id in self.settled_intents or intent.intent_id in self.reserves:
            # J9: an intent past settlement may not be renewed.
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason="intent already settled or reserved")
        if intent.reissue_count > 2:
            # R4 (3): same-lineage reissue chain is capped; redirect, don't reprice.
            return IntentReceipt(intent.intent_id, "rejected_conflict",
                                 reason="reissue chain > 2; reallocate instead")
        if self._available(intent.account) < intent.requested:
            return IntentReceipt(intent.intent_id, "rejected_budget",
                                 reason="insufficient budget")
        self.spent[intent.account] += intent.requested  # reserved counts as committed
        self.reserves[intent.intent_id] = ReserveRecord(
            reserve_id=uuid.uuid4().hex[:12], intent_id=intent.intent_id,
            amount=intent.requested, account=intent.account,
            intent_fingerprint=fingerprint)
        self._write(account=intent.account, reserved=intent.requested,
                    intent_id=intent.intent_id, entry_kind="reserve",
                    intent_fingerprint=fingerprint)
        return IntentReceipt(intent.intent_id, "granted", granted=intent.requested)

    def pre_call_check(self) -> None:
        """J4: terminate-before-call. Alerting alone is a forbidden anti-pattern."""
        if any(not finite_number(value) or value < 0 for value in self.spent.values()) \
                or sum(self.spent.values()) > self.total:
            raise BudgetError("hard ceiling exceeded; read-only settlement state")

    # ---- settle / release / reconcile ------------------------------------
    def release_for(self, intent: AllocationIntent) -> None:
        """R4 (1): synchronously release the correct account; no ghost reserves."""
        rec = self.reserves.get(intent.intent_id)
        if rec is None or rec.status != "open":
            return
        validate_binding(intent, rec)
        updated = checked_spend(self.spent, rec.account, rec.amount, 0)
        self.reserves.pop(intent.intent_id)
        self.spent[rec.account] = updated
        rec.status = "released"
        self._write(account=intent.account, intent_id=intent.intent_id,
                    entry_kind="reserve_released")

    def settle(self, intent: AllocationIntent, actual_cost: int,
               admission_outcome: bool | None = None) -> None:
        rec = self.reserves.get(intent.intent_id)
        if rec is None:
            raise BudgetError(f"settle without open reserve: {intent.intent_id}")
        validate_binding(intent, rec)
        if not finite_number(actual_cost) or actual_cost < 0:
            raise BudgetError("actual cost must be finite and non-negative")
        updated = checked_spend(self.spent, rec.account, rec.amount, actual_cost)
        self.reserves.pop(intent.intent_id)
        rec.status = "settled"
        rec.settled_amount = actual_cost
        # Actual replaces reserved; difference is settled back (多退少补).
        self.spent[rec.account] = updated
        self._write(account=intent.account, settled=actual_cost,
                    intent_id=intent.intent_id, admission_outcome=admission_outcome,
                    entry_kind="settle")
        delta = rec.amount - actual_cost
        if delta:
            self._write(account=intent.account, settled=delta,
                        intent_id=intent.intent_id, entry_kind="reconcile_delta")
        self.settled_intents.add(intent.intent_id)

    def reconcile_settled(self, intent: AllocationIntent, actual_cost: int) -> None:
        """Complete a missing post-settle delta without settling or changing spend twice."""
        validate_intent(intent)
        if not finite_number(actual_cost) or actual_cost < 0:
            raise BudgetError("actual cost must be finite and non-negative")
        if intent.intent_id not in self.settled_intents \
                or intent.intent_id in self.reserves:
            raise BudgetError("reconcile requires a settled intent without an open reserve")
        entries = [record["payload"] for record in self.store.read("ledger")
                   if record["payload"].get("intent_id") == intent.intent_id]
        # A released intent may legitimately be reserved again before settlement.
        # Only the current lifecycle contributes its reservation to reconciliation.
        last_release = max((index for index, entry in enumerate(entries)
                            if entry["entry_kind"] == "reserve_released"), default=-1)
        entries = entries[last_release + 1:]
        reserves = [entry for entry in entries if entry["entry_kind"] == "reserve"]
        settlements = [entry for entry in entries if entry["entry_kind"] == "settle"]
        deltas = [entry for entry in entries if entry["entry_kind"] == "reconcile_delta"]
        if len(reserves) != 1 or len(settlements) != 1 or len(deltas) > 1 \
                or not finite_number(settlements[0].get("settled")) \
                or settlements[0].get("settled") != actual_cost \
                or settlements[0]["account"] != intent.account:
            raise BudgetError("settled intent evidence is not unique or cost-matched")
        if any(entry.get("account") != intent.account
               or entry.get("stamp") != asdict(self.stamp)
               or entry.get("unit", "token") != "token" for entry in entries) \
                or not finite_number(reserves[0].get("reserved")) \
                or reserves[0]["reserved"] <= 0:
            raise BudgetError("settled intent evidence has incompatible reservation identity")
        validate_binding(intent, ReserveRecord(
            "reconcile", intent.intent_id, amount=reserves[0]["reserved"],
            account=reserves[0]["account"],
            intent_fingerprint=reserves[0].get("intent_fingerprint", "")))
        expected = reserves[0]["reserved"] - actual_cost
        if deltas:
            if not finite_number(deltas[0].get("settled")) \
                    or not math.isclose(deltas[0]["settled"], expected,
                                rel_tol=0.0, abs_tol=1e-9):
                raise BudgetError("existing reconcile delta differs from reserve minus actual")
        elif expected:
            self._write(account=intent.account, settled=expected,
                        intent_id=intent.intent_id, entry_kind="reconcile_delta")

    def restore_from_journal(self) -> None:
        """Rebuild a fresh ledger from durable entries; never replay into live state."""
        if self.reserves or self.settled_intents or any(self.spent.values()):
            raise BudgetError("ledger restore requires a fresh, empty ledger")
        spent = {account: 0.0 for account in COST_ACCOUNTS}
        reserves: dict[str, ReserveRecord] = {}
        settled: set[str] = set()
        expected_deltas: dict[str, tuple[str, float]] = {}
        reconciled: set[str] = set()
        for record in self.store.read("ledger"):
            entry = record["payload"]
            if entry.get("stamp") != asdict(self.stamp) or entry.get("unit", "token") != "token":
                raise BudgetError("ledger journal stamp or unit is incompatible")
            account, intent_id = entry.get("account"), entry.get("intent_id")
            kind = entry.get("entry_kind")
            if account not in COST_ACCOUNTS or not isinstance(intent_id, str) or not intent_id:
                raise BudgetError("ledger journal contains an invalid account or intent")
            if kind == "reconcile_delta":
                delta = entry.get("settled")
                expected = expected_deltas.get(intent_id)
                if expected is None or intent_id in reconciled or expected[0] != account \
                        or not finite_number(delta) \
                        or not math.isclose(delta, expected[1], rel_tol=0.0, abs_tol=1e-9):
                    raise BudgetError("invalid or duplicate ledger reconcile delta")
                reconciled.add(intent_id)
                continue
            if kind == "reserve":
                amount = entry.get("reserved", 0.0)
                if intent_id in reserves or intent_id in settled \
                        or not finite_number(amount) or amount <= 0:
                    raise BudgetError("invalid or duplicate ledger reserve replay")
                spent[account] = checked_spend(spent, account, 0, amount)
                reserves[intent_id] = ReserveRecord(
                    reserve_id="recovered-" + entry["entry_id"], intent_id=intent_id,
                    amount=amount, account=account,
                    intent_fingerprint=entry.get("intent_fingerprint", ""))
            elif kind == "reserve_released":
                reserve = reserves.pop(intent_id, None)
                if reserve is None or reserve.account != account:
                    raise BudgetError("ledger release replay without an open reserve")
                spent[account] = checked_spend(spent, account, reserve.amount, 0)
            elif kind == "settle":
                reserve = reserves.pop(intent_id, None)
                actual = entry.get("settled")
                if reserve is None or reserve.account != account \
                        or not finite_number(actual) or actual < 0:
                    raise BudgetError("ledger settle replay without a valid open reserve")
                spent[account] = checked_spend(spent, account, reserve.amount, actual)
                expected_deltas[intent_id] = (account, reserve.amount - actual)
                settled.add(intent_id)
            else:
                raise BudgetError(f"unsupported ledger journal entry: {kind}")
        self.spent = spent
        self.reserves = reserves
        self.settled_intents = settled

    # ---- reporting --------------------------------------------------------
    def account_summary(self) -> dict:
        return {"total": self.total, "locked_control": self.locked_control,
                "spent": dict(self.spent),
                "available_main": self._available("explore"),
                "available_control": self._available("control")}
