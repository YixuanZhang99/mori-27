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

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("assembly schema_version must be integer 1")
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssemblyConfig":
        required = {"schema_version", "name", "operators", *_SINGLE_COMPONENTS}
        allowed = required | {"skills", "mode", "knowledge"}
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
            knowledge=ComponentSpec.from_dict(data["knowledge"]) if data.get("knowledge") is not None else None,
            **{key: ComponentSpec.from_dict(data[key]) for key in _SINGLE_COMPONENTS})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "name": self.name,
            **{key: getattr(self, key).to_dict() for key in _SINGLE_COMPONENTS},
            "operators": [item.to_dict() for item in self.operators],
            "skills": [item.to_dict() for item in self.skills],
            "mode": self.mode, "knowledge": self.knowledge.to_dict() if self.knowledge else None}


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


@dataclass(frozen=True)
class Proposal:
    candidate: Candidate
    artifact: str
    cost: CostVec = field(default_factory=CostVec)


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


class Policy(Protocol):
    async def observe(self, state: Any, budget: Any) -> dict[str, Any]: ...
    async def ideate(self, context: dict[str, Any], parent: Any, k: int) -> list[Any]: ...
    async def select(self, frontier: Any, budget: Any) -> list[str]: ...
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
