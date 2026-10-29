#!/usr/bin/env python3
"""Verifier v14: v13 plus independent multi-currency batch accounting."""
from __future__ import annotations

import asyncio
import json
import math
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

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

STAMP = AccountingStamp("offline", "verifier-v14", "tokens", "prices", "2026-10-26")
IDS = ["low-score-win", "high-score-loss"]
UNITS = {"token", "usd", "eval_count", "node", "wallclock", "gpu_hours"}


class MultiBackend:
    def __init__(self, malformed=False):
        self.malformed = malformed
        self.calls = []
        self.budget_tokens = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

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


def intents():
    result = []
    for index, node in enumerate(IDS):
        intent = AllocationIntent(f"v14-multi-{index}", "verifier-v14", node, 1,
                                  snapshot_ref="v14-cohort", account="exploit")
        intent.requested_amounts = {"token": 100, "usd": 2, "eval_count": 1,
                                    "node": 1, "wallclock": 10, "gpu_hours": 1}
        result.append(intent)
    return result


def flip_admission(candidate, evidence):
    admit = (evidence.eval_result.metrics["admission/flip_wins"]
             > evidence.eval_result.metrics["admission/flip_losses"])
    return AdmissionDecision(admit, [StateMutation(
        MutationOp.MERGE if admit else MutationOp.PRUNE, candidate.id, {},
        "v14 flip-only admission")])


def multi_ledger(store):
    accounts = {"token": CurrencyAccount("token", 10_000, floor=10),
                "usd": CurrencyAccount("usd", 100),
                "eval_count": CurrencyAccount("eval_count", 20),
                "node": CurrencyAccount("node", 20),
                "wallclock": CurrencyAccount("wallclock", 100),
                "gpu_hours": CurrencyAccount("gpu_hours", 10)}
    exchange = ExchangeRateTable("v14-fx", {
        ("usd", "token"): 100, ("eval_count", "token"): 50,
        ("node", "token"): 10, ("wallclock", "token"): 2,
        ("gpu_hours", "token"): 200}, "token")
    return MultiCurrencyBudgetLedger(accounts, 0.05, STAMP, store, exchange)


