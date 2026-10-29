"""M3 types (M0 kernel subset). See 开发指南 M3 页 §1."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

CostAccountKind = Literal["explore", "exploit", "reeval", "control",
                          "repair", "handoff", "overhead"]
COST_ACCOUNTS = ("explore", "exploit", "reeval", "control",
                 "repair", "handoff", "overhead")
BudgetUnit = Literal["token", "usd", "eval_count", "node", "wallclock", "gpu_hours"]
BUDGET_UNITS = ("token", "usd", "eval_count", "node", "wallclock", "gpu_hours")


def finite_number(value) -> bool:
    """Accept real ledger numbers without coercing booleans or numeric strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class AccountingStamp:
    supplier: str
    model_version: str
    tokenizer_version: str
    price_table_version: str
    date: str


@dataclass
class CurrencyAccount:
    """One physical budget dimension; values are never mixed across units."""
    unit: BudgetUnit
    ceiling: float
    floor: float = 0.0
    conversion_to_progress: Optional[float] = None

    def __post_init__(self):
        if self.unit not in BUDGET_UNITS:
            raise ValueError(f"unknown budget unit: {self.unit}")
        if not finite_number(self.ceiling) or not finite_number(self.floor) \
                or self.ceiling <= 0 or self.floor < 0 or self.floor > self.ceiling:
            raise ValueError("invalid currency account bounds")
        if self.conversion_to_progress is not None and (
                not finite_number(self.conversion_to_progress)
                or self.conversion_to_progress <= 0):
            raise ValueError("conversion_to_progress must be finite and positive")


@dataclass(frozen=True)
class ExchangeRateTable:
    """Versioned explicit conversion layer; old ledger rows are never rewritten."""
    table_version: str
    rates: dict[tuple[str, str], float]
    standard_coin_anchor: str = "token"

    def __post_init__(self):
        if not self.table_version or not self.standard_coin_anchor:
            raise ValueError("exchange table and standard-coin anchor must be versioned")
        if any(not finite_number(rate) or rate <= 0 for rate in self.rates.values()):
            raise ValueError("exchange rates must be finite and positive")

    def convert(self, amount: float, from_unit: str, to_unit: str) -> float:
        if from_unit == to_unit:
            return amount
        direct = self.rates.get((from_unit, to_unit))
        if direct is not None:
            return amount * direct
        inverse = self.rates.get((to_unit, from_unit))
        if inverse is not None:
            return amount / inverse
        raise ValueError(f"no explicit rate: {from_unit}->{to_unit}@{self.table_version}")


@dataclass
class LedgerEntry:
    entry_id: str
    account: CostAccountKind
    unit: str = "token"  # M0 single-currency (exemption registered in ADR-0 v2)
    reserved: float = 0.0
    settled: float = 0.0
    intent_id: str = ""
    admission_outcome: Optional[bool] = None
    stamp: Optional[AccountingStamp] = None
    entry_kind: Literal["reserve", "settle", "reserve_released",
                        "exception_appropriation", "reconcile_delta"] = "settle"
    intent_fingerprint: str = ""


@dataclass
class ReserveRecord:
    reserve_id: str
    intent_id: str
    amount: float = 0.0
    settled_amount: Optional[float] = None
    status: Literal["open", "settled", "released"] = "open"
    amounts: dict[str, float] = field(default_factory=dict)
    settled_amounts: Optional[dict[str, float]] = None
    exchange_table_version: str = ""
    account: str = ""
    intent_fingerprint: str = ""
