"""Real bounded parallel M7 execution with serial governed finalization."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def real_fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "pool@example.invalid")
    git(repo, "config", "user.name", "Executor Pool Tests")
    (repo / "eval.py").write_text('''import fcntl, json, pathlib, sys, time
root = pathlib.Path(__file__).parent
state_path = pathlib.Path(sys.argv[1])
lock_path = state_path.with_suffix(".lock")
candidate = json.loads((root / "candidate.json").read_text())["id"]

def update(fn):
    with lock_path.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text())
        fn(state)
        state_path.write_text(json.dumps(state))
        fcntl.flock(stream, fcntl.LOCK_UN)

def entered(state):
    state["active"] += 1
    state["max_active"] = max(state["max_active"], state["active"])
    state["entered"].append(candidate)

def exited(state):
    state["active"] -= 1
    state["exited"].append(candidate)

update(entered)
try:
    time.sleep(0.4)
    if candidate == "crash":
        raise RuntimeError("candidate process crashed")
    if candidate != "missing":
        (root / "submission.csv").write_text("id,prediction\\n1,1\\n")
        (root / "metrics.json").write_text(json.dumps({"dev/score": 0.5}))
finally:
    update(exited)
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    shared = tmp_path / "shared"
    shared.mkdir()
    state_path = shared / "state.json"
    state_path.write_text(json.dumps(
        {"active": 0, "max_active": 0, "entered": [], "exited": []}))
    contract = EvalContract(
        metric_direction="maximize",
        eval_cmd=f"{sys.executable} {{cwd}}/eval.py {{data_dir}}/state.json",
        fidelity_levels=(FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        required_outputs=("submission.csv",), protected_paths=("eval.py",))
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")

    def builder(candidate, root):
        (root / "candidate.json").write_text(json.dumps({"id": candidate.id}))

    backend = GitWorktreeExecutor(contract, builder, store, data_dir=shared)
    workspace = GitWorktree(repo, tmp_path / "worktrees")
    return backend, workspace, store, state_path


def test_real_parallel_quota_failure_isolation_and_serial_absorb(tmp_path):
    backend, workspace, store, state_path = real_fixture(tmp_path)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    applier = StateApplier(frontier, memory, store)
    policy = BestFirstPolicy(ScopeContext("pool-run", "pool-task", "pool-domain"))
    candidates = [Candidate(node, operator="improve")
                  for node in ("ok-1", "crash", "ok-2", "missing")]
    specs = [ExecutorSpec() for _ in candidates]
    requests = [EvalRequest("dev", time_limit=5, seed_set=[7]) for _ in candidates]
    callback_order = []

    async def scenario():
        pool = ExecutorPool(backend, max_inflight=2, evidence_store=store)

        async def absorb(candidate, evidence):
            callback_order.append(candidate.id)
            assert pool.inflight_state["finalizing"] == 1
            applier.apply(StateMutation(
                MutationOp.ADD_NODE, candidate.id,
                {"candidate": candidate, "evidence": evidence}, "add pool candidate"))
            for mutation in await policy.absorb(evidence):
                await applier.apply_async(mutation)

        task = asyncio.create_task(pool.run_many(
            specs, candidates, workspace, requests, on_result=absorb))
        for _ in range(500):
            if len(pool.inflight_state["running"]) == 2:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("two real candidates never ran concurrently")
        state = pool.inflight_state
        assert len(state["running"]) == 2 and len(state["queued"]) == 2
        with pytest.raises(RuntimeError, match="checkpoint requires"):
            pool.checkpoint_state()
        results = await task
        assert pool.checkpoint_state()["inflight_executor"] == []
        pool.close()
        return results

    results = asyncio.run(scenario())
    assert [evidence.candidate_id for evidence in results] == [
        "ok-1", "crash", "ok-2", "missing"]
    assert callback_order == [candidate.id for candidate in candidates]
    assert [evidence.eval_result.status for evidence in results] == [
        EvalStatus.OK, EvalStatus.FAILED_TO_RUN, EvalStatus.OK, EvalStatus.INVALID]
    assert "candidate process crashed" in results[1].result_text
    activity = json.loads(state_path.read_text())
    assert activity["active"] == 0 and activity["max_active"] == 2
    assert sorted(activity["entered"]) == sorted(activity["exited"])
    assert len(frontier.nodes) == 4 and len(memory.entries) == 4
    assert set(frontier.sample(4, "greedy")) == {"ok-1", "ok-2"}
    levels = {entry_id: entry.level for entry_id, entry in memory.entries.items()}
    assert sorted(levels.values()) == ["L1", "L1", "L2", "L2"]
    assert len(list(store.read("executor_evidence"))) == 4
    assert len(list(store.read("executor_pool_absorbed"))) == 4
    assert len(list(store.read("state_mutation"))) == 14


def test_duplicate_batch_is_refused_and_backend_exception_returns_one_evidence(tmp_path):
    class BrokenBackend:
        async def execute(self, spec, candidate, workspace, request):
            raise RuntimeError("backend contract broke")

    store = AppendOnlyStore(tmp_path / "broken.jsonl")
    pool = ExecutorPool(BrokenBackend(), 2, store)
    candidate = Candidate("broken")
    request = EvalRequest("dev")
    with pytest.raises(ValueError, match="duplicate"):
        asyncio.run(pool.run_many([ExecutorSpec(), ExecutorSpec()],
                                  [candidate, candidate], None, [request, request]))
    first = asyncio.run(pool.run(ExecutorSpec(), candidate, None, request))
    second = asyncio.run(pool.run(ExecutorSpec(), candidate, None, request))
    assert first.executor_status == second.executor_status == "failed_to_run"
    assert (first.attempt, second.attempt) == (1, 2)
    assert "backend contract broke" in first.result_text
    assert len(list(store.read("executor_pool_finished"))) == 2
    assert len(list(store.read("executor_pool_failure"))) == 2
    assert pool.checkpoint_state()["queued"] == []
    pool.close()


def test_finalization_failure_is_not_relabelled_as_execution_failure(tmp_path):
    class SuccessfulBackend:
        async def execute(self, spec, candidate, workspace, request):
            return EvidenceRecord(candidate.id, EvalResult(EvalStatus.OK, {"dev/score": 1}))

    async def reject(candidate, evidence):
        raise RuntimeError("admission mutation rejected")

    pool = ExecutorPool(SuccessfulBackend(), 1)
    with pytest.raises(RuntimeError, match="admission mutation rejected"):
        asyncio.run(pool.run_many([ExecutorSpec()], [Candidate("c1")], None,
                                  [EvalRequest("dev")], on_result=reject))
    assert pool.checkpoint_state()["finalizing"] == 0
    pool.close()
