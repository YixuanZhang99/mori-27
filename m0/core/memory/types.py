"""M5 frozen memory types. All timestamps are caller-supplied logical values."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Any

PayloadKind = Literal["text", "structured", "executable", "genotype_ref"]
Scope = Literal["run", "task", "domain", "global"]
LifecycleState = Literal["candidate", "active", "demoted", "archived", "deleted"]
TRUST_ORDER = {"ungated": 0, "gated": 1, "verified": 2, "human": 3}


@dataclass
class Payload:
    kind: PayloadKind
    body: Any
    schema_id: Optional[str] = None

    def __post_init__(self):
        if self.kind == "structured" and not self.schema_id:
            raise ValueError("structured payload requires schema_id")


@dataclass
class UtilitySignals:
    q_value: Optional[float] = None
    helpful_count: int = 0
    harmful_count: int = 0
    contribution: Optional[float] = None
    hit_count: int = 0

    def scalar(self) -> float:
        signals = [self.helpful_count - self.harmful_count]
        if self.q_value is not None:
            signals.append(self.q_value)
        if self.contribution is not None:
            signals.append(self.contribution)
        return sum(signals) / len(signals)


@dataclass
class Provenance:
    source_run_id: str
    source_branch: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)
    trust_tier: Literal["verified", "gated", "ungated", "human"] = "ungated"

    def __post_init__(self):
        if not self.source_run_id:
            raise ValueError("memory provenance requires source_run_id")


@dataclass
class TimeMeta:
    created_at: float
    last_hit_at: Optional[float] = None
    ttl: Optional[float] = None
    superseded_by: Optional[str] = None


@dataclass(frozen=True)
class ScopeContext:
    run_id: str
    task_id: str
    domain_id: str


@dataclass
class MemoryEntry:
    id: str
    payload: Payload
    provenance: Provenance
    time: TimeMeta
    context: ScopeContext
    scope: Scope = "task"
    level: Literal["L1", "L2", "L3"] = "L2"
    state: LifecycleState = "candidate"
    utility: UtilitySignals = field(default_factory=UtilitySignals)


@dataclass(frozen=True)
class MemoryQuery:
    text: str
    context: ScopeContext
    trust_floor: Literal["verified", "gated", "ungated", "human"] = "ungated"
    include_negative: bool = True
    include_archived: bool = False


@dataclass(frozen=True)
class ScopeUpgradeEvidence:
    source_validated: bool
    demotion_path_ready: bool
    rollback_snapshot_ref: str
    cross_task_evidence_ref: str = ""
    human_confirmation: bool = False
