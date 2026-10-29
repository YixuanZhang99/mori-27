"""Three-level views of one physical operation journal, with no currency mixing.

Every reserve or settlement is one journal record containing its whole basket.
Global, direction and candidate amounts are projections of those same records,
never three independent charges. Allocation and stopping rules are explicit
deterministic policies, not claims of statistical convergence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from decimal import Decimal

from core.budget.ledger import BudgetError
from core.budget.types import AccountingStamp, finite_number
from core.composition.contracts import json_copy
from core.executor.types import Candidate, EvalRequest, EvalStatus

UNITS = frozenset({"token", "eval_count", "node", "wallclock", "gpu_hours", "usd"})
COUNTS = frozenset({"token", "eval_count", "node"})
OPERATIONS = frozenset({"planning", "operator", "dev", "dev_baseline", "admission", "final"})
JOURNAL_KIND = "hierarchical_budget"


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


def hierarchical_options(options):
    """Pure strict preflight suitable for Registry.register(validate_options=...)."""
    allowed = {"limits", "reservation", "operation_reservations", "fidelity_rungs",
               "rung_by", "rung_every", "convergence"}
    if type(options) is not dict or set(options) - allowed \
            or not {"limits", "reservation", "fidelity_rungs"}.issubset(options):
        raise BudgetError("hierarchical budget requires limits, reservation and fidelity_rungs")
    limits = options["limits"]
    if type(limits) is not dict or set(limits) != {"global", "direction", "candidate"}:
        raise BudgetError("limits requires global, direction and candidate physical baskets")
    global_limits = _basket(limits["global"], "global limits")
    if not any(global_limits.values()):
        raise BudgetError("at least one global limit must be positive")
    for level in ("direction", "candidate"):
        scoped = _basket(limits[level], f"{level} limits")
        if set(scoped) - set(global_limits):
            raise BudgetError("direction/candidate units require a global physical account")
    _basket(options["reservation"], "reservation", units=global_limits)
    overrides = options.get("operation_reservations", {})
    if type(overrides) is not dict or set(overrides) - OPERATIONS:
        raise BudgetError("unknown operation reservation override")
    for operation, amounts in overrides.items():
        _basket(amounts, f"{operation} reservation", units=global_limits)
    rungs = options["fidelity_rungs"]
    if type(rungs) is not list or not rungs:
        raise BudgetError("fidelity_rungs must be a nonempty list")
    for rung in rungs:
        _request(rung)
    if type(options.get("rung_by", "direction_calls")) is not str \
            or options.get("rung_by", "direction_calls") not in {"direction_calls", "depth"}:
        raise BudgetError("rung_by must be direction_calls or depth")
    every = options.get("rung_every", 1)
    if type(every) is not int or every < 1:
        raise BudgetError("rung_every must be a positive integer")
    convergence = options.get("convergence")
    if convergence is not None:
        if type(convergence) is not dict or set(convergence) - {
                "patience", "min_samples", "min_improvement", "metric", "direction"} \
                or not {"patience", "min_samples"}.issubset(convergence):
            raise BudgetError("convergence requires explicit patience and min_samples")
        for key in ("patience", "min_samples"):
            if type(convergence[key]) is not int or convergence[key] < 1:
                raise BudgetError("convergence counters must be positive integers")
        _text(convergence.get("metric", "dev/score"), "convergence metric")
        direction = convergence.get("direction", "maximize")
        if type(direction) is not str or direction not in {"maximize", "minimize"}:
            raise BudgetError("convergence direction must be maximize or minimize")
        _quantity(convergence.get("min_improvement", 0.0), "wallclock", "minimum improvement")


@dataclass(frozen=True)
class ReservationReceipt:
    intent_id: str
    verdict: str
    fingerprint: str
    amounts: dict[str, int | float]
    reason: str = ""

    @property
    def granted(self):
        return self.verdict == "granted"


@dataclass(frozen=True)
class ConvergenceSignal:
    rule: str
    reason: str
    statistical: bool = False


def _empty_state():
    return {"operations": {}, "observations": {}, "halt_reasons": []}


class HierarchicalBudget:
    def __init__(self, options, stamp: AccountingStamp, store):
        hierarchical_options(options)
        if not isinstance(stamp, AccountingStamp):
            raise BudgetError("hierarchical budget requires an AccountingStamp")
        self.options, self.stamp, self.store = json_copy(options), stamp, store
        self.units = tuple(sorted(self.options["limits"]["global"]))
        self._config_ref = _hash(self.options)
        self._data = _empty_state()
        self._seq, self._head = 0, None
        self._lock = threading.RLock()

    def _reservation(self, operation):
        return json_copy(self.options.get("operation_reservations", {}).get(
            operation, self.options["reservation"]))

    @staticmethod
    def _decimal(value):
        return Decimal(str(value))

    def _totals(self, data, *, direction_id=None, candidate_id=None):
        used = {unit: Decimal(0) for unit in self.units}
        reserved = {unit: Decimal(0) for unit in self.units}
        for operation in data["operations"].values():
            intent = operation["intent"]
            if direction_id is not None and intent["direction_id"] != direction_id \
                    or candidate_id is not None and intent["candidate"]["id"] != candidate_id:
                continue
            if operation["status"] == "settled":
                for unit, amount in operation["actual_costs"].items():
                    used[unit] += self._decimal(amount)
            elif operation["status"] in {"reserved", "started", "unresolved"}:
                for unit, amount in intent["amounts"].items():
                    reserved[unit] += self._decimal(amount)
        return used, reserved

    def _numeric(self, unit, amount):
        number = int(amount) if unit in COUNTS else float(amount)
        if not finite_number(number):
            raise BudgetError("physical budget total overflow")
        return number

    def _view(self, data, limits, **scope):
        used, reserved = self._totals(data, **scope)
        return {"used": {unit: self._numeric(unit, value) for unit, value in used.items()},
                "reserved": {unit: self._numeric(unit, value) for unit, value in reserved.items()},
                "committed": {unit: self._numeric(unit, used[unit] + reserved[unit]) for unit in self.units},
                "remaining": {unit: self._numeric(unit, self._decimal(limit) - used[unit] - reserved[unit])
                              for unit, limit in limits.items()}}

    def _insufficient(self, data, intent):
        if data["halt_reasons"]:
            return "read-only settlement state: " + "; ".join(data["halt_reasons"])
        if any(operation["status"] == "unresolved" for operation in data["operations"].values()):
            return "unresolved physical usage prevents further paid calls"
        scopes = (("global", {}), ("direction", {"direction_id": intent["direction_id"]}),
                  ("candidate", {"candidate_id": intent["candidate"]["id"]}))
        for level, scope in scopes:
            used, reserved = self._totals(data, **scope)
            for unit, ceiling in self.options["limits"][level].items():
                if used[unit] + reserved[unit] + self._decimal(intent["amounts"][unit]) > self._decimal(ceiling):
                    return f"insufficient {level} {unit} budget"
        return None

    def _allocation(self, candidate, direction_id, depth, data):
        if not isinstance(candidate, Candidate):
            raise BudgetError("allocate requires a Candidate")
        candidate.validate()
        _text(direction_id, "direction identity")
        if self.options.get("rung_by", "direction_calls") == "depth":
            if type(depth) is not int or depth < 0:
                raise BudgetError("depth allocation requires an explicit nonnegative skeleton depth")
            value = depth
        else:
            value = sum(operation["intent"]["operation"] == "dev"
                        and operation["intent"]["direction_id"] == direction_id
                        and operation["status"] != "released"
                        for operation in data["operations"].values())
        index = min(value // self.options.get("rung_every", 1), len(self.options["fidelity_rungs"]) - 1)
        return _request(self.options["fidelity_rungs"][index])

    def allocate(self, candidate, *, direction_id=None, operation="dev", depth=None):
        """Pure request choice; only a granted dev reserve advances the call ladder."""
        if operation != "dev":
            raise BudgetError("M9 must provide admission/final requests independently of dev allocation")
        if not isinstance(candidate, Candidate):
            raise BudgetError("allocate requires a Candidate")
        with self._lock:
            return self._allocation(candidate, direction_id or candidate.id, depth, self._data)

    def _intent(self, intent_id, candidate, direction_id, operation, request, depth):
        _text(intent_id, "intent identity")
        _text(direction_id, "direction identity")
        if not isinstance(candidate, Candidate) or type(operation) is not str or operation not in OPERATIONS:
            raise BudgetError("reservation requires a Candidate and known operation")
        candidate.validate()
        if request is not None and not isinstance(request, EvalRequest):
            raise BudgetError("operation request must be an EvalRequest")
        if operation in {"dev", "dev_baseline", "admission", "final"} and request is None:
            raise BudgetError("evaluation operation requires its exact EvalRequest")
        if operation in {"planning", "operator"} and request is not None:
            raise BudgetError("non-evaluation operations cannot carry an EvalRequest")
        if request is not None:
            request.validate()
            expected_split = {"dev": "dev", "dev_baseline": "dev", "admission": "admission", "final": "final_audit"}[operation]
            if request.split_id != expected_split:
                raise BudgetError("request split differs from operation authority")
        if depth is not None and (type(depth) is not int or depth < 0):
            raise BudgetError("operation depth must be a nonnegative integer")
        return json_copy({"intent_id": intent_id, "candidate": asdict(candidate), "direction_id": direction_id,
            "operation": operation, "request": asdict(request) if request is not None else None,
            "depth": depth, "amounts": self._reservation(operation)})

    def reserve_operation(self, intent_id, candidate, direction_id, operation, *, request=None, depth=None):
        intent = self._intent(intent_id, candidate, direction_id, operation, request, depth)
        fingerprint = _hash(intent)
        with self._lock:
            if intent_id in self._data["operations"]:
                return ReservationReceipt(intent_id, "rejected_invalid", fingerprint, {}, "intent identity already used")
            reason = self._insufficient(self._data, intent)
            if reason:
                return ReservationReceipt(intent_id, "rejected_budget", fingerprint, {}, reason)
            self._commit("reserve", {"intent": intent, "fingerprint": fingerprint})
            return ReservationReceipt(intent_id, "granted", fingerprint, json_copy(intent["amounts"]))

    def start_operation(self, intent_id, *, fingerprint):
        """Optional durable call-start marker; started calls cannot be released."""
        with self._lock:
            self.pre_call_check()
            self._commit("start", {"intent_id": intent_id, "fingerprint": fingerprint})

    def settle_operation(self, intent_id, actual_costs, *, measured_units, fingerprint):
        costs = _basket(actual_costs, "actual costs", units=self.units)
        if type(measured_units) not in (list, tuple, set, frozenset) \
                or any(type(unit) is not str or unit not in UNITS for unit in measured_units) \
                or not set(self.units).issubset(measured_units):
            raise BudgetError("physical usage coverage is missing; reservation remains open")
        with self._lock:
            self._commit("settle", {"intent_id": intent_id, "fingerprint": fingerprint,
                                  "actual_costs": costs, "measured_units": sorted(set(measured_units))})

    def mark_unresolved(self, intent_id, *, fingerprint, reason):
        _text(reason, "unresolved usage reason")
        with self._lock:
            self._commit("unresolved", {"intent_id": intent_id, "fingerprint": fingerprint, "reason": reason})

    def release_operation(self, intent_id, *, fingerprint):
        with self._lock:
            self._commit("release", {"intent_id": intent_id, "fingerprint": fingerprint})

    def pre_call_check(self):
        with self._lock:
            if self._data["halt_reasons"] or any(operation["status"] == "unresolved"
                    for operation in self._data["operations"].values()):
                raise BudgetError("unresolved usage or reservation overrun requires read-only settlement")

    def _reduce(self, state, kind, data):
        operations = state["operations"]
        if kind == "reserve":
            if set(data) != {"intent", "fingerprint"}:
                raise BudgetError("invalid reserve event")
            intent = data["intent"]
            if type(intent) is not dict or set(intent) != {"intent_id", "candidate", "direction_id", "operation", "request", "depth", "amounts"}:
                raise BudgetError("invalid reservation binding")
            rebuilt = self._intent(intent["intent_id"], Candidate(**intent["candidate"]), intent["direction_id"],
                intent["operation"], EvalRequest(**intent["request"]) if intent["request"] is not None else None,
                intent["depth"])
            if rebuilt != intent or _hash(intent) != data["fingerprint"] or intent["intent_id"] in operations:
                raise BudgetError("reservation fingerprint or identity mismatch")
            if intent["operation"] == "dev" and intent["request"] != asdict(self._allocation(
                    Candidate(**intent["candidate"]), intent["direction_id"], intent["depth"], state)):
                raise BudgetError("dev request differs from the allocated fidelity rung")
            reason = self._insufficient(state, intent)
            if reason:
                raise BudgetError("journal reserve violates limits: " + reason)
            operations[intent["intent_id"]] = {"intent": intent, "fingerprint": data["fingerprint"], "status": "reserved"}
            return
        if kind == "observe":
            self._validate_observation(data)
            identifier = data["observation_id"]
            if identifier in state["observations"]:
                raise BudgetError("duplicate convergence observation")
            state["observations"][identifier] = data
            return
        required = {"start": {"intent_id", "fingerprint"}, "release": {"intent_id", "fingerprint"},
                    "unresolved": {"intent_id", "fingerprint", "reason"},
                    "settle": {"intent_id", "fingerprint", "actual_costs", "measured_units"}}
        if kind not in required or set(data) != required[kind]:
            raise BudgetError("unknown or malformed physical operation event")
        operation = operations.get(data["intent_id"])
        if operation is None or operation["fingerprint"] != data["fingerprint"]:
            raise BudgetError("operation does not match the original reservation identity")
        if kind in {"start", "release"}:
            if operation["status"] != "reserved":
                raise BudgetError("only an unstarted open reservation can start or release")
            operation["status"] = "started" if kind == "start" else "released"
        elif kind == "unresolved":
            _text(data["reason"], "unresolved reason")
            if operation["status"] not in {"reserved", "started"}:
                raise BudgetError("unresolved usage requires an open operation")
            operation["status"] = "unresolved"
            operation["unresolved_reason"] = data["reason"]
        else:
            if operation["status"] not in {"reserved", "started", "unresolved"}:
                raise BudgetError("settlement requires an open operation")
            costs = _basket(data["actual_costs"], "settlement", units=self.units)
            coverage = data["measured_units"]
            if type(coverage) is not list or any(type(unit) is not str or unit not in UNITS for unit in coverage) \
                    or coverage != sorted(set(coverage)) or not set(self.units).issubset(coverage):
                raise BudgetError("settlement omitted physical usage coverage")
            operation["status"], operation["actual_costs"] = "settled", costs
            operation["measured_units"] = coverage
            for unit, cost in costs.items():
                if self._decimal(cost) > self._decimal(operation["intent"]["amounts"][unit]):
                    state["halt_reasons"].append(f"reservation overrun for {data['intent_id']}:{unit}")
            # Truthful settlement may exceed ceilings; future reserves fail closed.
            self._view(state, self.options["limits"]["global"])

    def _commit(self, kind, data):
        data = json_copy(data, label="budget event")
        updated = copy.deepcopy(self._data)
        self._reduce(updated, kind, data)
        event = {"schema_version": 1, "seq": self._seq + 1, "previous": self._head,
                 "config_ref": self._config_ref, "stamp": asdict(self.stamp), "event": kind, "data": data}
        event["event_ref"] = _hash(event)
        self.store.append(JOURNAL_KIND, event)
        self._data, self._seq, self._head = updated, event["seq"], event["event_ref"]

    def _validate_observation(self, data):
        required = {"observation_id", "candidate_id", "attempt", "fidelity", "direction_id", "score", "status", "binding_ref", "comparison_binding", "comparison_ref"}
        if type(data) is not dict or set(data) != required or type(data["attempt"]) is not int or data["attempt"] < 1:
            raise BudgetError("invalid convergence observation")
        for key in ("candidate_id", "direction_id", "fidelity", "binding_ref"):
            _text(data[key], key)
        if data["status"] not in {status.value for status in EvalStatus}:
            raise BudgetError("unknown evaluation status in convergence observation")
        if data["score"] is not None and (type(data["score"]) not in (int, float) or not finite_number(data["score"])):
            raise BudgetError("convergence score must be finite")
        expected_id = _hash({key: data[key] for key in ("candidate_id", "attempt", "fidelity", "binding_ref")})
        if data["observation_id"] != expected_id:
            raise BudgetError("convergence observation identity differs from evidence")
        comparison = data["comparison_binding"]
        if type(comparison) is not dict or set(comparison) != {
                "request_sha256", "fidelity", "seed_set", "evaluation_context", "evaluator_version", "split_id"} \
                or comparison["fidelity"] != data["fidelity"] or comparison["split_id"] != "dev" \
                or data["comparison_ref"] != _hash(comparison):
            raise BudgetError("invalid convergence comparison binding")
        for key in ("request_sha256", "evaluator_version"):
            _text(comparison[key], key)
        if type(comparison["evaluation_context"]) is not str or comparison["seed_set"] is not None and (
                type(comparison["seed_set"]) is not list
                or any(type(seed) is not int or seed < 0 for seed in comparison["seed_set"])
                or len(set(comparison["seed_set"])) != len(comparison["seed_set"])):
            raise BudgetError("invalid convergence context or seeds")

    def _progress(self, direction_id=None):
        rule = self.options.get("convergence")
        progress = {"attempts": 0, "samples": 0, "no_improvement": 0, "best": None,
                    "stagnant": False, "comparison_ref": None, "window_resets": 0}
        if rule is None:
            return progress
        for observation in self._data["observations"].values():
            if direction_id is not None and observation["direction_id"] != direction_id:
                continue
            if progress["comparison_ref"] != observation["comparison_ref"]:
                if progress["comparison_ref"] is not None:
                    progress["window_resets"] += 1
                progress.update(attempts=0, samples=0, no_improvement=0, best=None,
                                stagnant=False, comparison_ref=observation["comparison_ref"])
            progress["attempts"] += 1
            score = observation["score"] if observation["status"] == "ok" else None
            improved = False
            if score is not None:
                progress["samples"] += 1
                if progress["best"] is None:
                    improved = True
                else:
                    gain = self._decimal(score) - self._decimal(progress["best"])
                    if rule.get("direction", "maximize") == "minimize":
                        gain = -gain
                    improved = gain > self._decimal(rule.get("min_improvement", 0.0))
            if improved:
                progress["best"], progress["no_improvement"] = score, 0
            else:
                progress["no_improvement"] += 1
        progress["stagnant"] = progress["samples"] >= rule["min_samples"] and progress["no_improvement"] >= rule["patience"]
        return progress

    def should_continue(self, branch, evidence=None):
        _text(branch, "direction identity")
        with self._lock:
            if evidence is not None and self.options.get("convergence") is not None:
                contract = evidence.eval_result.contract
                if contract is not None and contract.binding.split_id != "dev":
                    raise BudgetError("held-out admission/final evidence cannot drive search convergence")
                if contract is None and evidence.eval_result.fidelity != "dev":
                    raise BudgetError("opaque non-dev evidence cannot drive search convergence")
                metric = self.options["convergence"].get("metric", "dev/score")
                score = evidence.eval_result.metrics.get(metric)
                if evidence.eval_result.status is EvalStatus.OK and score is None:
                    raise BudgetError("convergence requires the declared public dev objective")
                binding_payload = asdict(contract.binding) if contract is not None else None
                if binding_payload is not None and binding_payload["seed_set"] is not None:
                    binding_payload["seed_set"] = list(binding_payload["seed_set"])
                binding_ref = _hash(binding_payload) if binding_payload is not None else "legacy-opaque"
                comparison = ({key: value for key, value in binding_payload.items()
                               if key in {"request_sha256", "fidelity", "seed_set", "evaluation_context", "evaluator_version", "split_id"}}
                              if contract is not None else {
                                  "request_sha256": "legacy-opaque", "fidelity": evidence.eval_result.fidelity,
                                  "seed_set": None, "evaluation_context": "", "evaluator_version": "legacy-opaque", "split_id": "dev"})
                if comparison["seed_set"] is not None:
                    comparison["seed_set"] = list(comparison["seed_set"])
                observation = {"candidate_id": evidence.candidate_id, "attempt": evidence.attempt,
                    "fidelity": evidence.eval_result.fidelity, "direction_id": branch,
                    "score": score, "status": evidence.eval_result.status.value, "binding_ref": binding_ref,
                    "comparison_binding": comparison, "comparison_ref": _hash(comparison)}
                observation["observation_id"] = _hash({key: observation[key] for key in ("candidate_id", "attempt", "fidelity", "binding_ref")})
                self._validate_observation(observation)
                previous = self._data["observations"].get(observation["observation_id"])
                if previous is not None and previous != observation:
                    raise BudgetError("convergence evidence cannot be rebound or reassigned")
                if previous is None:
                    self._commit("observe", observation)
            if self._data["halt_reasons"] or any(operation["status"] == "unresolved"
                    for operation in self._data["operations"].values()) or self._progress(branch)["stagnant"]:
                return False
            globally_used, globally_reserved = self._totals(self._data)
            if any(globally_used[unit] + globally_reserved[unit] + self._decimal(self._reservation("dev")[unit]) > self._decimal(limit)
                   for unit, limit in self.options["limits"]["global"].items()):
                return False
            used, reserved = self._totals(self._data, direction_id=branch)
            return all(used[unit] + reserved[unit] + self._decimal(self._reservation("dev")[unit]) <= self._decimal(limit)
                       for unit, limit in self.options["limits"]["direction"].items())

    def converged(self, frontier=None):
        """The signal describes observed dev progress; it makes no statistical claim."""
        with self._lock:
            if self._data["halt_reasons"]:
                return ConvergenceSignal("reservation_overrun", "; ".join(self._data["halt_reasons"]))
            if any(operation["status"] == "unresolved" for operation in self._data["operations"].values()):
                return ConvergenceSignal("unresolved_usage", "physical usage must be reconciled before another call")
            used, reserved = self._totals(self._data)
            if any(used[unit] + reserved[unit] + self._decimal(self._reservation("dev")[unit]) > self._decimal(limit)
                   for unit, limit in self.options["limits"]["global"].items()):
                return ConvergenceSignal("global_budget_exhausted", "no complete dev operation reservation fits")
            progress = self._progress()
            if progress["stagnant"]:
                return ConvergenceSignal("observed_dev_patience", f"{progress['no_improvement']} consecutive attempts without the configured improvement after {progress['samples']} valid samples")
            return None

    def state(self):
        with self._lock:
            directions = sorted({operation["intent"]["direction_id"] for operation in self._data["operations"].values()})
            candidates = sorted({operation["intent"]["candidate"]["id"] for operation in self._data["operations"].values()})
            return {"schema_version": 1, "units": list(self.units), "limits": json_copy(self.options["limits"]),
                "global": self._view(self._data, self.options["limits"]["global"]),
                "directions": {identifier: self._view(self._data, self.options["limits"]["direction"], direction_id=identifier) for identifier in directions},
                "candidates": {identifier: self._view(self._data, self.options["limits"]["candidate"], candidate_id=identifier) for identifier in candidates},
                "open_intents": sorted(identifier for identifier, operation in self._data["operations"].items()
                                       if operation["status"] in {"reserved", "started", "unresolved"}),
                "halt_reasons": list(self._data["halt_reasons"]), "progress": self._progress()}

    def account_summary(self):
        return self.state()

    def checkpoint_state(self):
        with self._lock:
            return {"schema_version": 1, "config_ref": self._config_ref, "stamp": asdict(self.stamp),
                    "seq": self._seq, "head": self._head, "state": self.state()}

    def _rebuild(self):
        data, sequence, head = _empty_state(), 0, None
        for row in self.store.read(JOURNAL_KIND):
            event = json_copy(row["payload"], label="budget journal")
            if type(event) is not dict or set(event) != {"schema_version", "seq", "previous", "config_ref", "stamp", "event", "data", "event_ref"} \
                    or type(event["schema_version"]) is not int or event["schema_version"] != 1 \
                    or type(event["seq"]) is not int or event["seq"] != sequence + 1 \
                    or event["previous"] != head or event["config_ref"] != self._config_ref \
                    or event["stamp"] != asdict(self.stamp) \
                    or event["event_ref"] != _hash({key: value for key, value in event.items() if key != "event_ref"}):
                raise BudgetError("budget journal configuration, sequence or integrity mismatch")
            self._reduce(data, event["event"], event["data"])
            sequence, head = event["seq"], event["event_ref"]
        return data, sequence, head

    def restore_from_journal(self):
        with self._lock:
            if self._seq or self._data != _empty_state():
                raise BudgetError("budget restore requires a fresh component")
            self._data, self._seq, self._head = self._rebuild()

    def restore_state(self, checkpoint):
        checkpoint = json_copy(checkpoint, label="budget checkpoint")
        with self._lock:
            if self._seq or self._data != _empty_state():
                raise BudgetError("budget restore requires a fresh component")
            data, sequence, head = self._rebuild()
            previous = self._data, self._seq, self._head
            self._data, self._seq, self._head = data, sequence, head
            try:
                if checkpoint != self.checkpoint_state():
                    raise BudgetError("budget checkpoint differs from durable operation journal")
            except Exception:
                self._data, self._seq, self._head = previous
                raise
