"""Pure data declarations for canonical evaluation identity and visibility."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class EvaluationBinding:
    candidate_id: str
    artifact_sha256: str
    request_sha256: str
    evaluator_version: str
    evaluation_context: str
    split_id: str
    fidelity: str
    seed_set: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PublicEvaluationData:
    data: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PrivateEvaluationData:
    metrics: dict[str, float] = field(default_factory=dict)
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ItemOutcome:
    item_id: str
    verdict: int | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    seed: int | None = None
    visibility: Literal["public", "private"] = "private"


@dataclass(frozen=True)
class EvaluationContract:
    binding: EvaluationBinding
    measured_cost_units: tuple[str, ...]
    token_accounting: Literal["split", "total_only"] = "split"
    public: PublicEvaluationData = field(default_factory=PublicEvaluationData)
    private: PrivateEvaluationData = field(default_factory=PrivateEvaluationData)
    items: tuple[ItemOutcome, ...] | None = None
    binding_source: Literal["producer", "invocation"] = "producer"
    visibility: Literal["full", "public"] = "full"


