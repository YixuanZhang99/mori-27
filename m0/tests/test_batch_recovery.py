"""Durable settled-evidence recovery for canonical batch finalization."""
import asyncio
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.ledger import BudgetLedger
from core.budget.types import AccountingStamp
from core.eval.decision import AdmissionDecision
from core.executor import (Candidate, CostVec, EvalRequest, EvalResult, EvalStatus,
                           EvidenceRecord, ExecutorPool, ExecutorSpec)
from core.frontier import ResearchFrontier
from core.memory import ScopeContext, ScopedMemory
from core.orchestration import BatchScheduler
from core.policy import BestFirstPolicy, MutationOp, StateMutation
from core.policy.types import AllocationIntent
from core.state import StateApplier
from core.x1.store import AppendOnlyStore

IDS = ["low-score-win", "high-score-loss", "failed"]
STAMP = AccountingStamp("offline", "batch-recovery-v1", "tokens", "prices", "2026-10-26")


class RecoveryBackend:
    def __init__(self):
        self.calls = []

    async def execute(self, spec, candidate, workspace, request):
        self.calls.append(candidate.id)
        index = IDS.index(candidate.id)
        cost = CostVec(tokens_in=index + 1, tokens_out=1)
        if candidate.id == "failed":
            return EvidenceRecord(candidate.id, EvalResult(
                EvalStatus.FAILED_TO_RUN, cost=cost), executor_status="failed_to_run")
        wins, losses, score = ((2, 1, 0.1) if index == 0 else (1, 2, 0.99))
        return EvidenceRecord(candidate.id, EvalResult(
            EvalStatus.OK, {"dev/score": score, "admission/flip_wins": wins,
                            "admission/flip_losses": losses}, cost=cost))


def candidates():
    return [Candidate(node, operator="improve") for node in IDS]


def intents():
    return [AllocationIntent(f"recovery-{node}", "batch-recovery", node, 10,
                             snapshot_ref="recovery-cohort", account="exploit")
            for node in IDS]


def flip_admission(candidate, evidence):
    admit = (evidence.eval_result.status is EvalStatus.OK
             and evidence.eval_result.metrics["admission/flip_wins"]
             > evidence.eval_result.metrics["admission/flip_losses"])
    return AdmissionDecision(admit, [StateMutation(
        MutationOp.MERGE if admit else MutationOp.PRUNE, candidate.id, {},
        "recoverable flip-only admission")])


def fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyStore(root / "evidence.jsonl")
    ledger = BudgetLedger(1000, 0.05, 10, STAMP, store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("recovery-run", "task", "domain"))
    backend = RecoveryBackend()
    pool = ExecutorPool(backend, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, backend, ledger, frontier, memory, store


def reopen(store, ledger):
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("recovery-run", "task", "domain"))
    backend = RecoveryBackend()
    pool = ExecutorPool(backend, 1, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, backend, frontier, memory


def run(scheduler, admission=flip_admission):
    return asyncio.run(scheduler.run(
        [ExecutorSpec() for _ in IDS], candidates(), None,
        [EvalRequest("dev") for _ in IDS], intents(), admission))


def interrupt(scheduler):
    def broken(candidate, evidence):
        if candidate.id == "high-score-loss":
            raise RuntimeError("admission unavailable")
        return flip_admission(candidate, evidence)
    with pytest.raises(RuntimeError, match="admission unavailable"):
        run(scheduler, broken)


def test_same_process_resume_skips_finalized_and_preserves_costs(tmp_path):
    scheduler, pool, backend, ledger, frontier, memory, store = fixture(tmp_path)
    interrupt(scheduler)
    before = scheduler.recovery_state()
    with pytest.raises(RuntimeError, match="recover the previous cohort"):
        run(scheduler)
    results = asyncio.run(scheduler.resume(flip_admission))
    pool.close()
    assert before["status"] == "ready"
    assert before["pending_candidates"] == ["high-score-loss", "failed"]
    assert [result.candidate_id for result in results] == IDS
    assert len(backend.calls) == 3 and ledger.spent["exploit"] == 9
    assert len(list(store.read("batch_execution_settled"))) == 3
    assert len(list(store.read("batch_cycle_completed"))) == 1
    assert [frontier.nodes[node].status for node in IDS] == ["merged", "pruned", "pruned"]
    assert len(memory.entries) == 3
    additions = [record for record in store.read("state_mutation")
                 if record["payload"]["op"] == "add_node"]
    assert [record["payload"]["target"] for record in additions].count("low-score-win") == 1
    assert scheduler.recovery_state()["status"] == "completed"


def test_fresh_state_rebuilds_from_journal_without_reexecution_or_duplicate_events(tmp_path):
    scheduler, pool, backend, ledger, _, _, store = fixture(tmp_path)
    interrupt(scheduler)
    pool.close()
    resumed, new_pool, new_backend, frontier, memory = reopen(store, ledger)
    results = asyncio.run(resumed.resume(flip_admission))
    new_pool.close()
    assert [result.candidate_id for result in results] == IDS
    assert new_backend.calls == [] and ledger.spent["exploit"] == 9
    assert [frontier.nodes[node].status for node in IDS] == ["merged", "pruned", "pruned"]
    assert len(memory.entries) == 3
    admissions = [record["payload"]["candidate_id"] for record in store.read("batch_admission")]
    assert admissions == IDS
    assert len(list(store.read("batch_execution_settled"))) == 3
    assert len(list(store.read("batch_cycle_completed"))) == 1


def test_completed_resume_is_a_no_op_and_returns_journaled_evidence(tmp_path):
    scheduler, pool, _, _, frontier, _, store = fixture(tmp_path)
    original = run(scheduler)
    before = list(store.read())
    results = asyncio.run(scheduler.resume(flip_admission))
    pool.close()
    assert [asdict(result) for result in results] == [asdict(result) for result in original]
    assert list(store.read()) == before
    assert scheduler.last_admissions == {"low-score-win": True,
                                        "high-score-loss": False, "failed": False}
    assert frontier.nodes["low-score-win"].status == "merged"


def test_decision_without_admission_is_ambiguous_and_never_replayed(tmp_path):
    scheduler, pool, _, _, _, _, store = fixture(tmp_path)
    interrupt(scheduler)
    cohort_id = scheduler.recovery_state()["cohort_id"]
    store.append("batch_decision", {
        "cohort_id": cohort_id, "candidate_id": "high-score-loss",
        "decision": {"admit": False, "reason": "simulated crash", "mutations": [{
            "op": "prune", "target": "high-score-loss", "fields": {},
            "rationale": "recoverable flip-only admission"}]}})
    before = len(list(store.read("state_mutation")))
    assert scheduler.recovery_state()["status"] == "ambiguous"
    with pytest.raises(RuntimeError, match="ambiguous"):
        asyncio.run(scheduler.resume(flip_admission))
    pool.close()
    assert len(list(store.read("state_mutation"))) == before
    assert not list(store.read("batch_cycle_completed"))


def test_execution_incomplete_cannot_resume_or_execute(tmp_path):
    scheduler, pool, backend, _, _, _, store = fixture(tmp_path)
    store.append("batch_cycle_started", {
        "cohort_id": "incomplete", "candidate_ids": ["x"],
        "candidates": [asdict(Candidate("x"))]})
    assert scheduler.recovery_state()["status"] == "execution_incomplete"
    with pytest.raises(RuntimeError, match="execution_incomplete"):
        asyncio.run(scheduler.resume(flip_admission))
    pool.close()
    assert backend.calls == []
