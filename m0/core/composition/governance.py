"""Frozen control inputs and restricted component storage for governed runs.

These boundaries prevent accidental access through the declared interfaces. They
are not a sandbox for malicious Python factories or a proof of supplier randomness.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from core.composition.contracts import GovernanceConfig, json_copy


def digest(value: Any) -> str:
    encoded = json.dumps(json_copy(value), sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ControlPlan:
    """An immutable canonical plan; callers receive detached dictionary views."""

    _json: str

    @classmethod
    def freeze(cls, governance: GovernanceConfig | dict[str, Any], *, task_desc: str,
               initial_context: dict[str, Any], max_generations: int,
               units) -> "ControlPlan":
        if not isinstance(governance, GovernanceConfig):
            governance = GovernanceConfig.from_dict(governance)
        if type(task_desc) is not str or type(initial_context) is not dict:
            raise ValueError("frozen control inputs require task text and a context object")
        if type(max_generations) is not int or max_generations < 0:
            raise ValueError("control schedule requires a nonnegative generation limit")
        controls = governance.controls
        if controls["after_main_cycles"][-1] > max_generations + 1:
            raise ValueError("control schedule exceeds max_generations + 1")
        if any(set(basket) != set(units) for basket in controls["reservations"].values()):
            raise ValueError("control reservations must cover exactly the configured physical units")
        payload = {"schema_version": 1, "task_desc": task_desc,
                   "initial_context": json_copy(initial_context),
                   "initial_task_sha256": digest(task_desc),
                   "initial_context_sha256": digest(initial_context), "slots": []}
        for index, after in enumerate(controls["after_main_cycles"]):
            payload["slots"].append({"slot_id": f"control-{index:04d}",
                "after_main_cycles": after, "seed": controls["seed"] + index,
                **{name: controls[name] for name in (
                    "provider", "domain", "operator", "request", "reservations")}})
        payload["plan_ref"] = digest(payload)
        return cls(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False))

    @property
    def plan_ref(self) -> str:
        return self.to_dict()["plan_ref"]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._json)


# Component writes are enveloped, so no component can impersonate an authority
# record even if a custom factory chooses a misleading local record name.
_AUTHORITY_PREFIXES = ("composed_", "hierarchical_", "governed_", "control_",
                       "audit_", "worktree_", "budget_", "replay_")


class LaneStoreView:
    """Expose only records written by the same lane, slot and component.

    The view deliberately has no path property. Root runtime, budget and executor
    authorities keep the original store. An unqualified read filters silently;
    an explicit authority query or write fails instead of implying an empty log.
    """

    __slots__ = ("__store", "__lane", "__slot_id", "__component")

    def __init__(self, store, *, lane: str, component: str, slot_id: str | None = None):
        if lane not in {"main", "control"} or type(lane) is not str:
            raise ValueError("store lane must be main or control")
        if type(component) is not str or not component.strip():
            raise ValueError("store component must be nonempty text")
        if lane == "main" and slot_id is not None or lane == "control" and (
                type(slot_id) is not str or not slot_id.strip()):
            raise ValueError("control store requires a slot; main store cannot have a slot")
        self.__store = store
        self.__lane, self.__slot_id, self.__component = lane, slot_id, component

    @property
    def lane(self):
        return self.__lane

    @property
    def slot_id(self):
        return self.__slot_id

    @property
    def component(self):
        return self.__component

    @staticmethod
    def _check_kind(kind):
        if type(kind) is not str or not kind.strip():
            raise ValueError("component record kind must be nonempty text")
        if kind.startswith(_AUTHORITY_PREFIXES):
            raise PermissionError("component cannot access authority or other-lane records")

    def append(self, kind, payload):
        self._check_kind(kind)
        if is_dataclass(payload):
            payload = asdict(payload)
        self.__store.append("governed_component", {"lane": self.lane,
            "slot_id": self.slot_id, "component": self.component,
            "kind": kind, "payload": json_copy(payload, label="component record")})

    def read(self, kind=None):
        if kind is not None:
            self._check_kind(kind)
        for record in self.__store.read("governed_component"):
            payload = record["payload"]
            if (payload.get("lane"), payload.get("slot_id"), payload.get("component")) != (
                    self.lane, self.slot_id, self.component):
                continue
            if kind is None or payload.get("kind") == kind:
                yield {"kind": payload["kind"], "payload": json_copy(payload["payload"])}


def validate_factory_governance(kind: str, declaration: Any, *, reservation=None,
                                phase_reservations=None, external_bridges=()) -> dict:
    """Validate trusted factory capabilities without instantiating adapters.

    ``deterministic_fixture`` explicitly disclaims stochastic IID sampling.
    ``independent`` is an adapter/supplier assertion, separate from enforced
    fresh objects. Parameters must be actually applied, never an ignored knob.
    Schema 1 refuses external money. Schema 2 requires an explicitly installed
    bridge and finite ordinal caps; the runtime still owns dual admission.
    """
    if type(declaration) is not dict:
        if kind == "operator":
            raise ValueError("control operator requires an explicit parentless governance declaration")
        raise ValueError(f"{kind} requires an explicit registered governance declaration")
    value = json_copy(declaration, label=f"{kind} governance declaration")
    base = {"schema_version", "fresh_session", "state_independent"}
    if kind == "operator":
        if set(value) != {"schema_version", "parentless"} or type(value["schema_version"]) is not int \
                or value["schema_version"] != 1 or value["parentless"] is not True:
            raise ValueError("control operator must explicitly declare parentless operation")
        return value
    if kind == "provider":
        fields = base | {"sampling", "call_bound", "external_currency"}
    elif kind == "domain":
        fields = base
    else:
        raise ValueError("unsupported governance factory kind")
    external = kind == "provider" and type(value.get("schema_version")) is int and value["schema_version"] == 2
    if external:
        fields |= {"phase_call_limits"}
    if set(value) != fields or type(value["schema_version"]) is not int or value["schema_version"] != (2 if external else 1) \
            or value["fresh_session"] is not True or value["state_independent"] is not True:
        raise ValueError(f"{kind} requires versioned fresh and independent session capability")
    if kind == "provider":
        sampling = value["sampling"]
        if type(sampling) is not dict or set(sampling) != {"method", "parameters", "applied"} \
                or sampling["method"] not in ({"independent", "deterministic_fixture", "supplier_unverified"} if external
                                              else {"independent", "deterministic_fixture"}) \
                or type(sampling["parameters"]) is not dict or sampling["applied"] is not True:
            raise ValueError("provider requires an explicitly applied supported sampling contract")
        bound = value["call_bound"]
        if type(bound) is not dict or set(bound) != {"kind", "units"} or bound["kind"] != "hard" \
                or type(bound["units"]) is not dict or not bound["units"]:
            raise ValueError("provider requires a defensible hard total-call bound")
        if set(bound["units"]) != {"token"}:
            raise ValueError("provider hard call bound supports exactly the metered token unit")
        if type(bound["units"]["token"]) is not int or bound["units"]["token"] < 0:
            raise ValueError("provider hard call bound requires nonnegative integer tokens")
        if external:
            if bound["units"]["token"] == 0:
                raise ValueError("external provider requires a positive hard token bound")
            authority = value["external_currency"]
            if type(authority) is not dict or set(authority) != {"schema_version", "bridge"} or \
                    type(authority["schema_version"]) is not int or authority["schema_version"] != 1 or \
                    type(authority["bridge"]) is not str or authority["bridge"] not in external_bridges:
                raise ValueError("external provider requires an explicitly installed versioned bridge capability")
            caps = value["phase_call_limits"]
            if type(caps) is not dict or set(caps) not in ({"operator", "evaluation"}, {"planning", "operator", "evaluation"}) or any(
                    type(caps[phase]) is not int or caps[phase] < (1 if phase == "operator" else 0)
                    for phase in caps):
                raise ValueError("external provider requires finite provider phase ordinal limits")
            if phase_reservations is not None:
                for phase, cap in caps.items():
                    basket = phase_reservations.get(phase)
                    if type(basket) is not dict or "token" not in basket or cap * bound["units"]["token"] > basket["token"]:
                        raise ValueError("external phase call bounds exceed frozen physical reservations")
        for unit, amount in bound["units"].items():
            if unit not in {"token", "node", "eval_count", "wallclock", "gpu_hours", "usd"} \
                    or type(amount) not in (int, float) or amount < 0 \
                    or unit in {"token", "node", "eval_count"} and type(amount) is not int:
                raise ValueError("provider hard call bound has invalid physical units")
            if reservation is not None and (unit not in reservation or amount * (value["phase_call_limits"]["operator"] if external else 1) > reservation[unit]):
                raise ValueError("provider hard call bound exceeds control operator reservation")
        if reservation is not None and "token" in reservation and "token" not in bound["units"]:
            raise ValueError("provider hard call bound must cover token consumption")
        if not external and value["external_currency"] is not False:
            raise ValueError("external currency protection is unsupported; formal governance fails closed")
    return value