def fixture(root, malformed=False):
    root.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyStore(root / "evidence.jsonl")
    ledger = multi_ledger(store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("v14-run", "v14-task", "v14-domain"))
    backend = MultiBackend(malformed)
    pool = ExecutorPool(backend, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, backend, ledger, frontier, store


def run(scheduler, batch=None):
    return asyncio.run(scheduler.run(
        [ExecutorSpec() for _ in IDS], candidates(), None,
        [EvalRequest("dev", budget_token=999) for _ in IDS], batch or intents(),
        flip_admission))


def zero_spent(ledger):
    return all(set(accounts.values()) == {0.0} for accounts in ledger.spent.values())


def check_per_unit(root):
    scheduler, pool, backend, ledger, frontier, store = fixture(root)
    results = run(scheduler)
    checkpoint = scheduler.checkpoint_state()
    pool.close()
    summary = ledger.account_summary()
    settled = [record["payload"] for record in store.read("batch_execution_settled")]
    expected = {"token": 140, "usd": 1.25, "eval_count": 2, "node": 2,
                "wallclock": 6.0, "gpu_hours": 0.25}
    observed = {unit: ledger.spent[unit]["exploit"] for unit in sorted(UNITS)}
    passed = ([result.candidate_id for result in results] == IDS
              and backend.max_active == 2 and backend.budget_tokens == [100, 100]
              and all(math.isclose(observed[unit], expected[unit]) for unit in UNITS)
              and math.isclose(summary["standard_spent"], 547)
              and summary["exchange_table_version"] == "v14-fx"
              and not ledger.reserves and len(ledger.settled_intents) == 2
              and frontier.nodes["low-score-win"].status == "merged"
              and frontier.nodes["high-score-loss"].status == "pruned"
              and len(settled) == 2
              and all(set(item["actual_costs"]) == UNITS for item in settled)
              and checkpoint["open_reserves"] == [])
    return passed, {"max_active": backend.max_active,
                    "request_token_budgets": backend.budget_tokens,
                    "expected_by_unit": expected, "observed_by_unit": observed,
                    "standard_spent": summary["standard_spent"],
                    "exchange_table_version": summary["exchange_table_version"],
                    "node_statuses": {node: frontier.nodes[node].status for node in IDS},
                    "settlement_units": [sorted(item["actual_costs"]) for item in settled]}


def check_atomic(root):
    scheduler, pool, backend, ledger, _, store = fixture(root / "multi")
    batch = intents()
    batch[1].requested_amounts["usd"] = 200
    multi_refused = False
    try:
        run(scheduler, batch)
    except BudgetError as exc:
        multi_refused = "batch reservation rejected" in str(exc)
    pool.close()
    rejected = list(store.read("batch_budget_rejected"))
    multi_ok = (multi_refused and backend.calls == [] and zero_spent(ledger)
                and not ledger.reserves and len(rejected) == 1
                and rejected[0]["payload"]["released_intents"] == ["v14-multi-0"]
                and not list(store.read("batch_execution_settled")))

    single_root = root / "single"
    single_root.mkdir(parents=True, exist_ok=True)
    single_store = AppendOnlyStore(single_root / "evidence.jsonl")
    single_ledger = BudgetLedger(1000, 0.05, 10, STAMP, single_store)
    frontier = ResearchFrontier(store=single_store)
    memory = ScopedMemory(single_store)
    policy = BestFirstPolicy(ScopeContext("v14-single", "task", "domain"))
    single_backend = MultiBackend()
    single_pool = ExecutorPool(single_backend, 1, single_store)
    single_scheduler = BatchScheduler(
        single_pool, single_ledger, policy,
        StateApplier(frontier, memory, single_store), single_store)
    legacy_refused = False
    try:
        asyncio.run(single_scheduler.run(
            [ExecutorSpec()], [candidates()[0]], None, [EvalRequest("dev")],
            [intents()[0]], flip_admission))
    except BudgetError as exc:
        legacy_refused = "cannot reserve a cost basket" in str(exc)
    single_pool.close()
    legacy_ok = (legacy_refused and single_backend.calls == []
                 and not single_ledger.reserves
                 and set(single_ledger.spent.values()) == {0.0})
    return multi_ok and legacy_ok, {
        "multi_insufficient_unit_refused": multi_refused,
        "multi_backend_calls": backend.calls, "multi_zero_spent": zero_spent(ledger),
        "multi_rejection": rejected[0]["payload"] if rejected else None,
        "legacy_basket_refused": legacy_refused,
        "legacy_backend_calls": single_backend.calls,
        "legacy_spent": single_ledger.spent}


def check_invalid(root):
    scheduler, pool, backend, ledger, frontier, store = fixture(root / "cohort", True)
    malformed_refused = False
    try:
        run(scheduler)
    except BudgetError as exc:
        malformed_refused = "finite and non-negative" in str(exc)
    pool.close()
    cohort_ok = (malformed_refused and len(backend.calls) == 2
                 and not ledger.reserves and not ledger.settled_intents
                 and zero_spent(ledger) and not frontier.nodes
                 and not list(store.read("batch_execution_settled"))
                 and not list(store.read("batch_admission")))

    direct_store = AppendOnlyStore(root / "direct.jsonl")
    direct = multi_ledger(direct_store)
    reservation_results = []
    for index, invalid in enumerate((math.nan, math.inf, -math.inf)):
        intent = intents()[0]
        intent.intent_id = f"invalid-{index}"
        intent.requested_amounts["usd"] = invalid
        receipt = direct.quote_reserve(intent)
        reservation_results.append(receipt.verdict == "rejected_invalid"
                                   and "finite" in receipt.reason)
    valid = intents()[0]
    direct.quote_reserve(valid)
    invalid_settle_refused = False
    costs = dict(valid.requested_amounts)
    costs["usd"] = math.nan
    try:
        direct.settle(valid, costs)
    except BudgetError as exc:
        invalid_settle_refused = "finite" in str(exc)
    reserve_preserved = valid.intent_id in direct.reserves
    direct.release_for(valid)
    direct_ok = (all(reservation_results) and invalid_settle_refused
                 and reserve_preserved and not direct.reserves and zero_spent(direct))
    return cohort_ok and direct_ok, {
        "malformed_cohort_refused": malformed_refused,
        "cohort_settled_intents": len(ledger.settled_intents),
        "cohort_materialized_nodes": sorted(frontier.nodes),
        "nonfinite_reservations_refused": reservation_results,
        "invalid_settlement_refused": invalid_settle_refused,
        "reserve_preserved_after_invalid_settlement": reserve_preserved,
        "direct_zero_spent_after_release": zero_spent(direct)}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_batch_multicurrency.py",
                           "tests/test_batch_scheduler.py", "tests/test_multi_currency.py",
                           "tests/test_executor_pool.py", "tests/test_executor_hitl.py",
                           "tests/test_state_mutation.py", "tests/test_loop_governed_state.py",
                           "tests/test_pareto_archive.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2500:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    versions = ("v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13", "v14")
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py" for version in versions]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v13/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v13_complete"] = prior.returncode == 0
    values["v13_exit"] = prior.returncode
    if prior.returncode:
        values["v13_stderr"] = prior.stderr[-2500:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("per_unit_settlement_and_gate_not_rank", check_per_unit),
                         ("atomic_cohort_and_legacy_refusal", check_atomic),
                         ("invalid_costs_cannot_partially_settle", check_invalid),
                         ("multicurrency_batch_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v14/verify.py", "version": "v14",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v14.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
