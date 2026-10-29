"""N1 multi-currency ledger extension.

Each unit has an independent ceiling and control lock. Reservation is atomic
across all requested units; conversion happens only through a versioned rate
 table for reporting, never by adding unlike units in the ledger.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict

from core.budget.ledger import BudgetError
from core.budget.types import (COST_ACCOUNTS, AccountingStamp, CurrencyAccount,
                               ExchangeRateTable, LedgerEntry, ReserveRecord)
from core.policy.types import AllocationIntent, IntentReceipt
from core.x1.store import AppendOnlyStore


class MultiCurrencyBudgetLedger:
    def __init__(self, accounts: dict[str, CurrencyAccount], control_share: float,
                 stamp: AccountingStamp, store: AppendOnlyStore,
                 exchange: ExchangeRateTable):
        if not accounts or not 0 < control_share < 1:
            raise BudgetError("accounts must be non-empty and control_share in (0,1)")
        if set(accounts) != {a.unit for a in accounts.values()}:
            raise BudgetError("account keys must match their physical units")
        for unit, account in accounts.items():
            if account.ceiling < account.floor:
                raise BudgetError(f"预算不足以产生可证结论: {unit} below floor")
            if unit != exchange.standard_coin_anchor:
                # Fail at construction, not after an incomparable run has finished.
                exchange.convert(0, unit, exchange.standard_coin_anchor)
        self.accounts = accounts
        self.control_share = control_share
        self.stamp = stamp
        self.store = store
        self.exchange = exchange
        self.spent = {unit: {a: 0.0 for a in COST_ACCOUNTS} for unit in accounts}
        self.locked_control = {unit: a.ceiling * control_share
                               for unit, a in accounts.items()}
        self.reserves: dict[str, ReserveRecord] = {}
        self.settled_intents: set[str] = set()
        self.store.append("exchange_rate_table", {
            "table_version": exchange.table_version,
            "standard_coin_anchor": exchange.standard_coin_anchor,
            "rates": {f"{src}->{dst}": rate
                      for (src, dst), rate in exchange.rates.items()}})

    @staticmethod
    def requested_amounts(intent: AllocationIntent) -> dict[str, float]:
        if intent.requested_amounts:
            if intent.requested <= 0:
                raise BudgetError("legacy scalar must remain positive")
            return dict(intent.requested_amounts)
        return {"token": float(intent.requested)}

    def _write(self, unit: str, **kw) -> LedgerEntry:
        entry = LedgerEntry(entry_id=uuid.uuid4().hex[:12], unit=unit,
                            stamp=self.stamp, **kw)
        self.store.append("ledger", asdict(entry))
        return entry

    def _available(self, unit: str, account: str) -> float:
        committed = sum(self.spent[unit].values())
        if account == "control":
            return self.locked_control[unit] - self.spent[unit]["control"]
        return (self.accounts[unit].ceiling - self.locked_control[unit]
                - committed + self.spent[unit]["control"])

    def quote_reserve(self, intent: AllocationIntent) -> IntentReceipt:
        if intent.account not in COST_ACCOUNTS:
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason=f"unknown account {intent.account}")
        if intent.intent_id in self.settled_intents or intent.intent_id in self.reserves:
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason="intent already settled or reserved")
        if intent.reissue_count > 2:
            return IntentReceipt(intent.intent_id, "rejected_conflict",
                                 reason="reissue chain > 2; reallocate instead")
        try:
            amounts = self.requested_amounts(intent)
        except BudgetError as exc:
            return IntentReceipt(intent.intent_id, "rejected_invalid", reason=str(exc))
        if (not amounts or any(unit not in self.accounts for unit in amounts)
                or any(isinstance(amount, bool) or not isinstance(amount, (int, float))
                       or not math.isfinite(amount) or amount <= 0
                       for amount in amounts.values())):
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason="amounts must be finite, positive and use declared units")
        insufficient = [unit for unit, amount in amounts.items()
                        if self._available(unit, intent.account) < amount]
        if insufficient:
            # No unit is mutated: rejection is atomic across the whole basket.
            return IntentReceipt(intent.intent_id, "rejected_budget",
                                 reason="insufficient budget: " + ",".join(sorted(insufficient)))
        for unit, amount in amounts.items():
            self.spent[unit][intent.account] += amount
        self.reserves[intent.intent_id] = ReserveRecord(
            reserve_id=uuid.uuid4().hex[:12], intent_id=intent.intent_id,
            amounts=amounts, exchange_table_version=self.exchange.table_version)
        for unit, amount in amounts.items():
            self._write(unit, account=intent.account, reserved=amount,
                        intent_id=intent.intent_id, entry_kind="reserve")
        scalar = int(amounts["token"]) if set(amounts) == {"token"} else 0
        return IntentReceipt(intent.intent_id, "granted", granted=scalar,
                             granted_amounts=amounts)

    def pre_call_check(self) -> None:
        for unit in self.accounts:
            if sum(self.spent[unit].values()) > self.accounts[unit].ceiling:
                raise BudgetError(f"hard ceiling exceeded for {unit}; read-only settlement state")

    def release_for(self, intent: AllocationIntent) -> None:
        rec = self.reserves.pop(intent.intent_id, None)
        if rec is None or rec.status != "open":
            return
        rec.status = "released"
        for unit, amount in rec.amounts.items():
            self.spent[unit][intent.account] -= amount
            self._write(unit, account=intent.account, intent_id=intent.intent_id,
                        entry_kind="reserve_released")

    def settle(self, intent: AllocationIntent, actual_costs: dict[str, float],
               admission_outcome: bool | None = None) -> None:
        rec = self.reserves.get(intent.intent_id)
        if rec is None:
            raise BudgetError(f"settle without open reserve: {intent.intent_id}")
        if (set(actual_costs) != set(rec.amounts)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value < 0
                       for value in actual_costs.values())):
            raise BudgetError(
                "actual costs must be finite and cover exactly the reserved units")
        self.reserves.pop(intent.intent_id)
        rec.status = "settled"
        rec.settled_amounts = dict(actual_costs)
        for unit, actual in actual_costs.items():
            reserved = rec.amounts[unit]
            self.spent[unit][intent.account] += actual - reserved
            self._write(unit, account=intent.account, settled=actual,
                        intent_id=intent.intent_id,
                        admission_outcome=admission_outcome, entry_kind="settle")
            delta = reserved - actual
            if delta:
                self._write(unit, account=intent.account, settled=delta,
                            intent_id=intent.intent_id, entry_kind="reconcile_delta")
        self.settled_intents.add(intent.intent_id)

    def restore_from_journal(self) -> None:
        """Rebuild independent physical accounts without mixing or converting units."""
        if self.reserves or self.settled_intents \
                or any(value for values in self.spent.values() for value in values.values()):
            raise BudgetError("ledger restore requires a fresh, empty ledger")
        spent = {unit: {account: 0.0 for account in COST_ACCOUNTS}
                 for unit in self.accounts}
        reserves: dict[str, ReserveRecord] = {}
        settled: set[str] = set()
        for record in self.store.read("ledger"):
            entry = record["payload"]
            unit, account = entry.get("unit"), entry["account"]
            intent_id, kind = entry["intent_id"], entry["entry_kind"]
            if entry.get("stamp") != asdict(self.stamp) or unit not in self.accounts \
                    or account not in COST_ACCOUNTS or not intent_id:
                raise BudgetError("multi-currency journal is incompatible with this ledger")
            if kind == "reconcile_delta":
                continue
            if kind == "reserve":
                amount = entry.get("reserved", 0.0)
                if intent_id in settled or isinstance(amount, bool) \
                        or not isinstance(amount, (int, float)) \
                        or not math.isfinite(amount) or amount <= 0:
                    raise BudgetError("invalid multi-currency reserve replay")
                reserve = reserves.get(intent_id)
                if reserve is None:
                    reserve = ReserveRecord(
                        reserve_id="recovered-" + entry["entry_id"], intent_id=intent_id,
                        amounts={}, exchange_table_version=self.exchange.table_version)
                    reserves[intent_id] = reserve
                if unit in reserve.amounts:
                    raise BudgetError("duplicate unit in multi-currency reserve replay")
                reserve.amounts[unit] = amount
                spent[unit][account] += amount
                continue
            reserve = reserves.get(intent_id)
            if reserve is None or unit not in reserve.amounts:
                raise BudgetError("multi-currency replay without the reserved unit")
            if kind == "reserve_released":
                spent[unit][account] -= reserve.amounts.pop(unit)
                if not reserve.amounts:
                    reserves.pop(intent_id)
            elif kind == "settle":
                actual = entry.get("settled", 0.0)
                if isinstance(actual, bool) or not isinstance(actual, (int, float)) \
                        or not math.isfinite(actual) or actual < 0:
                    raise BudgetError("invalid multi-currency settle replay")
                spent[unit][account] += actual - reserve.amounts.pop(unit)
                if not reserve.amounts:
                    reserves.pop(intent_id)
                    settled.add(intent_id)
            else:
                raise BudgetError(f"unsupported ledger journal entry: {kind}")
        self.spent = spent
        self.reserves = reserves
        self.settled_intents = settled

    def to_standard(self, amounts: dict[str, float]) -> float:
        anchor = self.exchange.standard_coin_anchor
        return sum(self.exchange.convert(amount, unit, anchor)
                   for unit, amount in amounts.items())

    def account_summary(self) -> dict:
        actual = {unit: dict(values) for unit, values in self.spent.items()}
        flattened = {unit: sum(values.values()) for unit, values in actual.items()}
        return {
            "by_unit": actual,
            "locked_control": dict(self.locked_control),
            "available_main": {unit: self._available(unit, "explore")
                               for unit in self.accounts},
            "available_control": {unit: self._available(unit, "control")
                                  for unit in self.accounts},
            "standard_spent": self.to_standard(flattened),
            "standard_coin_anchor": self.exchange.standard_coin_anchor,
            "exchange_table_version": self.exchange.table_version,
        }
