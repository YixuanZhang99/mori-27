#!/usr/bin/env python3
"""Verifier v12: v11 plus real bounded ExecutorPool behavior."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.executor import (Candidate, EvalRequest, EvalResult, EvalStatus, EvidenceRecord,
                           ExecutorPool, ExecutorSpec, GitWorktree, GitWorktreeExecutor)
from core.frontier import ResearchFrontier
from core.memory import ScopeContext, ScopedMemory
from core.policy import BestFirstPolicy, MutationOp, StateMutation
from core.state import StateApplier
from core.tasks.adapter import EvalContract, FidelityLevel
from core.x1.store import AppendOnlyStore


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def real_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "v12@example.invalid")
    git(repo, "config", "user.name", "Verifier v12")
    (repo / "eval.py").write_text('''import fcntl, json, pathlib, sys, time
root = pathlib.Path(__file__).parent
state_path = pathlib.Path(sys.argv[1])
candidate = json.loads((root / "candidate.json").read_text())["id"]

def update(kind):
    with state_path.with_suffix(".lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text())
        if kind == "enter":
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        else:
            state["active"] -= 1
        state[kind].append(candidate)
        state_path.write_text(json.dumps(state))
        fcntl.flock(stream, fcntl.LOCK_UN)

update("enter")
try:
    time.sleep(0.4)
    if candidate == "crash":
        raise RuntimeError("v12 candidate crash")
    if candidate != "missing":
        (root / "submission.csv").write_text("id,prediction\\n1,1\\n")
        (root / "metrics.json").write_text(json.dumps({"dev/score": 0.5}))
finally:
    update("exit")
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    shared = root / "shared"
    shared.mkdir()
    state_path = shared / "state.json"
    state_path.write_text(json.dumps(
        {"active": 0, "max_active": 0, "enter": [], "exit": []}))
    contract = EvalContract(
        "maximize", f"{sys.executable} {{cwd}}/eval.py {{data_dir}}/state.json",
        (FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        ("submission.csv",), ("eval.py",))
    store = AppendOnlyStore(root / "evidence.jsonl")

    def builder(candidate, path):
        (path / "candidate.json").write_text(json.dumps({"id": candidate.id}))

    return (GitWorktreeExecutor(contract, builder, store, data_dir=shared),
            GitWorktree(repo, root / "worktrees"), store, state_path)


def candidates():
    return [Candidate(node, operator="improve")
            for node in ("ok-1", "crash", "ok-2", "missing")]


def requests():
    return [EvalRequest("dev", time_limit=5, seed_set=[7]) for _ in range(4)]


async def wait_for_two(pool):
    for _ in range(500):
        if len(pool.inflight_state["running"]) == 2:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("real pool did not reach two concurrent executions")


def check_real(root):
    backend, workspace, store, state_path = real_fixture(root)
    cands = candidates()

    async def scenario():
        pool = ExecutorPool(backend, 2, store)
        task = asyncio.create_task(pool.run_many(
            [ExecutorSpec() for _ in cands], cands, workspace, requests()))
        await wait_for_two(pool)
        state = pool.inflight_state
        refused = False
        try:
            pool.checkpoint_state()
        except RuntimeError:
            refused = True
        results = await task
        quiescent = pool.checkpoint_state()
        pool.close()
        return state, refused, quiescent, results

    state, refused, quiescent, results = asyncio.run(scenario())
    activity = json.loads(state_path.read_text())
    statuses = [evidence.eval_result.status.value for evidence in results]
    all_records = list(store.read())
    passed = (len(state["queued"]) == 2 and len(state["running"]) == 2
              and not set(state["queued"]).intersection(state["running"])
              and set(state["queued"] + state["running"])
              == {candidate.id for candidate in cands}
              and refused and quiescent["inflight_executor"] == []
              and [evidence.candidate_id for evidence in results]
              == [candidate.id for candidate in cands]
              and statuses == ["ok", "failed_to_run", "ok", "invalid"]
              and activity["active"] == 0 and activity["max_active"] == 2
              and sorted(activity["enter"]) == sorted(activity["exit"])
              and len(all_records) > 0 and len(list(store.read("executor_evidence"))) == 4
              and len(list(store.read("executor_pool_finished"))) == 4
              and not list(workspace.run_root.iterdir()))
    return passed, {"max_observed_active": activity["max_active"],
                    "queued_at_probe": state["queued"], "running_at_probe": state["running"],
                    "statuses": statuses, "checkpoint_refused_while_active": refused,
                    "evidence_records": len(list(store.read("executor_evidence"))),
                    "jsonl_records_parsed": len(all_records),
                    "worktrees_remaining": len(list(workspace.run_root.iterdir())),
                    "security_sandbox_claimed": False}


def check_serial(root):
    backend, workspace, store, _ = real_fixture(root)
    cands = candidates()
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    applier = StateApplier(frontier, memory, store)
    policy = BestFirstPolicy(ScopeContext("v12-run", "v12-task", "v12-domain"))
    order = []

    async def scenario():
        pool = ExecutorPool(backend, 2, store)

        async def absorb(candidate, evidence):
            order.append(candidate.id)
            if pool.inflight_state["finalizing"] != 1:
                raise AssertionError("result finalization was not serialized")
            applier.apply(StateMutation(
                MutationOp.ADD_NODE, candidate.id,
                {"candidate": candidate, "evidence": evidence}, "add v12 candidate"))
            for mutation in await policy.absorb(evidence):
                await applier.apply_async(mutation)

        results = await pool.run_many([ExecutorSpec() for _ in cands], cands,
                                      workspace, requests(), on_result=absorb)
        checkpoint = pool.checkpoint_state()
        pool.close()
        return results, checkpoint

    results, checkpoint = asyncio.run(scenario())
    eligible = set(frontier.sample(4, "greedy"))
    levels = sorted(entry.level for entry in memory.entries.values())
    passed = (order == [candidate.id for candidate in cands]
              and len(results) == 4 and eligible == {"ok-1", "ok-2"}
              and len(frontier.nodes) == 4 and len(memory.entries) == 4
              and levels == ["L1", "L1", "L2", "L2"]
              and len(list(store.read("state_mutation"))) == 14
              and len(list(store.read("executor_pool_absorbed"))) == 4
              and checkpoint["finalizing"] == 0)
    return passed, {"callback_order": order, "eligible": sorted(eligible),
                    "memory_levels": levels,
                    "state_mutations": len(list(store.read("state_mutation"))),
                    "quiescent_checkpoint": checkpoint}


def check_robustness(root):
    root.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyStore(root / "robust.jsonl")

    class Broken:
        async def execute(self, spec, candidate, workspace, request):
            raise RuntimeError("v12 backend exception")

    pool = ExecutorPool(Broken(), 2, store)
    duplicate_refused = False
    try:
        asyncio.run(pool.run_many([ExecutorSpec(), ExecutorSpec()],
                                  [Candidate("same"), Candidate("same")], None,
                                  [EvalRequest("dev"), EvalRequest("dev")]))
    except ValueError:
        duplicate_refused = True
    first = asyncio.run(pool.run(ExecutorSpec(), Candidate("broken"), None, EvalRequest("dev")))
    second = asyncio.run(pool.run(ExecutorSpec(), Candidate("broken"), None, EvalRequest("dev")))
    pool.close()

    class Successful:
        async def execute(self, spec, candidate, workspace, request):
            return EvidenceRecord(candidate.id, EvalResult(EvalStatus.OK, {"dev/score": 1}))

    async def reject(candidate, evidence):
        raise RuntimeError("v12 finalization rejection")

    final_pool = ExecutorPool(Successful(), 1)
    finalization_propagated = False
    try:
        asyncio.run(final_pool.run_many([ExecutorSpec()], [Candidate("c1")], None,
                                        [EvalRequest("dev")], on_result=reject))
    except RuntimeError as exc:
        finalization_propagated = "finalization rejection" in str(exc)
    final_state = final_pool.checkpoint_state()
    final_pool.close()
    passed = (duplicate_refused and first.executor_status == second.executor_status
              == "failed_to_run" and (first.attempt, second.attempt) == (1, 2)
              and len(list(store.read("executor_pool_failure"))) == 2
              and len(list(store.read("executor_pool_finished"))) == 2
              and finalization_propagated and final_state["finalizing"] == 0)
    return passed, {"duplicate_refused": duplicate_refused,
                    "attempts": [first.attempt, second.attempt],
                    "backend_failure_records": len(list(store.read("executor_pool_failure"))),
                    "finalization_propagated": finalization_propagated,
                    "finalizing_after_failure": final_state["finalizing"]}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_executor_pool.py", "tests/test_executor_hitl.py",
                           "tests/test_state_mutation.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2000:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    versions = ("v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12")
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py" for version in versions]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v11/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v11_complete"] = prior.returncode == 0
    values["v11_exit"] = prior.returncode
    if prior.returncode:
        values["v11_stderr"] = prior.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("real_parallel_quota_and_failure_isolation", check_real),
                         ("serial_absorb_and_checkpoint_guard", check_serial),
                         ("pool_robustness", check_robustness),
                         ("executor_pool_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v12/verify.py", "version": "v12",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v12.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
