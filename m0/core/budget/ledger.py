"""M3 engine (M0): quote_reserve / settle / three-way reject / control lock /
reeval floor / hard cap pre-call intercept / intent reconciliation.

Boundary: M3 only quotes, reserves, settles, rejects. It NEVER downgrades an
intent (allocation semantics have a single author: M1). No LLM anywhere here.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict

from core.budget.types import (COST_ACCOUNTS, AccountingStamp, LedgerEntry,
                               ReserveRecord)
from core.policy.types import AllocationIntent, IntentReceipt
from core.x1.store import AppendOnlyStore


class BudgetError(Exception):
    pass


class BudgetLedger:
    def __init__(self, total_budget: int, control_share: float,
                 reeval_floor: int, stamp: AccountingStamp,
                 store: AppendOnlyStore):
        if not 0 < control_share < 1:
            raise BudgetError("control_share must be in (0,1)")
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
        if intent.account not in COST_ACCOUNTS:
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason=f"unknown account {intent.account}")
        if intent.requested <= 0:
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason="requested must be > 0")
        if intent.intent_id in self.settled_intents:
            # J9: an intent past settlement may not be renewed.
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason="intent already settled")
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
            amount=intent.requested)
        self._write(account=intent.account, reserved=intent.requested,
                    intent_id=intent.intent_id, entry_kind="reserve")
        return IntentReceipt(intent.intent_id, "granted", granted=intent.requested)

    def pre_call_check(self) -> None:
        """J4: terminate-before-call. Alerting alone is a forbidden anti-pattern."""
        if sum(self.spent.values()) > self.total:
            raise BudgetError("hard ceiling exceeded; read-only settlement state")

    # ---- settle / release / reconcile ------------------------------------
    def release_for(self, intent: AllocationIntent) -> None:
        """R4 (1): synchronously release the correct account; no ghost reserves."""
        rec = self.reserves.pop(intent.intent_id, None)
        if rec is None or rec.status != "open":
            return
        self.spent[intent.account] -= rec.amount
        rec.status = "released"
        self._write(account=intent.account, intent_id=intent.intent_id,
                    entry_kind="reserve_released")

    def settle(self, intent: AllocationIntent, actual_cost: int,
               admission_outcome: bool | None = None) -> None:
        rec = self.reserves.pop(intent.intent_id, None)
        if rec is None:
            raise BudgetError(f"settle without open reserve: {intent.intent_id}")
        rec.status = "settled"
        rec.settled_amount = actual_cost
        # Actual replaces reserved; difference is settled back (多退少补).
        self.spent[intent.account] += actual_cost - rec.amount
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
        if intent.intent_id not in self.settled_intents \
                or intent.intent_id in self.reserves:
            raise BudgetError("reconcile requires a settled intent without an open reserve")
        entries = [record["payload"] for record in self.store.read("ledger")
                   if record["payload"].get("intent_id") == intent.intent_id]
        reserves = [entry for entry in entries if entry["entry_kind"] == "reserve"]
        settlements = [entry for entry in entries if entry["entry_kind"] == "settle"]
        deltas = [entry for entry in entries if entry["entry_kind"] == "reconcile_delta"]
        if len(reserves) != 1 or len(settlements) != 1 or len(deltas) > 1 \
                or settlements[0]["settled"] != actual_cost \
                or settlements[0]["account"] != intent.account:
            raise BudgetError("settled intent evidence is not unique or cost-matched")
        expected = reserves[0]["reserved"] - actual_cost
        if deltas:
            if not math.isclose(deltas[0]["settled"], expected,
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
        for record in self.store.read("ledger"):
            entry = record["payload"]
            if entry.get("stamp") != asdict(self.stamp) or entry.get("unit", "token") != "token":
                raise BudgetError("ledger journal stamp or unit is incompatible")
            account, intent_id = entry["account"], entry["intent_id"]
            kind = entry["entry_kind"]
            if account not in COST_ACCOUNTS or not intent_id:
                raise BudgetError("ledger journal contains an invalid account or intent")
            if kind == "reconcile_delta":
                continue
            if kind == "reserve":
                amount = entry.get("reserved", 0.0)
                if intent_id in reserves or intent_id in settled \
                        or isinstance(amount, bool) or not isinstance(amount, (int, float)) \
                        or not math.isfinite(amount) or amount <= 0:
                    raise BudgetError("invalid or duplicate ledger reserve replay")
                spent[account] += amount
                reserves[intent_id] = ReserveRecord(
                    reserve_id="recovered-" + entry["entry_id"], intent_id=intent_id,
                    amount=amount)
            elif kind == "reserve_released":
                reserve = reserves.pop(intent_id, None)
                if reserve is None:
                    raise BudgetError("ledger release replay without an open reserve")
                spent[account] -= reserve.amount
            elif kind == "settle":
                reserve = reserves.pop(intent_id, None)
                actual = entry.get("settled", 0.0)
                if reserve is None or isinstance(actual, bool) \
                        or not isinstance(actual, (int, float)) \
                        or not math.isfinite(actual) or actual < 0:
                    raise BudgetError("ledger settle replay without a valid open reserve")
                spent[account] += actual - reserve.amount
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
