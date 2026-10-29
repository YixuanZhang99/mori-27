"""Rule-based M1 evidence absorption; no LLM or clock on this path."""
from __future__ import annotations

import hashlib

from core.executor.types import EvalStatus, EvidenceRecord
from core.memory.types import (MemoryEntry, Payload, Provenance, ScopeContext,
                               TimeMeta)
from core.policy.types import MutationOp, StateMutation


class BestFirstPolicy:
    """Minimal deterministic policy: greedy selection plus governed absorption."""

    def __init__(self, context: ScopeContext, source_run_id: str | None = None):
        self.context = context
        self.source_run_id = source_run_id or context.run_id

    async def select(self, frontier, budget_state=None) -> list[str]:
        return frontier.sample(1, "greedy")

    def _memory_id(self, evidence: EvidenceRecord) -> str:
        key = f"{self.source_run_id}\0{evidence.candidate_id}\0{evidence.attempt}"
        return "memory-" + hashlib.sha256(key.encode()).hexdigest()[:16]

    async def absorb(self, evidence: EvidenceRecord) -> list[StateMutation]:
        if not evidence.candidate_id or evidence.attempt < 1:
            raise ValueError("absorb requires candidate lineage and a positive attempt")
        result = evidence.eval_result
        raw_text = evidence.result_text or result.text_feedback or result.status.value
        memory_id = self._memory_id(evidence)
        refs = [f"evidence://{evidence.candidate_id}/{evidence.attempt}"]
        if evidence.branch_ref:
            refs.append(evidence.branch_ref)
        trusted = evidence.executor_status == "scored" and result.status is EvalStatus.OK
        entry = MemoryEntry(
            id=memory_id, payload=Payload("text", raw_text),
            provenance=Provenance(self.source_run_id, evidence.branch_ref, refs,
                                  "gated" if trusted else "ungated"),
            time=TimeMeta(created_at=float(evidence.attempt)),
            context=self.context, scope="task", level="L1")
        rationale = f"absorb {evidence.candidate_id} attempt {evidence.attempt}"
        mutations = [
            StateMutation(MutationOp.UPDATE_NODE, evidence.candidate_id, {
                "insight": evidence.insight,
                "result": {"result_text": evidence.result_text,
                           "text_feedback": result.text_feedback},
                "eval_status": result.status.value, "attempt": evidence.attempt,
                "code_ref": evidence.branch_ref}, rationale),
            StateMutation(MutationOp.WRITE_MEMORY, memory_id,
                          {"entry": entry, "at": float(evidence.attempt)}, rationale),
        ]
        if trusted:
            delta = ({"append_text": evidence.insight}
                     if evidence.insight and evidence.insight != raw_text
                     else {"utility": {"helpful_count": 1}})
            mutations.append(StateMutation(
                MutationOp.PROMOTE_MEMORY, memory_id,
                {"target_level": "L2", "delta": delta},
                "validated OK evidence; incrementally distill L1 to L2"))
        return mutations
