"""v17 owner-crash recovery using real detached processes and git worktrees."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import (Candidate, EvalRequest, EvalStatus, ExecutorSpec,
                           GitWorktree, GitWorktreeExecutor)
from core.executor.process import ProcessJournal, process_alive, start_ticks
from core.tasks.adapter import EvalContract, FidelityLevel
from core.x1.store import AppendOnlyStore

PROJECT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def make_repo(root: Path, delay: float) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "user.name", "Offline Recovery Tests")
    (repo / "solution.py").write_text("VALUE = 0\n")
    (repo / "eval.py").write_text(f'''import json, pathlib, time
root = pathlib.Path(__file__).parent
time.sleep({delay})
(root / "submission.csv").write_text("id,prediction\\n1,1\\n")
(root / "metrics.json").write_text(json.dumps({{"dev/score": 0.75}}))
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    return repo


def contract(repo: Path) -> EvalContract:
    return EvalContract(
        metric_direction="maximize", eval_cmd=f"{sys.executable} {{cwd}}/eval.py",
        fidelity_levels=(FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        required_outputs=("submission.csv",), protected_paths=("eval.py",))


def builder(candidate, root):
    (root / "candidate.json").write_text(json.dumps({"id": candidate.id}))
    (root / "solution.py").write_text(f"VALUE = {candidate.created_cycle}\n")


def forbidden_builder(candidate, root):
    raise AssertionError("recovery must not rebuild or re-execute a candidate")


def start_owner(repo: Path, store_path: Path, worktrees: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["AR_TEST_SECRET"] = "must-not-be-persisted"
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner",
         str(repo), str(store_path), str(worktrees)],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for_started(store: AppendOnlyStore) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        records = list(store.read("executor_process_started"))
        if records:
            return records[0]["payload"]
        time.sleep(0.02)
    raise AssertionError("owner did not launch the detached evaluation")


def recover_until_result(executor, workspace, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        evidence = executor.recover_inflight(workspace)
        if evidence:
            return evidence
        time.sleep(0.05)
    raise AssertionError("detached evaluation was not recovered")


def test_real_owner_crash_pending_then_recovers_exactly_once(tmp_path):
    repo = make_repo(tmp_path, 2.0)
    store_path = tmp_path / "evidence.jsonl"
    worktrees = tmp_path / "worktrees"
    owner = start_owner(repo, store_path, worktrees)
    store = AppendOnlyStore(store_path)
    record = wait_for_started(store)
    owner.kill()
    owner.wait(timeout=5)

    restored = GitWorktreeExecutor(contract(repo), forbidden_builder, store)
    workspace = GitWorktree(repo, worktrees)
    assert restored.recover_inflight(workspace) == []
    assert list(store.read("executor_evidence")) == []
    evidence = recover_until_result(restored, workspace)[0]
    assert evidence.eval_result.status is EvalStatus.OK
    assert evidence.executor_status == "scored"
    assert evidence.eval_result.metrics == {"dev/score": 0.75}
    assert evidence.attempt == 1
    assert git(repo, "show", f"{evidence.branch_ref}:submission.csv").startswith("id,prediction")
    assert not list(worktrees.iterdir())
    assert restored.recover_inflight(workspace) == []
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("executor_process_finished"))) == 1
    assert len(list(store.read("executor_evidence"))) == 1
    finished = list(store.read("executor_process_finished"))[0]["payload"]
    assert finished["recovered"] is True
    persisted = store_path.read_text() + Path(record["spec_path"]).read_text()
    assert "must-not-be-persisted" not in persisted
    assert "AR_TEST_SECRET" not in persisted


def test_lost_wrapper_kills_registered_orphan_and_fails_closed(tmp_path):
    repo = make_repo(tmp_path, 30.0)
    store_path = tmp_path / "evidence.jsonl"
    worktrees = tmp_path / "worktrees"
    owner = start_owner(repo, store_path, worktrees)
    store = AppendOnlyStore(store_path)
    record = wait_for_started(store)
    deadline = time.monotonic() + 10
    while not Path(record["target_path"]).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    target = json.loads(Path(record["target_path"]).read_text())
    owner.kill()
    owner.wait(timeout=5)
    os.kill(record["wrapper_pid"], signal.SIGKILL)
    assert process_alive(target["pid"], target["start_ticks"])

    restored = GitWorktreeExecutor(contract(repo), forbidden_builder, store)
    workspace = GitWorktree(repo, worktrees)
    deadline = time.monotonic() + 5
    while process_alive(record["wrapper_pid"], record["wrapper_start_ticks"]) \
            and time.monotonic() < deadline:
        time.sleep(0.02)
    evidence = restored.recover_inflight(workspace)[0]
    assert evidence.eval_result.status is EvalStatus.FAILED_TO_RUN
    assert evidence.executor_status == "failed_to_run"
    assert "without an atomic result" in evidence.result_text
    deadline = time.monotonic() + 5
    while process_alive(target["pid"], target["start_ticks"]) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not process_alive(target["pid"], target["start_ticks"])
    assert not list(worktrees.iterdir())
    assert restored.recover_inflight(workspace) == []
    assert len(list(store.read("executor_evidence"))) == 1
    assert len(list(store.read("executor_process_finished"))) == 1


def test_finished_process_without_executor_evidence_is_finalized_once(tmp_path):
    repo = make_repo(tmp_path, 0.0)
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    executor = GitWorktreeExecutor(contract(repo), builder, store)
    workspace = GitWorktree(repo, tmp_path / "worktrees")
    candidate = Candidate("terminal-gap", hypothesis="h")
    request = EvalRequest("dev", time_limit=10)
    spec = ExecutorSpec(hypothesis="h", execution_ref="terminal-gap-cohort")
    ref = workspace.fork("HEAD")
    root = workspace.path_for(ref)
    protected = workspace.manifest(ref, ("eval.py",))
    builder(candidate, root)
    completed = executor._run_command(root, request, candidate, spec, 1, ref, protected)
    assert completed["returncode"] == 0
    assert len(list(store.read("executor_process_finished"))) == 1
    assert list(store.read("executor_evidence")) == []

    restored = GitWorktreeExecutor(contract(repo), forbidden_builder, store)
    new_workspace = GitWorktree(repo, tmp_path / "worktrees")
    evidence = restored.recover_inflight(
        new_workspace, execution_ref="terminal-gap-cohort")
    assert len(evidence) == 1 and evidence[0].eval_result.status is EvalStatus.OK
    assert len(list(store.read("executor_process_finished"))) == 1
    assert len(list(store.read("executor_evidence"))) == 1
    assert restored.recover_inflight(
        new_workspace, execution_ref="terminal-gap-cohort") == []
    assert not list(new_workspace.run_root.iterdir())


def test_adopt_rejects_mismatched_identity(tmp_path):
    repo = make_repo(tmp_path, 0.0)
    workspace = GitWorktree(repo, tmp_path / "worktrees")
    ref = workspace.fork("HEAD")
    path = workspace.path_for(ref)
    with pytest.raises(ValueError, match="path does not match"):
        workspace.adopt(ref, tmp_path / "other")
    with pytest.raises(ValueError, match="candidate worktree branches"):
        workspace.adopt("main", path)
    assert workspace.adopt(ref, path) == path
    workspace.destroy(ref)


def test_pid_start_mismatch_never_adopts_reused_process(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    journal = ProcessJournal(store)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             start_new_session=True)
    try:
        (tmp_path / "target.json").write_text(json.dumps({
            "pid": child.pid, "start_ticks": start_ticks(child.pid) + 1}))
        record = {"execution_id": "pid-reuse", "candidate_id": "c", "attempt": 1,
                  "wrapper_pid": child.pid,
                  "wrapper_start_ticks": start_ticks(child.pid) + 1,
                  "result_path": str(tmp_path / "missing-result.json"),
                  "target_path": str(tmp_path / "target.json")}
        state = journal.recover(record)
        assert state["status"] == "lost"
        assert process_alive(child.pid, start_ticks(child.pid))
    finally:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def test_corrupt_result_is_lost_not_finished(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    journal = ProcessJournal(store)
    (tmp_path / "result.json").write_text('{"returncode": 0} trailing')
    (tmp_path / "target.json").write_text("{}")
    record = {"execution_id": "corrupt", "candidate_id": "c", "attempt": 1,
              "wrapper_pid": 99999999, "wrapper_start_ticks": 1,
              "result_path": str(tmp_path / "result.json"),
              "target_path": str(tmp_path / "target.json")}
    state = journal.recover(record)
    assert state["status"] == "lost"
    assert "invalid durable process result" in state["detail"]
    assert list(store.read("executor_process_finished")) == []


def owner_main(repo: Path, store_path: Path, worktrees: Path) -> None:
    store = AppendOnlyStore(store_path)
    executor = GitWorktreeExecutor(contract(repo), builder, store)
    workspace = GitWorktree(repo, worktrees)
    candidate = Candidate("owner-crash", hypothesis="h", operator="improve")
    asyncio.run(executor.execute(ExecutorSpec(hypothesis="h"), candidate, workspace,
                                 EvalRequest("dev", time_limit=60, seed_set=[7])))


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
