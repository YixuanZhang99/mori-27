"""v20 real Bubblewrap isolation and recovery interoperability (offline)."""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import (BubblewrapSandbox, Candidate, EvalRequest, EvalStatus,
                           ExecutorSpec, GitWorktree, GitWorktreeExecutor)
from core.tasks.adapter import EvalContract, FidelityLevel
from core.x1.store import AppendOnlyStore

PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None,
                                reason="real sandbox verification requires bubblewrap")


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def make_repo(root: Path, delay=0.0):
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "user.name", "Sandbox Tests")
    (repo / "solution.py").write_text("VALUE = 0\n")
    (repo / "eval.py").write_text(f'''import ctypes, errno, json, os, pathlib, socket, time
root = pathlib.Path(__file__).parent
libc = ctypes.CDLL(None, use_errno=True)
returncode = libc.syscall(101, 0, 0, 0, 0)  # x86_64 ptrace(PTRACE_TRACEME)
if returncode != -1 or ctypes.get_errno() != errno.EPERM:
    raise RuntimeError("seccomp ptrace probe was not rejected with EPERM")
candidate = json.loads((root / "candidate.json").read_text())
if candidate["id"] == "timeout":
    time.sleep(30)
if os.environ.get("AR_TEST_SECRET") is not None:
    raise RuntimeError("host environment leaked")
try:
    (root / "eval.py").write_text("tamper")
except OSError:
    pass
else:
    raise RuntimeError("protected path is writable")
try:
    pathlib.Path(candidate["host_secret"]).read_text()
except OSError:
    pass
else:
    raise RuntimeError("host secret file is visible")
if pathlib.Path(candidate["data_path"]).read_text() != "offline-data":
    raise RuntimeError("read-only data unavailable")
try:
    pathlib.Path(candidate["data_path"]).write_text("tamper")
except OSError:
    pass
else:
    raise RuntimeError("data_dir is writable")
try:
    connection = socket.create_connection(("127.0.0.1", candidate["port"]), timeout=0.2)
except OSError:
    pass
else:
    connection.close()
    raise RuntimeError("host network is reachable")
pathlib.Path(candidate["escape_path"]).write_text("private-tmp")
time.sleep({delay})
(root / "submission.csv").write_text("id,prediction\\n1,1\\n")
(root / "metrics.json").write_text(json.dumps({{"dev/score": 0.75, "sandbox/probe": 1}}))
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    return repo


def contract():
    return EvalContract(
        metric_direction="maximize", eval_cmd=f"{sys.executable} {{cwd}}/eval.py",
        fidelity_levels=(FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        required_outputs=("submission.csv",), protected_paths=("eval.py",))


def builder_for(tmp_path: Path, port: int):
    def builder(candidate, root):
        (root / "candidate.json").write_text(json.dumps({
            "id": candidate.id, "host_secret": str(tmp_path / "host-secret.txt"),
            "escape_path": str(tmp_path / "host-escape.txt"),
            "data_path": str(tmp_path / "data/input.txt"), "port": port}))
    return builder


def listener():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    return server


def test_real_sandbox_blocks_host_env_files_network_and_writes(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    (tmp_path / "host-secret.txt").write_text("host-canary")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/input.txt").write_text("offline-data")
    server = listener()
    monkeypatch.setenv("AR_TEST_SECRET", "environment-canary")
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    try:
        executor = GitWorktreeExecutor(contract(), builder_for(tmp_path, server.getsockname()[1]),
                                       store, data_dir=tmp_path / "data",
                                       sandbox=BubblewrapSandbox())
        workspace = GitWorktree(repo, tmp_path / "worktrees")
        evidence = asyncio.run(executor.execute(
            ExecutorSpec(), Candidate("sandbox-ok"), workspace,
            EvalRequest("dev", time_limit=10, seed_set=[20])))
    finally:
        server.close()
    assert evidence.executor_status == "scored", evidence.result_text
    assert evidence.eval_result.status is EvalStatus.OK
    assert evidence.eval_result.metrics["sandbox/probe"] == 1
    assert not (tmp_path / "host-escape.txt").exists()
    assert (tmp_path / "host-secret.txt").read_text() == "host-canary"
    assert (tmp_path / "data/input.txt").read_text() == "offline-data"
    persisted = store.path.read_text()
    for record in store.read("executor_process_started"):
        persisted += Path(record["payload"]["spec_path"]).read_text()
    assert "environment-canary" not in persisted
    assert "AR_TEST_SECRET" not in persisted
    assert not list(workspace.run_root.iterdir())


def test_sandbox_timeout_remains_structured(tmp_path):
    repo = make_repo(tmp_path)
    (tmp_path / "host-secret.txt").write_text("x")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/input.txt").write_text("offline-data")
    server = listener()
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    try:
        executor = GitWorktreeExecutor(contract(), builder_for(tmp_path, server.getsockname()[1]),
                                       store, data_dir=tmp_path / "data",
                                       sandbox=BubblewrapSandbox())
        workspace = GitWorktree(repo, tmp_path / "worktrees")
        evidence = asyncio.run(executor.execute(
            ExecutorSpec(), Candidate("timeout"), workspace,
            EvalRequest("dev", time_limit=1)))
    finally:
        server.close()
    assert evidence.executor_status == "timeout"
    assert evidence.eval_result.status is EvalStatus.TIMEOUT
    assert not list(workspace.run_root.iterdir())


def forbidden_builder(candidate, root):
    raise AssertionError("sandbox recovery attempted rebuild")


def test_real_sandbox_owner_crash_recovers_without_reexecution(tmp_path):
    repo = make_repo(tmp_path, delay=2.0)
    (tmp_path / "host-secret.txt").write_text("x")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/input.txt").write_text("offline-data")
    server = listener()
    store_path = tmp_path / "evidence.jsonl"
    owner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--owner",
                              str(repo), str(store_path), str(tmp_path / "worktrees"),
                              str(tmp_path), str(server.getsockname()[1])],
                             cwd=PROJECT, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    store = AppendOnlyStore(store_path)
    deadline = time.monotonic() + 10
    started = []
    while not started and time.monotonic() < deadline:
        started = list(store.read("executor_process_started"))
        time.sleep(0.02)
    assert started
    owner.kill()
    owner.wait(timeout=5)
    server.close()
    executor = GitWorktreeExecutor(contract(), forbidden_builder, store,
                                   data_dir=tmp_path / "data", sandbox=BubblewrapSandbox())
    workspace = GitWorktree(repo, tmp_path / "worktrees")
    deadline = time.monotonic() + 10
    evidence = []
    while not evidence and time.monotonic() < deadline:
        evidence = executor.recover_inflight(workspace)
        time.sleep(0.05)
    assert len(evidence) == 1 and evidence[0].eval_result.status is EvalStatus.OK
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("executor_evidence"))) == 1
    assert not list(workspace.run_root.iterdir())


def owner_main(repo, store_path, worktrees, tmp_path, port):
    executor = GitWorktreeExecutor(contract(), builder_for(tmp_path, port),
                                   AppendOnlyStore(store_path), data_dir=tmp_path / "data",
                                   sandbox=BubblewrapSandbox())
    asyncio.run(executor.execute(ExecutorSpec(), Candidate("sandbox-recovery"),
                                 GitWorktree(repo, worktrees),
                                 EvalRequest("dev", time_limit=30)))


if __name__ == "__main__" and len(sys.argv) == 7 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
               Path(sys.argv[5]), int(sys.argv[6]))
