"""Canonical batch settlement across independent physical cost units."""
import asyncio
import math
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.currency import MultiCurrencyBudgetLedger
from core.budget.ledger import BudgetError, BudgetLedger
from core.budget.types import AccountingStamp, CurrencyAccount, ExchangeRateTable
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

STAMP = AccountingStamp("offline", "batch-multi-v1", "tokens", "prices", "2026-10-26")
IDS = ["low-score-win", "high-score-loss"]


class MultiBackend:
    def __init__(self, malformed=False):
        self.malformed = malformed
        self.calls = []
        self.budget_tokens = []
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    async def execute(self, spec, candidate, workspace, request):
        with self._lock:
            self.calls.append(candidate.id)
            self.budget_tokens.append(request.budget_token)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.05)
            index = IDS.index(candidate.id)
            usd = 0.5 + index * 0.25
            if self.malformed and index == 1:
                usd = math.nan
            return EvidenceRecord(candidate.id, EvalResult(
                EvalStatus.OK, {"dev/score": 0.1 if index == 0 else 0.99,
                                "admission/flip_wins": 2 if index == 0 else 1,
                                "admission/flip_losses": 1 if index == 0 else 2},
                cost=CostVec(wall_seconds=2.5 + index, tokens_in=40 + index * 20,
                             tokens_out=20, gpu_hours=0.1 + index * 0.05,
                             usd=usd, eval_count=1, node_count=1)))
        finally:
            with self._lock:
                self.active -= 1


def candidates():
    return [Candidate(node, operator="improve") for node in IDS]


def intents(usd=2.0):
    result = []
    for index, node in enumerate(IDS):
        intent = AllocationIntent(f"multi-{index}", "batch-multi", node, 1,
                                  snapshot_ref="multi-cohort", account="exploit")
        intent.requested_amounts = {"token": 100, "usd": usd, "eval_count": 1,
                                    "node": 1, "wallclock": 10, "gpu_hours": 1}
        result.append(intent)
    return result


def flip_admission(candidate, evidence):
    admit = (evidence.eval_result.metrics["admission/flip_wins"]
             > evidence.eval_result.metrics["admission/flip_losses"])
    return AdmissionDecision(admit, [StateMutation(
        MutationOp.MERGE if admit else MutationOp.PRUNE, candidate.id, {},
        "flip-only multicurrency admission")])


def fixture(root, malformed=False):
    root.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyStore(root / "evidence.jsonl")
    accounts = {"token": CurrencyAccount("token", 10_000, floor=10),
                "usd": CurrencyAccount("usd", 100),
                "eval_count": CurrencyAccount("eval_count", 20),
                "node": CurrencyAccount("node", 20),
                "wallclock": CurrencyAccount("wallclock", 100),
                "gpu_hours": CurrencyAccount("gpu_hours", 10)}
    exchange = ExchangeRateTable("multi-fx-v1", {
        ("usd", "token"): 100, ("eval_count", "token"): 50,
        ("node", "token"): 10, ("wallclock", "token"): 2,
        ("gpu_hours", "token"): 200}, "token")
    ledger = MultiCurrencyBudgetLedger(accounts, 0.05, STAMP, store, exchange)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    applier = StateApplier(frontier, memory, store)
    policy = BestFirstPolicy(ScopeContext("multi-run", "multi-task", "multi-domain"))
    backend = MultiBackend(malformed)
    pool = ExecutorPool(backend, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy, applier, store)
    return scheduler, pool, backend, ledger, frontier, store


def run(scheduler, batch_intents=None):
    batch_intents = batch_intents or intents()
    return asyncio.run(scheduler.run(
        [ExecutorSpec() for _ in IDS], candidates(), None,
        [EvalRequest("dev", budget_token=999) for _ in IDS], batch_intents,
        flip_admission))


def test_multi_currency_costs_settle_per_unit_and_never_enter_admission(tmp_path):
    scheduler, pool, backend, ledger, frontier, store = fixture(tmp_path)
    results = run(scheduler)
    pool.close()
    assert [result.candidate_id for result in results] == IDS
    assert backend.max_active == 2 and backend.budget_tokens == [100, 100]
    assert ledger.spent["token"]["exploit"] == 140
    assert ledger.spent["usd"]["exploit"] == pytest.approx(1.25)
    assert ledger.spent["eval_count"]["exploit"] == 2
    assert ledger.spent["node"]["exploit"] == 2
    assert ledger.spent["wallclock"]["exploit"] == pytest.approx(6.0)
    assert ledger.spent["gpu_hours"]["exploit"] == pytest.approx(0.25)
    assert not ledger.reserves and len(ledger.settled_intents) == 2
    assert frontier.nodes["low-score-win"].status == "merged"
    assert frontier.nodes["high-score-loss"].status == "pruned"
    settled = [record["payload"] for record in store.read("batch_execution_settled")]
    assert [set(item["actual_costs"]) for item in settled] == [
        {"token", "usd", "eval_count", "node", "wallclock", "gpu_hours"}] * 2


def test_later_insufficient_unit_releases_entire_cohort_without_execution(tmp_path):
    scheduler, pool, backend, ledger, _, store = fixture(tmp_path)
    batch = intents()
    batch[1].requested_amounts["usd"] = 200
    with pytest.raises(BudgetError, match="batch reservation rejected"):
        run(scheduler, batch)
    pool.close()
    assert backend.calls == [] and not ledger.reserves
    assert all(set(accounts.values()) == {0.0} for accounts in ledger.spent.values())
    rejected = list(store.read("batch_budget_rejected"))
    assert len(rejected) == 1 and rejected[0]["payload"]["released_intents"] == ["multi-0"]
    assert not list(store.read("batch_execution_settled"))


def test_malformed_later_cost_vector_prevents_any_partial_settlement(tmp_path):
    scheduler, pool, backend, ledger, frontier, store = fixture(tmp_path, malformed=True)
    with pytest.raises(BudgetError, match="finite and non-negative"):
        run(scheduler)
    pool.close()
    assert len(backend.calls) == 2 and not ledger.reserves
    assert not ledger.settled_intents and not list(store.read("batch_execution_settled"))
    assert not list(store.read("batch_admission")) and not frontier.nodes
    assert all(set(accounts.values()) == {0.0} for accounts in ledger.spent.values())
    assert scheduler.checkpoint_state()["open_reserves"] == []


def test_single_currency_ledger_refuses_basket_instead_of_dropping_units(tmp_path):
    store = AppendOnlyStore(tmp_path / "single.jsonl")
    ledger = BudgetLedger(1000, 0.05, 10, STAMP, store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("single", "task", "domain"))
    backend = MultiBackend()
    pool = ExecutorPool(backend, 1, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    with pytest.raises(BudgetError, match="cannot reserve a cost basket"):
        asyncio.run(scheduler.run(
            [ExecutorSpec()], [candidates()[0]], None, [EvalRequest("dev")],
            [intents()[0]], flip_admission))
    pool.close()
    assert backend.calls == [] and not ledger.reserves
    assert set(ledger.spent.values()) == {0.0}
    assert scheduler.recovery_state()["status"] == "aborted"
