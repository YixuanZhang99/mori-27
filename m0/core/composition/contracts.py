"""Composition contracts for the configurable runtime.

The legacy M0 entry point remains a compatibility adapter. New components share
the canonical execution evidence types and receive scoped runtime dependencies.
Configuration contains registered names and JSON options, never import paths or
executable expressions.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvidenceRecord
from core.memory.types import ScopeContext
from core.policy.types import StateMutation
from core.x1.store import AppendOnlyStore


def json_copy(value: Any, *, label: str = "configuration") -> Any:
    """Validate actual finite JSON data and detach every nested mutable value."""
    def visit(item: Any) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                visit(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                visit(child)
            return
        raise ValueError(f"{label} must contain finite JSON values with string keys")
    visit(value)
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                 sort_keys=True, separators=(",", ":")))


def _name(value: Any, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty name without surrounding whitespace")
    return value


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _name(self.name, "component name")
        if type(self.options) is not dict:
            raise ValueError("component options must be an object")
        object.__setattr__(self, "options", json_copy(self.options, label="component options"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentSpec":
        if type(data) is not dict or set(data) - {"name", "options"} or "name" not in data:
            raise ValueError("component spec requires name and optional options only")
        return cls(data["name"], data.get("options", {}))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "options": json_copy(self.options, label="component options")}


_SINGLE_COMPONENTS = ("provider", "domain", "policy", "frontier", "memory",
                      "executor", "admission", "budget")


@dataclass(frozen=True, init=False)
class GovernanceConfig:
    """Strict opt-in configuration held as immutable canonical JSON."""

    schema_version: int
    _controls_json: str

    def __init__(self, schema_version: int, controls: dict[str, Any]):
        if type(schema_version) is not int or schema_version != 1:
            raise ValueError("governance schema_version must be integer 1")
        controls = json_copy(controls, label="governance controls")
        required = {"after_main_cycles", "seed", "provider", "domain", "operator",
                    "request", "reservations"}
        if type(controls) is not dict or set(controls) != required:
            raise ValueError("governance controls require exactly the declared schedule, factories, request and reservations")
        schedule = controls["after_main_cycles"]
        if type(schedule) is not list or not schedule or any(
                type(value) is not int or value < 0 for value in schedule) or schedule[0] != 0 \
                or any(a >= b for a, b in zip(schedule, schedule[1:])):
            raise ValueError("control schedule must start at zero and contain strictly increasing integers")
        if type(controls["seed"]) is not int or controls["seed"] < 0:
            raise ValueError("control seed must be a nonnegative integer")
        for kind in ("provider", "domain", "operator"):
            controls[kind] = ComponentSpec.from_dict(controls[kind]).to_dict()
        request = controls["request"]
        if type(request) is not dict or set(request) - {
                "fidelity", "split_id", "seed_set", "time_limit", "budget_token"} \
                or not {"fidelity", "split_id"} <= set(request):
            raise ValueError("control request requires frozen fidelity/split without resume_from")
        EvalRequest(**request).validate()
        if request["fidelity"] != "dev" or request["split_id"] != "dev":
            raise ValueError("control request must use the frozen dev split and fidelity")
        reservations = controls["reservations"]
        if type(reservations) is not dict or set(reservations) != {"operator", "evaluation"}:
            raise ValueError("control reservations require operator and evaluation baskets")
        units = None
        for phase, basket in reservations.items():
            if type(basket) is not dict or not basket or set(basket) - {
                    "token", "node", "eval_count", "wallclock", "gpu_hours", "usd"}:
                raise ValueError("control reservations require physical units")
            if units is not None and set(basket) != units:
                raise ValueError("control reservations must explicitly cover the same units")
            units = set(basket)
            for unit, value in basket.items():
                if type(value) not in (int, float) or value < 0 or \
                        unit in {"token", "node", "eval_count"} and type(value) is not int:
                    raise ValueError("control reservations require finite nonnegative physical quantities")
        if "node" in reservations["operator"] and reservations["operator"]["node"] < 1:
            raise ValueError("control operator reservation must cover at least one created node")
        if "eval_count" in reservations["evaluation"] and reservations["evaluation"]["eval_count"] < 1:
            raise ValueError("control evaluation reservation must cover at least one evaluation")
        if reservations["evaluation"].get("node", 0) != 0:
            raise ValueError("control evaluation node reservation must be zero; evaluation creates no node")
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "_controls_json", json.dumps(controls, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"), allow_nan=False))

    @property
    def controls(self) -> dict[str, Any]:
        return json.loads(self._controls_json)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GovernanceConfig":
        if type(data) is not dict or set(data) != {"schema_version", "controls"}:
            raise ValueError("governance requires schema_version and controls only")
        return cls(data["schema_version"], data["controls"])

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "controls": self.controls}


@dataclass(frozen=True)
class ExecutionConfig:
    """Detached versioned construction inputs; no executable configuration."""
    _encoded: str

    @classmethod
    def from_dict(cls, value):
        value = json_copy(value, label="execution configuration")
        if type(value) is not dict or set(value) != {"schema_version", "spec", "constructor"} \
                or type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("unsupported execution configuration")
        spec = value["spec"]
        if type(spec) is not dict or not {"role", "hypothesis_frozen", "context_projection"} <= set(spec) \
                or set(spec) - {"role", "hypothesis_frozen", "context_projection", "hypothesis"}:
            raise ValueError("execution requires an explicit role, hypothesis policy and projection")
        _name(spec["role"], "execution role")
        if type(spec["hypothesis_frozen"]) is not bool:
            raise ValueError("hypothesis_frozen must be boolean")
        projection = spec["context_projection"]
        if type(projection) is not list or any(type(x) is not str or x not in {
                "memory", "grounding", "query"} for x in projection) or len(set(projection)) != len(projection):
            raise ValueError("unsupported execution context projection")
        if spec.get("hypothesis") is not None:
            _name(spec["hypothesis"], "execution hypothesis")
        value["constructor"] = ComponentSpec.from_dict(value["constructor"]).to_dict()
        return cls(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))

    def to_dict(self):
        return json.loads(self._encoded)

    @property
    def constructor(self):
        return ComponentSpec.from_dict(self.to_dict()["constructor"])

    @property
    def spec(self):
        from core.executor.types import ExecutorSpec
        return ExecutorSpec(**self.to_dict()["spec"])


@dataclass(frozen=True)
class AssemblyConfig:
    schema_version: int
    name: str
    provider: ComponentSpec
    domain: ComponentSpec
    policy: ComponentSpec
    operators: tuple[ComponentSpec, ...]
    frontier: ComponentSpec
    memory: ComponentSpec
    executor: ComponentSpec
    admission: ComponentSpec
    budget: ComponentSpec
    skills: tuple[ComponentSpec, ...] = ()
    mode: str = "benchmark"
    knowledge: ComponentSpec | None = None
    governance: GovernanceConfig | None = None
    execution: ExecutionConfig | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in {1, 2}:
            raise ValueError("assembly schema_version must be integer 1 or 2")
        if (self.schema_version == 1 and self.execution is not None) or (
                self.schema_version == 2 and not isinstance(self.execution, ExecutionConfig)):
            raise ValueError("assembly schema 2 requires execution; schema 1 cannot enable it")
        if self.execution is not None and self.budget.name != "hierarchical":
            raise ValueError("configured construction requires hierarchical physical accounting")
        _name(self.name, "assembly name")
        if self.mode not in ("benchmark", "research") or type(self.mode) is not str:
            raise ValueError("assembly mode must be benchmark or research")
        for name in _SINGLE_COMPONENTS:
            if not isinstance(getattr(self, name), ComponentSpec):
                raise ValueError(f"assembly {name} must be a ComponentSpec")
        for name in ("operators", "skills"):
            values = getattr(self, name)
            if type(values) not in (list, tuple) or any(
                    not isinstance(value, ComponentSpec) for value in values):
                raise ValueError(f"assembly {name} must contain ComponentSpec objects")
            object.__setattr__(self, name, tuple(values))
        if not self.operators:
            raise ValueError("assembly operators must be non-empty")
        if len({operator.name for operator in self.operators}) != len(self.operators):
            raise ValueError("assembly operator names must be unique for policy selection")
        if self.knowledge is not None:
            if not isinstance(self.knowledge, ComponentSpec):
                raise ValueError("knowledge must be a ComponentSpec")
            if self.mode != "research":
                raise ValueError("knowledge requires research mode; benchmark access is disabled")

        if self.governance is not None:
            if not isinstance(self.governance, GovernanceConfig):
                raise ValueError("assembly governance must be a GovernanceConfig")
            if self.budget.name != "hierarchical":
                raise ValueError("governance requires a hierarchical physical budget")
            all_limits = self.budget.options.get("limits")
            if type(all_limits) is not dict or type(all_limits.get("global")) is not dict:
                raise ValueError("governance budget limits require a global physical basket")
            limits = all_limits["global"]
            controls = self.governance.controls
            baskets = controls["reservations"]
            if not limits or any(set(basket) != set(limits) for basket in baskets.values()):
                raise ValueError("control reservations must explicitly cover configured physical units")
            for unit, limit in limits.items():
                if type(limit) not in (int, float) or limit < 0:
                    raise ValueError("governance requires finite nonnegative global limits")
                if len(controls["after_main_cycles"]) * sum(basket[unit] for basket in baskets.values()) > limit:
                    raise ValueError("control holdback exceeds global physical capacity")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssemblyConfig":
        required = {"schema_version", "name", "operators", *_SINGLE_COMPONENTS}
        allowed = required | {"skills", "mode", "knowledge", "governance", "execution"}
        if type(data) is not dict:
            raise ValueError("assembly configuration must be an object")
        data = json_copy(data, label="assembly configuration")
        if required - data.keys():
            raise ValueError("assembly configuration missing fields: "
                             + ", ".join(sorted(required - data.keys())))
        if data.keys() - allowed:
            raise ValueError("unknown assembly fields: "
                             + ", ".join(sorted(data.keys() - allowed)))
        for key in ("operators", "skills"):
            if type(data.get(key, [])) is not list:
                raise ValueError(f"assembly {key} must be a list")
        return cls(
            schema_version=data["schema_version"], name=data["name"],
            operators=tuple(ComponentSpec.from_dict(item) for item in data["operators"]),
            skills=tuple(ComponentSpec.from_dict(item) for item in data.get("skills", [])),
            mode=data.get("mode", "benchmark"),
            execution=ExecutionConfig.from_dict(data["execution"]) if "execution" in data else None,
            governance=GovernanceConfig.from_dict(data["governance"]) if "governance" in data else None,
            knowledge=ComponentSpec.from_dict(data["knowledge"]) if data.get("knowledge") is not None else None,
            **{key: ComponentSpec.from_dict(data[key]) for key in _SINGLE_COMPONENTS})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "name": self.name,
            **{key: getattr(self, key).to_dict() for key in _SINGLE_COMPONENTS},
            "operators": [item.to_dict() for item in self.operators],
            "skills": [item.to_dict() for item in self.skills],
            "mode": self.mode, "knowledge": self.knowledge.to_dict() if self.knowledge else None,
            **({"governance": self.governance.to_dict()} if self.governance is not None else {}),
            **({"execution": self.execution.to_dict()} if self.execution is not None else {})}


@dataclass(frozen=True)
class BuildContext:
    llm: Any
    evaluator: Any
    store: AppendOnlyStore
    scope_context: ScopeContext
    loop_config: Any
    workdir: str | Path
    accounting_stamp: Any = None
    mode: str = "benchmark"
    invocation_scope: dict[str, Any] | None = None
    governance: Any = None
    execution: ExecutionConfig | None = None


class OperatorFailure(RuntimeError):
    """A failed proposal with known provider cost, suitable for settlement."""
    def __init__(self, cost: CostVec, detail: str, *, measured_cost_units=None):
        super().__init__(detail)
        self.cost = cost
        self.detail = detail
        self.measured_cost_units = measured_cost_units


class OperatorBudgetExhausted(OperatorFailure):
    """Stop proposing after settling this invocation's complete known cost."""



