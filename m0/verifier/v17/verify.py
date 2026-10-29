#!/usr/bin/env python3
"""Verifier v17: real owner-crash recovery for detached M7 evaluations.

Acceptance requires v16, a real SIGKILL owner crash, an observed pending state,
exactly-once recovered evidence without builder re-execution, persistent artifacts,
worktree cleanup, orphan/PID/corruption contract tests, and CI wiring. External
benchmark execution is explicitly not claimed.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.executor import (Candidate, EvalRequest, EvalStatus, ExecutorSpec,
                           GitWorktree, GitWorktreeExecutor)
from core.tasks.adapter import EvalContract, FidelityLevel
from core.x1.store import AppendOnlyStore


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "verifier@example.invalid")
    git(repo, "config", "user.name", "v17 Verifier")
    (repo / "solution.py").write_text("VALUE = 0\n")
    (repo / "eval.py").write_text('''import json, pathlib, time
root = pathlib.Path(__file__).parent
time.sleep(2)
(root / "submission.csv").write_text("id,prediction\\n1,1\\n")
(root / "metrics.json").write_text(json.dumps({"dev/score": 0.75}))
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    return repo


def contract() -> EvalContract:
    return EvalContract(
        metric_direction="maximize", eval_cmd=f"{sys.executable} {{cwd}}/eval.py",
        fidelity_levels=(FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        required_outputs=("submission.csv",), protected_paths=("eval.py",))


def builder(candidate, root):
    (root / "candidate.json").write_text(json.dumps({"id": candidate.id}))


def forbidden_builder(candidate, root):
    raise AssertionError("v17 recovery attempted candidate rebuild")


def owner_main(repo: Path, store_path: Path, worktrees: Path) -> None:
    executor = GitWorktreeExecutor(contract(), builder, AppendOnlyStore(store_path))
    workspace = GitWorktree(repo, worktrees)
    asyncio.run(executor.execute(
        ExecutorSpec(hypothesis="h"), Candidate("v17-crash", hypothesis="h"),
        workspace, EvalRequest("dev", time_limit=30, seed_set=[17])))


def check_owner_crash(root: Path):
    repo = make_repo(root)
    store_path, worktrees = root / "evidence.jsonl", root / "worktrees"
    env = dict(os.environ)
    env["AR_V17_SECRET"] = "v17-must-not-be-persisted"
    owner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--owner",
                              str(repo), str(store_path), str(worktrees)],
                             cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    store = AppendOnlyStore(store_path)
    deadline = time.monotonic() + 10
    started = []
    while not started and time.monotonic() < deadline:
        started = list(store.read("executor_process_started"))
        time.sleep(0.02)
    if not started:
        owner.kill()
        owner.wait()
        raise RuntimeError("owner did not start evaluation")
    record = started[0]["payload"]
    owner.kill()
    owner.wait(timeout=5)
    restored = GitWorktreeExecutor(contract(), forbidden_builder, store)
    workspace = GitWorktree(repo, worktrees)
    pending = restored.recover_inflight(workspace)
    deadline = time.monotonic() + 10
    recovered = []
    while not recovered and time.monotonic() < deadline:
        recovered = restored.recover_inflight(workspace)
        time.sleep(0.05)
    second = restored.recover_inflight(workspace)
    events = list(store.read("executor_evidence"))
    finished = list(store.read("executor_process_finished"))
    artifact = None
    if recovered and recovered[0].branch_ref:
        artifact = git(repo, "show", f"{recovered[0].branch_ref}:submission.csv")
    persisted = store_path.read_text() + Path(record["spec_path"]).read_text()
    passed = (pending == [] and len(recovered) == 1 and second == []
              and recovered[0].eval_result.status is EvalStatus.OK
              and recovered[0].eval_result.metrics == {"dev/score": 0.75}
              and recovered[0].executor_status == "scored"
              and recovered[0].attempt == 1
              and artifact is not None and artifact.startswith("id,prediction")
              and not list(worktrees.iterdir()) and len(events) == 1
              and len(finished) == 1 and finished[0]["payload"]["recovered"] is True
              and "v17-must-not-be-persisted" not in persisted
              and "AR_V17_SECRET" not in persisted)
    return passed, {"owner_returncode": owner.returncode,
                    "pending_evidence": len(pending), "recovered_evidence": len(recovered),
                    "repeat_evidence": len(second), "terminal_events": len(finished),
                    "evidence_events": len(events),
                    "status": recovered[0].eval_result.status.value if recovered else None,
                    "artifact_persisted": bool(artifact), "worktrees_remaining":
                        [path.name for path in worktrees.iterdir()],
                    "secret_persisted": "v17-must-not-be-persisted" in persisted}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_executor_recovery.py", "tests/test_executor_hitl.py",
                           "tests/test_executor_pool.py", "tests/test_batch_recovery.py",
                           "tests/test_batch_scheduler.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2500:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    command = "python3 verifier/v17/verify.py"
    historical_excluded = "python3 verifier/v14/verify.py" not in text
    return command in text and historical_excluded, {
        "v17_command_present": command in text,
        "historical_v14_excluded": historical_excluded, "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v16/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v16_complete"] = prior.returncode == 0
    values["v16_exit"] = prior.returncode
    if prior.returncode:
        values["v16_stderr"] = prior.stderr[-2500:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("real_owner_crash_recovery", check_owner_crash),
                         ("recovery_and_regression_contracts", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v17/verify.py", "version": "v17",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v17.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--owner":
        owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        raise SystemExit(main())
