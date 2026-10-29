"""M1 types (M0 kernel subset). See 开发指南 M1 页 §1 + R4 裁决."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


class MutationOp(str, Enum):
    ADD_NODE = "add_node"
    UPDATE_NODE = "update_node"
    PRUNE = "prune"
    MERGE = "merge"
    WRITE_MEMORY = "write_memory"
    PROMOTE_MEMORY = "promote_memory"


@dataclass(frozen=True)
class StateMutation:
    op: MutationOp
    target: str
    fields: dict = field(default_factory=dict)
    rationale: str = ""


@dataclass
class AllocationIntent:
    intent_id: str
    policy_id: str
    candidate_ref: str
    requested: int
    ttl_blocks: int = 1
    snapshot_ref: str = ""
    account: str = "explore"          # CostAccountKind; control for baseline
    reissue_of: Optional[str] = None  # R4: same-lineage reissue, ttl resets
    reissue_count: int = 0            # R4: hard cap 2
    # N1 extension: when non-empty this is the complete per-unit reservation.
    # The legacy scalar remains the M0 token path; the two never mix silently.
    requested_amounts: dict[str, float] = field(default_factory=dict)


@dataclass
class IntentReceipt:
    intent_id: str
    verdict: Literal["granted", "reduced", "rejected_budget",
                     "rejected_conflict", "rejected_invalid"]
    granted: int = 0
    reason: str = ""
    granted_amounts: dict[str, float] = field(default_factory=dict)
