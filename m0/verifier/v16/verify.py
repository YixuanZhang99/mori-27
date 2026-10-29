#!/usr/bin/env python3
"""Verifier v16: v15 plus durable canonical batch finalization recovery."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import traceback
from dataclasses import asdict
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
STAMP = AccountingStamp("offline", "verifier-v16", "tokens", "prices", "2026-10-26")


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
    return [AllocationIntent(f"v16-{node}", "verifier-v16", node, 10,
                             snapshot_ref="v16-cohort", account="exploit")
            for node in IDS]


def flip_admission(candidate, evidence):
    admit = (evidence.eval_result.status is EvalStatus.OK
             and evidence.eval_result.metrics["admission/flip_wins"]
             > evidence.eval_result.metrics["admission/flip_losses"])
    return AdmissionDecision(admit, [StateMutation(
        MutationOp.MERGE if admit else MutationOp.PRUNE, candidate.id, {},
        "v16 recoverable flip-only admission")])


def fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyStore(root / "evidence.jsonl")
    ledger = BudgetLedger(1000, 0.05, 10, STAMP, store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("v16-run", "task", "domain"))
    backend = RecoveryBackend()
    pool = ExecutorPool(backend, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, backend, ledger, frontier, memory, store


def reopen(store, ledger):
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("v16-run", "task", "domain"))
    backend = RecoveryBackend()
    pool = ExecutorPool(backend, 1, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, backend, frontier, memory


def run(scheduler, admission=flip_admission, batch=None):
    return asyncio.run(scheduler.run(
        [ExecutorSpec() for _ in IDS], candidates(), None,
        [EvalRequest("dev") for _ in IDS], batch or intents(), admission))


def interrupt(scheduler):
    def broken(candidate, evidence):
        if candidate.id == "high-score-loss":
            raise RuntimeError("v16 admission unavailable")
        return flip_admission(candidate, evidence)
    try:
        run(scheduler, broken)
    except RuntimeError as exc:
        return "v16 admission unavailable" in str(exc)
    return False


def statuses(frontier):
    return [frontier.nodes[node].status for node in IDS]


def check_same_process(root):
    scheduler, pool, backend, ledger, frontier, memory, store = fixture(root)
    interrupted = interrupt(scheduler)
    before = scheduler.recovery_state()
    new_batch_refused = False
    try:
        run(scheduler)
    except RuntimeError as exc:
        new_batch_refused = "recover the previous cohort" in str(exc)
    results = asyncio.run(scheduler.resume(flip_admission))
    pool.close()
    additions = [record["payload"]["target"] for record in store.read("state_mutation")
                 if record["payload"]["op"] == "add_node"]
    passed = (interrupted and before["status"] == "ready"
              and before["pending_candidates"] == ["high-score-loss", "failed"]
              and new_batch_refused and len(backend.calls) == 3
              and ledger.spent["exploit"] == 9
              and [result.candidate_id for result in results] == IDS
              and statuses(frontier) == ["merged", "pruned", "pruned"]
              and len(memory.entries) == 3 and additions.count("low-score-win") == 1
              and len(list(store.read("batch_execution_settled"))) == 3
              and len(list(store.read("batch_cycle_completed"))) == 1
              and scheduler.recovery_state()["status"] == "completed")
    return passed, {"interrupted": interrupted, "before": before,
                    "new_batch_refused": new_batch_refused,
                    "backend_calls": backend.calls, "spent": ledger.spent["exploit"],
                    "result_order": [result.candidate_id for result in results],
                    "node_statuses": statuses(frontier),
                    "first_candidate_additions": additions.count("low-score-win"),
                    "completed_records": len(list(store.read("batch_cycle_completed")))}


def check_fresh_and_completed(root):
    scheduler, pool, _, ledger, _, _, store = fixture(root)
    interrupted = interrupt(scheduler)
    pool.close()
    resumed, new_pool, new_backend, frontier, memory = reopen(store, ledger)
    results = asyncio.run(resumed.resume(flip_admission))
    admissions = [record["payload"]["candidate_id"] for record in store.read("batch_admission")]
    before_completed_resume = list(store.read())
    completed_results = asyncio.run(resumed.resume(flip_admission))
    after_completed_resume = list(store.read())
    new_pool.close()
    passed = (interrupted and new_backend.calls == [] and ledger.spent["exploit"] == 9
              and [result.candidate_id for result in results] == IDS
              and statuses(frontier) == ["merged", "pruned", "pruned"]
              and len(memory.entries) == 3 and admissions == IDS
              and len(list(store.read("batch_execution_settled"))) == 3
              and len(list(store.read("batch_cycle_completed"))) == 1
              and [asdict(item) for item in completed_results]
              == [asdict(item) for item in results]
              and after_completed_resume == before_completed_resume)
    return passed, {"interrupted": interrupted, "fresh_backend_calls": new_backend.calls,
                    "spent": ledger.spent["exploit"], "admission_events": admissions,
                    "node_statuses": statuses(frontier), "memory_entries": len(memory.entries),
                    "completed_resume_appended_records":
                        len(after_completed_resume) - len(before_completed_resume),
                    "completed_evidence_identical":
                        [asdict(item) for item in completed_results]
                        == [asdict(item) for item in results]}


def check_refusals(root):
    scheduler, pool, _, _, _, _, store = fixture(root / "ambiguous")
    interrupted = interrupt(scheduler)
    cohort_id = scheduler.recovery_state()["cohort_id"]
    store.append("batch_decision", {
        "cohort_id": cohort_id, "candidate_id": "high-score-loss",
        "decision": {"admit": False, "reason": "v16 simulated interruption", "mutations": [{
            "op": "prune", "target": "high-score-loss", "fields": {},
            "rationale": "v16 recoverable flip-only admission"}]}})
    before = len(list(store.read("state_mutation")))
    ambiguous_state = scheduler.recovery_state()
    ambiguous_refused = False
    try:
        asyncio.run(scheduler.resume(flip_admission))
    except RuntimeError as exc:
        ambiguous_refused = "ambiguous" in str(exc)
    ambiguous_ok = (interrupted and ambiguous_state["status"] == "ambiguous"
                    and ambiguous_refused
                    and len(list(store.read("state_mutation"))) == before
                    and not list(store.read("batch_cycle_completed")))
    pool.close()

    incomplete, incomplete_pool, incomplete_backend, _, _, _, incomplete_store = \
        fixture(root / "incomplete")
    incomplete_store.append("batch_cycle_started", {
        "cohort_id": "incomplete", "candidate_ids": ["x"],
        "candidates": [asdict(Candidate("x"))]})
    incomplete_refused = False
    try:
        asyncio.run(incomplete.resume(flip_admission))
    except RuntimeError as exc:
        incomplete_refused = "execution_incomplete" in str(exc)
    incomplete_ok = (incomplete.recovery_state()["status"] == "execution_incomplete"
                     and incomplete_refused and incomplete_backend.calls == [])
    incomplete_pool.close()

    aborted, aborted_pool, aborted_backend, _, _, _, _ = fixture(root / "aborted")
    basket = intents()
    basket[0].requested_amounts = {"token": 1}
    aborted_refused = False
    try:
        run(aborted, batch=basket)
    except BudgetError as exc:
        aborted_refused = "cannot reserve a cost basket" in str(exc)
    aborted_ok = (aborted_refused and aborted.recovery_state()["status"] == "aborted"
                  and not aborted.recovery_state()["recovery_required"]
                  and aborted_backend.calls == [])
    aborted_pool.close()
    return ambiguous_ok and incomplete_ok and aborted_ok, {
        "ambiguous_state": ambiguous_state, "ambiguous_refused": ambiguous_refused,
        "ambiguous_mutations_added": len(list(store.read("state_mutation"))) - before,
        "incomplete_refused": incomplete_refused,
        "incomplete_backend_calls": incomplete_backend.calls,
        "pre_submission_refused": aborted_refused,
        "aborted_state": aborted.recovery_state()}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_batch_recovery.py", "tests/test_batch_scheduler.py",
                           "tests/test_batch_multicurrency.py", "tests/test_multi_currency.py",
                           "tests/test_executor_pool.py", "tests/test_executor_hitl.py",
                           "tests/test_state_mutation.py", "tests/test_loop_checkpoint.py",
                           "tests/test_loop_governed_state.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2500:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    versions = ("v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13",
                "v15", "v16")
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py" for version in versions]
    present = [command for command in commands if command in text]
    historical_excluded = "python3 verifier/v14/verify.py" not in text
    return len(present) == len(commands) and historical_excluded, {
        "commands_present": present, "historical_v14_excluded": historical_excluded,
        "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v15/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v15_complete"] = prior.returncode == 0
    values["v15_exit"] = prior.returncode
    if prior.returncode:
        values["v15_stderr"] = prior.stderr[-2500:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("same_process_resume_and_new_batch_guard", check_same_process),
                         ("fresh_state_rebuild_and_completed_noop", check_fresh_and_completed),
                         ("ambiguous_and_incomplete_refusal", check_refusals),
                         ("batch_recovery_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v16/verify.py", "version": "v16",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v16.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
