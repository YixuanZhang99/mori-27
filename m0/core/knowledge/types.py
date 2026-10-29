"""M6 typed two-lane knowledge contract. Audit has no veto value by construction."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Lane = Literal["ground", "audit"]
Intent = Literal["related_work", "survey", "lookup", "explore", "repair"]
AuditTier = Literal["novel", "partial_overlap", "prior_art_exists"]


@dataclass(frozen=True)
class GroundedQuery:
    query_id: str
    intent: Intent
    text: str
    context: dict = field(default_factory=dict)
    depth_tier: Literal["shallow_2k", "deep_6k", "mid"] = "deep_6k"
    eval_mode: Literal["research", "benchmark"] = "research"

    def __post_init__(self):
        if not self.query_id or not self.text:
            raise ValueError("grounded query requires id and text")
        expected = "mid" if self.intent == "repair" else (
            "shallow_2k" if self.intent == "lookup" else "deep_6k")
        if self.depth_tier != expected:
            raise ValueError(f"{self.intent} requires depth_tier={expected}")


@dataclass
class KnowledgeDigest:
    digest_id: str
    query: GroundedQuery
    summary: str
    findings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: dict = field(default_factory=dict)
    lane: Lane = "ground"


@dataclass
class GapSignalCard:
    gap_id: str
    kind: Literal["convergent", "cross_link"]
    statement: str
    evidence: list[dict]
    non_obviousness_gate: dict
    constraints: list[str] = field(default_factory=list)
    failure_modes: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    ttl: Optional[float] = None

    def __post_init__(self):
        trace_ids = {e.get("trace_id") for e in self.evidence}
        if len(self.evidence) < 2 or len(trace_ids) < 2 or None in trace_ids:
            raise ValueError("gap card requires at least two independent trajectories")
        if any("path_excerpt" not in e or "paper_id" not in e for e in self.evidence):
            raise ValueError("gap evidence must contain path excerpts and paper ids")
        if not self.non_obviousness_gate.get("structural_novelty"):
            raise ValueError("non-obviousness gate is incomplete")


@dataclass
class AuditReliability:
    sampled_rate: float = 0.0
    false_novel_rate: Optional[float] = None
    false_kill_rate: Optional[float] = None
    n_reviewed: int = 0

    def usable(self) -> bool:
        return self.n_reviewed > 0 and self.sampled_rate > 0


@dataclass
class AuditVerdict:
    audit_id: str
    idea_id: str
    verdict: AuditTier
    audit_phase: Literal["add_precheck", "merge_review"]
    audit_query_trace: list[dict]
    backends_covered: list[str]
    reliability: AuditReliability
    fetch_refs: list[str]
    closest_paper_id: Optional[str] = None
    overlap_risk: str = ""
    lane: Lane = "audit"


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    content: str
    backend: str
    opened: bool = True
    truncation_boundary: Optional[str] = None


@dataclass
class FetchLedger:
    seq: int
    url: str
    content_hash: str
    timestamp: float
    lane: Lane
    truncation_boundary: Optional[str] = None
    backend: str = ""


@dataclass
class DualRateLedger:
    verdict_id: str
    idea_id: str
    verdict: AuditTier
    audit_query_trace: list[dict]
    fetch_refs: list[str]
    sampled_for_review: bool
    review_truth: Literal["true_novel", "true_overlap"]
    error_kind: Literal["false_novel", "false_kill", "correct", "isolation_violation"]
    reviewer: str
    review_date: float
