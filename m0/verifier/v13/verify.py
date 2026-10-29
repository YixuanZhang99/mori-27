#!/usr/bin/env python3
"""Verifier v13: v12 plus frozen-cohort scheduling and accounting."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

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
STAMP = AccountingStamp("offline", "verifier-v13", "tokens", "prices", "2026-10-26")


class CohortBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []
        self.finished = []
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
                    EvalStatus.FAILED_TO_RUN, cost=cost, text_feedback="v13 failure"),
                    executor_status="failed_to_run", result_text="v13 failure")
            wins, losses, score = ((2, 1, 0.1) if index == 0 else (1, 2, 0.99))
            return EvidenceRecord(candidate.id, EvalResult(
                EvalStatus.OK, {"dev/score": score,
                                "admission/flip_wins": wins,
                                "admission/flip_losses": losses}, cost=cost),
                executor_status="scored")
        finally:
            with self._lock:
                self.active -= 1
                self.finished.append(candidate.id)


def candidates():
    return [Candidate(node, operator="improve") for node in IDS]


def intents(cost=10):
    return [AllocationIntent(f"intent-{node}", "verifier-v13", node, cost,
                             snapshot_ref="frozen-cohort", account="exploit")
            for node in IDS]


def flip_admission(candidate, evidence):
    if evidence.eval_result.status is EvalStatus.OK:
        admit = (evidence.eval_result.metrics["admission/flip_wins"]
                 > evidence.eval_result.metrics["admission/flip_losses"])
    else:
        admit = False
    operation = MutationOp.MERGE if admit else MutationOp.PRUNE
    return AdmissionDecision(admit, [StateMutation(
        operation, candidate.id, {}, "v13 per-item flip adjudication")], "gate-not-rank")


def fixture(root, total=1000):
    root.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyStore(root / "evidence.jsonl")
    ledger = BudgetLedger(total, 0.05, 10, STAMP, store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    applier = StateApplier(frontier, memory, store)
    policy = BestFirstPolicy(ScopeContext("v13-run", "v13-task", "v13-domain"))
    backend = CohortBackend()
    pool = ExecutorPool(backend, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy, applier, store)
    return scheduler, pool, backend, ledger, frontier, memory, store


def run_batch(scheduler, admission=flip_admission, cost=10):
    return asyncio.run(scheduler.run(
        [ExecutorSpec() for _ in IDS], candidates(), None,
        [EvalRequest("dev", budget_token=999) for _ in IDS], intents(cost), admission))


def check_frozen(root):
    scheduler, pool, backend, ledger, frontier, memory, store = fixture(root)
    admission_trace = []

    def observed_admission(candidate, evidence):
        admission_trace.append({
            "candidate_id": candidate.id,
            "finished": sorted(backend.finished),
            "settled": len(ledger.settled_intents),
            "nodes_before_decision": sorted(frontier.nodes),
            "pool_finalizing": pool.inflight_state["finalizing"]})
        return flip_admission(candidate, evidence)

    async def scenario():
        task = asyncio.create_task(scheduler.run(
            [ExecutorSpec() for _ in IDS], candidates(), None,
            [EvalRequest("dev", budget_token=999) for _ in IDS], intents(),
            observed_admission))
        for _ in range(500):
            if backend.max_active == 2:
                break
            await asyncio.sleep(0.005)
        else:
            raise AssertionError("v13 cohort did not reach max_inflight=2")
        active_refused = False
        try:
            scheduler.checkpoint_state()
        except RuntimeError:
            active_refused = True
        results = await task
        return results, active_refused

    results, active_refused = asyncio.run(scenario())
    quiescent = scheduler.checkpoint_state()
    pool.close()
    expected_admissions = {"low-score-win": True, "high-score-loss": False,
                           "failed": False}
    statuses = {node: frontier.nodes[node].status for node in IDS}
    admissions = [record["payload"] for record in store.read("batch_admission")]
    all_results_finished = all(item["finished"] == sorted(IDS) and item["settled"] == 3
                               for item in admission_trace)
    serial_nodes = [item["nodes_before_decision"] for item in admission_trace]
    passed = (active_refused and backend.max_active == 2
              and sorted(backend.calls) == sorted(IDS)
              and backend.budget_tokens == [10, 10, 10]
              and [result.candidate_id for result in results] == IDS
              and scheduler.last_admissions == expected_admissions
              and statuses == {"low-score-win": "merged", "high-score-loss": "pruned",
                               "failed": "pruned"}
              and frontier.sample(3, "greedy") == ["low-score-win"]
              and len(memory.entries) == 3 and ledger.spent["exploit"] == 9
              and len(ledger.settled_intents) == 3 and not ledger.reserves
              and all_results_finished
              and serial_nodes == [["low-score-win"],
                                   ["high-score-loss", "low-score-win"], sorted(IDS)]
              and all(item["pool_finalizing"] == 0 for item in admission_trace)
              and [item["candidate_id"] for item in admissions] == IDS
              and len(list(store.read("batch_execution_settled"))) == 3
              and len(list(store.read("batch_cycle_completed"))) == 1
              and quiescent["open_reserves"] == [])
    return passed, {"max_active": backend.max_active,
                    "request_budget_tokens": backend.budget_tokens,
                    "result_order": [result.candidate_id for result in results],
                    "admissions": scheduler.last_admissions, "node_statuses": statuses,
                    "actual_exploit_spent": ledger.spent["exploit"],
                    "admission_trace": admission_trace,
                    "active_checkpoint_refused": active_refused,
                    "quiescent_checkpoint": quiescent}


def check_atomic_budget(root):
    scheduler, pool, backend, ledger, _, _, store = fixture(root, total=100)
    refused = False
    try:
        run_batch(scheduler, cost=40)
    except BudgetError as exc:
        refused = "batch reservation rejected" in str(exc)
    rejected = list(store.read("batch_budget_rejected"))
    checkpoint = scheduler.checkpoint_state()
    pool.close()
    passed = (refused and backend.calls == [] and not ledger.reserves
              and set(ledger.spent.values()) == {0.0} and len(rejected) == 1
              and len(rejected[0]["payload"]["released_intents"]) == 2
              and not list(store.read("batch_execution_settled"))
              and checkpoint["open_reserves"] == [])
    return passed, {"budget_error_raised": refused, "backend_calls": backend.calls,
                    "spent": ledger.spent, "open_reserves": list(ledger.reserves),
                    "rejection_payload": rejected[0]["payload"] if rejected else None}


def check_admission_failure(root):
    scheduler, pool, backend, ledger, frontier, _, store = fixture(root)

    def broken(candidate, evidence):
        if candidate.id == "high-score-loss":
            raise RuntimeError("v13 admission backend unavailable")
        return flip_admission(candidate, evidence)

    propagated = False
    try:
        run_batch(scheduler, broken)
    except RuntimeError as exc:
        propagated = "v13 admission backend unavailable" in str(exc)
    checkpoint = scheduler.checkpoint_state()
    pool.close()
    passed = (propagated and len(backend.calls) == 3 and ledger.spent["exploit"] == 9
              and len(ledger.settled_intents) == 3 and not ledger.reserves
              and set(frontier.nodes) == {"low-score-win", "high-score-loss"}
              and frontier.nodes["low-score-win"].status == "merged"
              and frontier.nodes["high-score-loss"].status == "done"
              and not list(store.read("batch_cycle_completed"))
              and len(list(store.read("batch_execution_settled"))) == 3
              and checkpoint["open_reserves"] == [])
    return passed, {"exception_propagated": propagated,
                    "actual_exploit_spent": ledger.spent["exploit"],
                    "settled_intents": len(ledger.settled_intents),
                    "materialized_nodes": sorted(frontier.nodes),
                    "cycle_completed_records": len(list(store.read("batch_cycle_completed"))),
                    "checkpoint_after_failure": checkpoint}


def check_non_ok_and_guards(root):
    scheduler, pool, _, ledger, frontier, _, _ = fixture(root / "non-ok")

    def illegal(candidate, evidence):
        return AdmissionDecision(True, [StateMutation(
            MutationOp.MERGE, candidate.id, {}, "illegal non-OK merge")])

    refused = False
    try:
        asyncio.run(scheduler.run(
            [ExecutorSpec()], [Candidate("failed")], None, [EvalRequest("dev")],
            [intents()[2]], illegal))
    except ValueError as exc:
        refused = "non-OK evidence" in str(exc)
    non_ok_status = frontier.nodes["failed"].status
    non_ok_cost = ledger.spent["exploit"]
    pool.close()

    held_scheduler, held_pool, _, held_ledger, _, _, _ = fixture(root / "open-reserve")
    held = AllocationIntent("held-intent", "verifier-v13", "held", 5,
                            snapshot_ref="held", account="exploit")
    held_ledger.quote_reserve(held)
    open_reserve_refused = False
    try:
        held_scheduler.checkpoint_state()
    except RuntimeError:
        open_reserve_refused = True
    held_ledger.release_for(held)
    released_checkpoint = held_scheduler.checkpoint_state()
    held_pool.close()
    passed = (refused and non_ok_status == "done" and non_ok_cost == 4
              and not ledger.reserves and open_reserve_refused
              and released_checkpoint["open_reserves"] == [])
    return passed, {"illegal_non_ok_admission_refused": refused,
                    "node_status_after_refusal": non_ok_status,
                    "settled_cost_after_refusal": non_ok_cost,
                    "open_reserve_checkpoint_refused": open_reserve_refused,
                    "released_checkpoint": released_checkpoint}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_batch_scheduler.py", "tests/test_executor_pool.py",
                           "tests/test_executor_hitl.py", "tests/test_state_mutation.py",
                           "tests/test_loop_governed_state.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2500:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    versions = ("v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13")
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py" for version in versions]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v12/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v12_complete"] = prior.returncode == 0
    values["v12_exit"] = prior.returncode
    if prior.returncode:
        values["v12_stderr"] = prior.stderr[-2500:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (
                ("frozen_cohort_execution_and_gate_not_rank", check_frozen),
                ("atomic_batch_budget_rejection", check_atomic_budget),
                ("admission_failure_preserves_real_costs", check_admission_failure),
                ("non_ok_admission_and_checkpoint_guards", check_non_ok_and_guards),
                ("batch_scheduler_contract_tests", check_tests),
                ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v13/verify.py", "version": "v13",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v13.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
