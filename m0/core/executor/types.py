"""Canonical M7 execution boundary types from SPEC §1.

These are deliberately independent from the smaller M0 display EvalResult.  M7
uses EvalStatus to make execution failure data, rather than an exception.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from core.executor.evaluation_contract import EvaluationContract

NodeRef = str
ArtifactRef = str


@dataclass(frozen=True)
class Candidate:
    id: NodeRef
    parents: list[NodeRef] = field(default_factory=list)
    hypothesis: str | None = None
    operator: str = "draft"
    context_pack_ref: str | None = None
    created_cycle: int = 0

    def validate(self) -> None:
        if not self.id or len(self.parents) > 2 or len(set(self.parents)) != len(self.parents):
            raise ValueError("candidate requires an id and at most two distinct parents")
        if self.id in self.parents or self.created_cycle < 0:
            raise ValueError("invalid candidate lineage or creation cycle")


@dataclass(frozen=True)
class ExecutorSpec:
    role: str = "general"
    hypothesis_frozen: bool = True
    hypothesis: str | None = None
    context_projection: list[str] = field(default_factory=lambda: ["summary"])
    # Durable scheduler/executor correlation; never an admission input.
    execution_ref: str | None = None


class EvalStatus(str, Enum):
    OK = "ok"
    FAILED_TO_RUN = "failed_to_run"
    TIMEOUT = "timeout"
    INVALID = "invalid"


@dataclass(frozen=True)
class CostVec:
    wall_seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    gpu_hours: float = 0.0
    usd: float = 0.0
    eval_count: int = 0
    node_count: int = 0


@dataclass(frozen=True)
class EvalRequest:
    fidelity: str
    time_limit: int | None = None
    budget_token: int | None = None
    seed_set: list[int] | None = None
    resume_from: ArtifactRef | None = None
    split_id: str = "dev"

    def validate(self) -> None:
        if type(self.fidelity) is not str or not self.fidelity.strip():
            raise ValueError("fidelity is required")
        if type(self.split_id) is not str or not self.split_id.strip():
            raise ValueError("split_id is required")
        if self.time_limit is not None and (type(self.time_limit) is not int or self.time_limit <= 0):
            raise ValueError("time_limit must be positive")
        if self.budget_token is not None and (type(self.budget_token) is not int or self.budget_token < 0):
            raise ValueError("budget_token cannot be negative")
        if self.seed_set is not None and (type(self.seed_set) is not list
                or any(type(seed) is not int or seed < 0 for seed in self.seed_set)
                or len(set(self.seed_set)) != len(self.seed_set)):
            raise ValueError("seed_set must contain distinct nonnegative integers")
        if self.resume_from is not None and (type(self.resume_from) is not str or not self.resume_from.strip()):
            raise ValueError("resume_from must be a non-empty artifact reference")


@dataclass(frozen=True)
class EvalResult:
    status: EvalStatus
    metrics: dict[str, float] = field(default_factory=dict)
    cost: CostVec = field(default_factory=CostVec)
    fidelity: str = "dev"
    uncertainty: float | None = None
    text_feedback: str | None = None
    partial_curves_ref: str | None = None
    trajectory_ref: str | None = None
    artifacts_ref: ArtifactRef | None = None
    # Optional for old M0/M7 adapters; mandatory at the configured runtime boundary.
    contract: EvaluationContract | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    candidate_id: NodeRef
    eval_result: EvalResult
    branch_ref: ArtifactRef | None = None
    executor_status: Literal[
        "scored", "skipped", "failed_to_run", "timeout", "invalid"
    ] = "scored"
    attempt: int = 1
    insight: str | None = None
    result_text: str | None = None
