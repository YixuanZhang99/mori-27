"""N1 multi-currency ledger extension.

Each unit has an independent ceiling and control lock. Reservation is atomic
across all requested units; conversion happens only through a versioned rate
 table for reporting, never by adding unlike units in the ledger.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict

from core.budget.ledger import (BudgetError, checked_spend, intent_fingerprint,
                                validate_binding, validate_intent)
from core.budget.types import (COST_ACCOUNTS, AccountingStamp, CurrencyAccount,
                               ExchangeRateTable, LedgerEntry, ReserveRecord, finite_number)
from core.policy.types import AllocationIntent, IntentReceipt
from core.x1.store import AppendOnlyStore


class MultiCurrencyBudgetLedger:
    def __init__(self, accounts: dict[str, CurrencyAccount], control_share: float,
                 stamp: AccountingStamp, store: AppendOnlyStore,
                 exchange: ExchangeRateTable):
        if not accounts or not finite_number(control_share) or not 0 < control_share < 1:
            raise BudgetError("accounts must be non-empty and control_share in (0,1)")
        if set(accounts) != {a.unit for a in accounts.values()}:
            raise BudgetError("account keys must match their physical units")
        for unit, account in accounts.items():
            if not finite_number(account.ceiling) or not finite_number(account.floor) \
                    or account.ceiling <= 0 or account.floor < 0 \
                    or account.ceiling < account.floor:
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
        validate_intent(intent)
        if intent.requested_amounts:
            return dict(intent.requested_amounts)
        return {"token": intent.requested}

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
        try:
            amounts = self.requested_amounts(intent)
            fingerprint = intent_fingerprint(intent)
        except BudgetError as exc:
            return IntentReceipt(intent.intent_id, "rejected_invalid", reason=str(exc))
        if intent.intent_id in self.settled_intents or intent.intent_id in self.reserves:
            return IntentReceipt(intent.intent_id, "rejected_invalid",
                                 reason="intent already settled or reserved")
        if intent.reissue_count > 2:
            return IntentReceipt(intent.intent_id, "rejected_conflict",
                                 reason="reissue chain > 2; reallocate instead")
        if (not amounts or any(unit not in self.accounts for unit in amounts)
                or any(not finite_number(amount) or amount <= 0
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
            amounts=dict(amounts), exchange_table_version=self.exchange.table_version,
            account=intent.account, intent_fingerprint=fingerprint)
        for unit, amount in amounts.items():
            self._write(unit, account=intent.account, reserved=amount,
                        intent_id=intent.intent_id, entry_kind="reserve",
                        intent_fingerprint=fingerprint)
        scalar = int(amounts["token"]) if set(amounts) == {"token"} else 0
        return IntentReceipt(intent.intent_id, "granted", granted=scalar,
                             granted_amounts=dict(amounts))

    def pre_call_check(self) -> None:
        for unit in self.accounts:
            if any(not finite_number(value) or value < 0
                   for value in self.spent[unit].values()) \
                    or sum(self.spent[unit].values()) > self.accounts[unit].ceiling:
                raise BudgetError(f"hard ceiling exceeded for {unit}; read-only settlement state")

    def release_for(self, intent: AllocationIntent) -> None:
        rec = self.reserves.get(intent.intent_id)
        if rec is None or rec.status != "open":
            return
        validate_binding(intent, rec)
        updated = {unit: checked_spend(self.spent[unit], rec.account, amount, 0)
                   for unit, amount in rec.amounts.items()}
        self.reserves.pop(intent.intent_id)
        rec.status = "released"
        for unit, amount in rec.amounts.items():
            self.spent[unit][rec.account] = updated[unit]
            self._write(unit, account=intent.account, intent_id=intent.intent_id,
                        entry_kind="reserve_released")
        if rec.settled_amounts:
            # A recovered basket can have durable settlement for some units and
            # open reserves for others. Releasing the remainder cannot renew it.
            self.settled_intents.add(intent.intent_id)

    def settle(self, intent: AllocationIntent, actual_costs: dict[str, float],
               admission_outcome: bool | None = None) -> None:
        rec = self.reserves.get(intent.intent_id)
        if rec is None:
            raise BudgetError(f"settle without open reserve: {intent.intent_id}")
        validate_binding(intent, rec)
        if (not isinstance(actual_costs, dict) or set(actual_costs) != set(rec.amounts)
                or any(not finite_number(value) or value < 0
                       for value in actual_costs.values())):
            raise BudgetError(
                "actual costs must be finite and cover exactly the reserved units")
        updated = {unit: checked_spend(self.spent[unit], rec.account,
                                      rec.amounts[unit], actual)
                   for unit, actual in actual_costs.items()}
        self.reserves.pop(intent.intent_id)
        rec.status = "settled"
        rec.settled_amounts = dict(actual_costs)
        for unit, actual in actual_costs.items():
            reserved = rec.amounts[unit]
            self.spent[unit][rec.account] = updated[unit]
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
        reserved_units: dict[str, set[str]] = {}
        closing: set[str] = set()
        expected_deltas: dict[tuple[str, str], tuple[str, float]] = {}
        reconciled: set[tuple[str, str]] = set()
        for record in self.store.read("ledger"):
            entry = record["payload"]
            unit, account = entry.get("unit"), entry.get("account")
            intent_id, kind = entry.get("intent_id"), entry.get("entry_kind")
            if entry.get("stamp") != asdict(self.stamp) or unit not in self.accounts \
                    or account not in COST_ACCOUNTS \
                    or not isinstance(intent_id, str) or not intent_id:
                raise BudgetError("multi-currency journal is incompatible with this ledger")
            if kind == "reconcile_delta":
                key, delta = (intent_id, unit), entry.get("settled")
                expected = expected_deltas.get(key)
                if expected is None or key in reconciled or expected[0] != account \
                        or not finite_number(delta) \
                        or not math.isclose(delta, expected[1], rel_tol=0.0, abs_tol=1e-9):
                    raise BudgetError("invalid or duplicate multi-currency reconcile delta")
                reconciled.add(key)
                continue
            if kind == "reserve":
                amount = entry.get("reserved", 0.0)
                if intent_id in settled or intent_id in closing \
                        or not finite_number(amount) or amount <= 0:
                    raise BudgetError("invalid multi-currency reserve replay")
                reserve = reserves.get(intent_id)
                if reserve is None:
                    reserve = ReserveRecord(
                        reserve_id="recovered-" + entry["entry_id"], intent_id=intent_id,
                        amounts={}, exchange_table_version=self.exchange.table_version,
                        account=account,
                        intent_fingerprint=entry.get("intent_fingerprint", ""))
                    reserves[intent_id] = reserve
                if reserve.account != account or reserve.intent_fingerprint != entry.get(
                        "intent_fingerprint", ""):
                    raise BudgetError("multi-currency reserve identity differs across units")
                if unit in reserved_units.setdefault(intent_id, set()):
                    raise BudgetError("duplicate unit in multi-currency reserve replay")
                reserved_units[intent_id].add(unit)
                reserve.amounts[unit] = amount
                spent[unit][account] = checked_spend(spent[unit], account, 0, amount)
                continue
            reserve = reserves.get(intent_id)
            if reserve is None or unit not in reserve.amounts or reserve.account != account:
                raise BudgetError("multi-currency replay without the reserved unit")
            closing.add(intent_id)
            if kind == "reserve_released":
                spent[unit][account] = checked_spend(
                    spent[unit], account, reserve.amounts.pop(unit), 0)
                if not reserve.amounts:
                    reserves.pop(intent_id)
                    if any(key[0] == intent_id for key in expected_deltas):
                        settled.add(intent_id)
                    else:
                        reserved_units.pop(intent_id)
                        closing.remove(intent_id)
            elif kind == "settle":
                actual = entry.get("settled")
                if not finite_number(actual) or actual < 0:
                    raise BudgetError("invalid multi-currency settle replay")
                reserved = reserve.amounts.pop(unit)
                spent[unit][account] = checked_spend(spent[unit], account, reserved, actual)
                expected_deltas[(intent_id, unit)] = (account, reserved - actual)
                if reserve.settled_amounts is None:
                    reserve.settled_amounts = {}
                reserve.settled_amounts[unit] = actual
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
