"""M8/M9 types (M0 kernel subset). See 开发指南 M8M9 页 §1."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class ItemResult:
    item_id: str
    verdict: Literal[0, 1]


@dataclass
class ReliabilityMeta:
    n_trials: int = 1
    ci95: Optional[tuple[float, float]] = None
    noise_floor: Optional[float] = None


@dataclass
class EvalResult:
    candidate_id: str
    head_sha: str
    items: list[ItemResult]
    combined_score: float = 0.0          # display-only; never a gate input
    public: dict = field(default_factory=dict)
    private: dict = field(default_factory=dict)
    text_feedback: str = ""              # S-4: required for reflective improve
    reliability: ReliabilityMeta = field(default_factory=ReliabilityMeta)
    evaluator_version: str = "det-v1"


@dataclass
class Verdict:
    kind: Literal["ACCEPT", "REJECT"]
    rationale_ref: Optional[str] = None


@dataclass
class Receipt:
    receipt_id: str
    verdict: Verdict
    head_sha: str
    evaluator_version: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class GateEvidenceRecord:
    candidate_id: str
    receipt_id: Optional[str]
    transition: str                     # evaluate | verdict | invalidate:* | rollback
    rule_id: str
    signals_snapshot: dict = field(default_factory=dict)