@dataclass(frozen=True)
class Proposal:
    candidate: Candidate
    artifact: str
    cost: CostVec = field(default_factory=CostVec)
    # None is the legacy unknown-coverage contract. Multi-unit accounting must
    # require explicit measurements rather than interpreting default zeros.
    measured_cost_units: tuple[str, ...] | None = None


@dataclass(frozen=True)
class OperatorRequest:
    task_desc: str
    candidate_id: str
    cycle: int
    parents: tuple[Proposal, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    admit: bool
    reason: str

    def __post_init__(self) -> None:
        if type(self.admit) is not bool or type(self.reason) is not str or not self.reason.strip():
            raise ValueError("decision requires a boolean admit and non-empty reason")


@dataclass(frozen=True)
class Selection:
    """An atomic operator and lineage decision, validated by the driver."""
    parents: list[str]
    operator: str


class Policy(Protocol):
    async def observe(self, state: Any, budget: Any) -> dict[str, Any]: ...
    async def ideate(self, context: dict[str, Any], parent: Any, k: int) -> list[Any]: ...
    async def select(self, frontier: Any, budget: Any) -> list[str] | Selection: ...
    async def absorb(self, evidence: EvidenceRecord) -> list[StateMutation]: ...


class Operator(Protocol):
    async def propose(self, request: OperatorRequest) -> Proposal: ...


class Domain(Protocol):
    evaluator_version: str
    evaluation_context: str
    def validate_request(self, request: EvalRequest) -> None: ...
    async def evaluate(self, proposal: Proposal, request: EvalRequest) -> EvalResult: ...


class Executor(Protocol):
    async def execute(self, proposal: Proposal, request: EvalRequest,
                      domain: Domain) -> EvidenceRecord: ...


class Admission(Protocol):
    def judge(self, evidence: EvidenceRecord,
              incumbent: EvidenceRecord | None) -> Decision: ...


class BudgetController(Protocol):
    def state(self) -> Any: ...
    def allocate(self, candidate: Candidate) -> EvalRequest: ...
    def should_continue(self, branch: str, evidence: EvidenceRecord) -> bool: ...
    def converged(self, frontier: Any) -> Any | None: ...


class Skill(Protocol):
    def apply(self, request: OperatorRequest) -> OperatorRequest: ...
