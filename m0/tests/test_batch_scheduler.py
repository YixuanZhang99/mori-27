"""Frozen-cohort execution, atomic accounting and serial canonical admission."""
import asyncio
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.ledger import BudgetError, BudgetLedger
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
STAMP = AccountingStamp("offline", "batch-v1", "tokens", "prices", "2026-10-26")


class CohortBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []
        self.budget_tokens = []

    async def execute(self, spec, candidate, workspace, request):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(candidate.id)
            self.budget_tokens.append(request.budget_token)
        try:
            await asyncio.sleep(0.08)
            index = IDS.index(candidate.id)
            cost = CostVec(tokens_in=index + 1, tokens_out=1)
            if candidate.id == "failed":
                return EvidenceRecord(candidate.id, EvalResult(
                    EvalStatus.FAILED_TO_RUN, cost=cost, text_feedback="failed"),
                    executor_status="failed_to_run", result_text="failed")
            wins, losses, score = ((2, 1, 0.1) if index == 0 else (1, 2, 0.99))
            return EvidenceRecord(candidate.id, EvalResult(
                EvalStatus.OK, {"dev/score": score,
                                "admission/flip_wins": wins,
                                "admission/flip_losses": losses},
                cost=cost, text_feedback="evaluated"),
                executor_status="scored", result_text="evaluated")
        finally:
            with self._lock:
                self.active -= 1


def candidates():
    return [Candidate(node, operator="improve") for node in IDS]


def intents(cost=10):
    return [AllocationIntent(f"intent-{node}", "batch-test", node, cost,
                             snapshot_ref="cohort-1", account="exploit")
            for node in IDS]


def flip_admission(candidate, evidence):
    if evidence.eval_result.status is EvalStatus.OK:
        admit = (evidence.eval_result.metrics["admission/flip_wins"]
                 > evidence.eval_result.metrics["admission/flip_losses"])
    else:
        admit = False
    operation = MutationOp.MERGE if admit else MutationOp.PRUNE
    return AdmissionDecision(admit, [StateMutation(
        operation, candidate.id, {}, "per-item flip-count adjudication")],
        "gate-not-rank")


def fixture(tmp_path, total=1000):
    store = AppendOnlyStore(tmp_path / "batch.jsonl")
    ledger = BudgetLedger(total, 0.05, 10, STAMP, store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    applier = StateApplier(frontier, memory, store)
    policy = BestFirstPolicy(ScopeContext("batch-run", "batch-task", "batch-domain"))
    backend = CohortBackend()
    pool = ExecutorPool(backend, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy, applier, store)
    return scheduler, pool, backend, ledger, frontier, memory, store


def test_frozen_cohort_quota_accounting_and_gate_not_rank(tmp_path):
    scheduler, pool, backend, ledger, frontier, memory, store = fixture(tmp_path)

    async def scenario():
        task = asyncio.create_task(scheduler.run(
            [ExecutorSpec() for _ in IDS], candidates(), None,
            [EvalRequest("dev", budget_token=999) for _ in IDS], intents(),
            flip_admission))
        for _ in range(500):
            if backend.max_active == 2:
                break
            await asyncio.sleep(0.005)
        else:
            raise AssertionError("cohort did not execute concurrently")
        with pytest.raises(RuntimeError, match="inactive"):
            scheduler.checkpoint_state()
        return await task

    results = asyncio.run(scenario())
    assert [result.candidate_id for result in results] == IDS
    assert backend.max_active == 2 and sorted(backend.calls) == sorted(IDS)
    assert backend.budget_tokens == [10, 10, 10]
    assert scheduler.last_admissions == {
        "low-score-win": True, "high-score-loss": False, "failed": False}
    assert scheduler.checkpoint_state()["open_reserves"] == []
    pool.close()
    assert ledger.spent["exploit"] == 9 and not ledger.reserves
    assert len(ledger.settled_intents) == 3
    assert frontier.nodes["low-score-win"].status == "merged"
    assert frontier.nodes["high-score-loss"].status == "pruned"
    assert frontier.nodes["failed"].status == "pruned"
    assert frontier.sample(3, "greedy") == ["low-score-win"]
    assert len(memory.entries) == 3
    admissions = [record["payload"] for record in store.read("batch_admission")]
    assert [record["candidate_id"] for record in admissions] == IDS
    assert len(list(store.read("batch_execution_settled"))) == 3
    assert len(list(store.read("batch_cycle_completed"))) == 1


def test_batch_budget_rejection_is_atomic_and_executes_nothing(tmp_path):
    scheduler, pool, backend, ledger, _, _, store = fixture(tmp_path, total=100)
    with pytest.raises(BudgetError, match="batch reservation rejected"):
        asyncio.run(scheduler.run(
            [ExecutorSpec() for _ in IDS], candidates(), None,
            [EvalRequest("dev") for _ in IDS], intents(cost=40), flip_admission))
    assert backend.calls == [] and not ledger.reserves
    assert set(ledger.spent.values()) == {0.0}
    rejected = list(store.read("batch_budget_rejected"))
    assert len(rejected) == 1
    assert len(rejected[0]["payload"]["released_intents"]) == 2
    assert scheduler.checkpoint_state()["open_reserves"] == []
    pool.close()


def test_admission_failure_preserves_all_real_costs_and_resets_checkpoint(tmp_path):
    scheduler, pool, backend, ledger, frontier, _, store = fixture(tmp_path)

    def broken_admission(candidate, evidence):
        if candidate.id == "high-score-loss":
            raise RuntimeError("admission store unavailable")
        return flip_admission(candidate, evidence)

    with pytest.raises(RuntimeError, match="admission store unavailable"):
        asyncio.run(scheduler.run(
            [ExecutorSpec() for _ in IDS], candidates(), None,
            [EvalRequest("dev") for _ in IDS], intents(), broken_admission))
    assert len(backend.calls) == 3 and ledger.spent["exploit"] == 9
    assert not ledger.reserves and len(ledger.settled_intents) == 3
    assert set(frontier.nodes) == {"low-score-win", "high-score-loss"}
    assert scheduler.checkpoint_state()["open_reserves"] == []
    assert list(store.read("batch_cycle_completed")) == []
    pool.close()


def test_non_ok_admission_is_refused_after_cost_settlement(tmp_path):
    scheduler, pool, backend, ledger, frontier, _, _ = fixture(tmp_path)

    def illegal(candidate, evidence):
        return AdmissionDecision(True, [StateMutation(
            MutationOp.MERGE, candidate.id, {}, "illegal admission")])

    with pytest.raises(ValueError, match="non-OK evidence"):
        asyncio.run(scheduler.run(
            [ExecutorSpec()], [Candidate("failed")], None, [EvalRequest("dev")],
            [intents()[2]], illegal))
    assert ledger.spent["exploit"] == 4 and not ledger.reserves
    assert frontier.nodes["failed"].status == "done"
    assert scheduler.checkpoint_state()["open_reserves"] == []
    pool.close()
