"""M2 types (M0 kernel subset). See 开发指南 M2 页 §1."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class OperatorSpec:
    op_id: str
    kind: Literal["draft", "improve", "debug", "crossover"]
    prompt_version: str                 # required; empty = registration refused
    representation: str = "full_rewrite"


@dataclass(frozen=True)
class CrossoverContract:
    """C7/O12: composition is legal only with all three safeguards."""
    signature_constraint: bool = True
    role_labels: tuple[str, str] = ("base", "donor")
    debug_fallback_required: bool = True

    def validate(self) -> None:
        if not self.signature_constraint or not self.debug_fallback_required:
            raise ValueError("crossover requires signature constraint and debug fallback")
        if len(self.role_labels) != 2 or len(set(self.role_labels)) != 2:
            raise ValueError("crossover requires two distinct parent role labels")


@dataclass
class VariationProposal:
    proposal_id: str
    parent_ids: list[str]               # replay requires this (RUBRIC C4)
    patch_text: str
    apply_result: Literal["ok", "retry_ok", "failed"] = "failed"
    apply_attempts: int = 0             # failures counted BEFORE retries (C4)
    similarity_records: list = field(default_factory=list)  # reserved for novelty gate
    crossover_meta: dict | None = None  # ordered multi-parent lineage + contract evidence


@dataclass
class FunnelRecord:
    operator: str
    generation: int
    proposed: int = 0
    applicable: int = 0
    runnable: int = 0
    admitted: int = 0
    cost: dict = field(default_factory=dict)

    def check(self) -> None:
        """T-漏斗: monotone non-increasing stages."""
        assert self.proposed >= self.applicable >= self.runnable >= self.admitted, (
            f"funnel not monotone: {self}")
