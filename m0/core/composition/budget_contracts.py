"""Pure physical budget value contracts shared by the authority and projections."""
from __future__ import annotations
import hashlib
import json
from core.budget.ledger import BudgetError
from core.budget.types import finite_number
from core.composition.contracts import json_copy
from core.executor.types import EvalRequest

UNITS = frozenset({"token", "eval_count", "node", "wallclock", "gpu_hours", "usd"})
COUNTS = frozenset({"token", "eval_count", "node"})


def _canonical(value):
    return json.dumps(json_copy(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(value):
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise BudgetError(f"{label} must be nonempty text")


def _quantity(value, unit, label, *, positive=False):
    if type(value) not in (int, float) or not finite_number(value) or value < 0 \
            or positive and value == 0 or unit in COUNTS and type(value) is not int:
        raise BudgetError(f"{label}.{unit} must be a finite nonnegative physical quantity"
                          + (" (integer count)" if unit in COUNTS else ""))


def _basket(value, label, *, units=None, nonempty=True):
    if type(value) is not dict or nonempty and not value or set(value) - UNITS \
            or units is not None and set(value) != set(units):
        raise BudgetError(f"{label} must explicitly cover its configured physical units")
    for unit, amount in value.items():
        _quantity(amount, unit, label)
    return json_copy(value)


def _request(data):
    if type(data) is not dict or "fidelity" not in data \
            or set(data) - {"fidelity", "split_id", "seed_set", "time_limit", "budget_token", "resume_from"}:
        raise BudgetError("fidelity rung contains unsupported request fields")
    request = EvalRequest(**json_copy(data))
    try:
        request.validate()
    except (TypeError, ValueError) as error:
        raise BudgetError("invalid fidelity rung") from error
    if request.split_id != "dev":
        raise BudgetError("budget fidelity rungs may allocate only dev exploration")
    return request


