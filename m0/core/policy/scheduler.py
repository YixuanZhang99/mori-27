"""M1 scheduler (M0): greedy parent_sample + intent emit + R4 reissue +
stop-table lookup. No LLM, no network, no wall-clock, no statistics (T-*).
"""
from __future__ import annotations

from dataclasses import replace

from core.policy.types import AllocationIntent


def parent_sample(candidates: list[dict]) -> dict:
    """Greedy argmax over accepted candidates. Deterministic for a fixed snapshot."""
    if not candidates:
        raise ValueError("empty candidate pool")
    return max(candidates, key=lambda c: (c["score"], c["candidate_id"]))


def make_intent(policy_id: str, candidate_ref: str, requested: int,
                snapshot_ref: str, account: str = "explore",
                generation: int = 0) -> AllocationIntent:
    return AllocationIntent(
        intent_id=f"g{generation}-{candidate_ref}-{account}",
        policy_id=policy_id, candidate_ref=candidate_ref,
        requested=requested, snapshot_ref=snapshot_ref, account=account)


def reissue(intent: AllocationIntent) -> AllocationIntent:
    """R4 (2): same-lineage LOW-TIER reissue; ttl restarts at 1 block."""
    return replace(intent,
                   intent_id=intent.intent_id + f"-r{intent.reissue_count + 1}",
                   requested=max(1, intent.requested // 2),
                   reissue_of=intent.intent_id,
                   reissue_count=intent.reissue_count + 1,
                   ttl_blocks=1,
                   requested_amounts={
                       unit: max(1.0, amount / 2) if amount > 1 else amount
                       for unit, amount in intent.requested_amounts.items()})
