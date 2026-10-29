#!/usr/bin/env python3
"""Verifier v18: owner-crash recovery through batch settlement and admission.

Requires v17, real two-candidate SIGKILL recovery with fresh scheduler/ledger/state,
pending refusal, exactly-once settlement/admission, multi-currency journal replay,
accounting-ambiguity refusal, terminal-process/evidence-gap recovery and CI wiring.
No external benchmark execution is claimed.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.executor import GitWorktree
from core.orchestration import BatchScheduler
from core.x1.store import AppendOnlyStore
from tests.test_batch_execution_recovery import (IDS, admission, components, make_repo)


def check_batch_owner_crash(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    repo = make_repo(root)
    store_path, worktrees = root / "evidence.jsonl", root / "worktrees"
    owner_script = ROOT / "tests/test_batch_execution_recovery.py"
    owner = subprocess.Popen([sys.executable, str(owner_script), "--owner",
                              str(repo), str(store_path), str(worktrees)],
                             cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    store = AppendOnlyStore(store_path)
    deadline = time.monotonic() + 10
    started = []
    while len(started) < 2 and time.monotonic() < deadline:
        started = list(store.read("executor_process_started"))
        time.sleep(0.02)
    if len(started) != 2:
        owner.kill()
        owner.wait()
        raise RuntimeError("batch owner did not start both evaluations")
    execution_refs = {record["payload"].get("execution_ref") for record in started}
    owner.kill()
    owner.wait(timeout=5)
    scheduler, pool, ledger, frontier, memory = components(repo, store, recover=True)
    workspace = GitWorktree(repo, worktrees)
    initial = scheduler.recovery_state()
    pending_refused = False
    try:
        asyncio.run(scheduler.resume(admission, workspace))
    except RuntimeError as exc:
        pending_refused = "execution_pending" in str(exc)
    early_admissions = len(list(store.read("batch_admission")))
    deadline = time.monotonic() + 10
    results = None
    while time.monotonic() < deadline:
        try:
            results = asyncio.run(scheduler.resume(admission, workspace))
            break
        except RuntimeError as exc:
            if "execution_pending" not in str(exc):
                raise
            time.sleep(0.05)
    if results is None:
        raise RuntimeError("recovered batch did not finish")
    before_repeat = list(store.read())
    repeated = asyncio.run(scheduler.resume(admission, workspace))
    after_repeat = list(store.read())
    settled = list(store.read("batch_execution_settled"))
    passed = (len(execution_refs) == 1 and None not in execution_refs
              and initial["status"] == "execution_incomplete"
              and pending_refused and early_admissions == 0
              and [item.candidate_id for item in results] == IDS
              and [frontier.nodes[node].status for node in IDS] == ["merged", "pruned"]
              and len(memory.entries) == 2 and ledger.spent["exploit"] == 0
              and not ledger.reserves and len(ledger.settled_intents) == 2
              and len(settled) == 2
              and all(record["payload"].get("recovered") for record in settled)
              and len(list(store.read("executor_process_started"))) == 2
              and len(list(store.read("executor_evidence"))) == 2
              and len(list(store.read("batch_cycle_completed"))) == 1
              and not list(worktrees.iterdir())
              and scheduler.recovery_state()["status"] == "completed"
              and [asdict(item) for item in repeated] == [asdict(item) for item in results]
              and after_repeat == before_repeat)
    pool.close()
    return passed, {"owner_returncode": owner.returncode,
                    "execution_ref_count": len(execution_refs),
                    "initial_state": initial, "pending_refused": pending_refused,
                    "early_admissions": early_admissions,
                    "node_statuses": [frontier.nodes[node].status for node in IDS],
                    "settled_records": len(settled), "token_spent": ledger.spent["exploit"],
                    "process_started_records": 2, "completed_records": 1,
                    "repeat_appended_records": len(after_repeat) - len(before_repeat),
                    "worktrees_remaining": [path.name for path in worktrees.iterdir()]}


def check_tests(_root):
    files = ["tests/test_batch_execution_recovery.py", "tests/test_executor_recovery.py",
             "tests/test_batch_recovery.py", "tests/test_batch_scheduler.py",
             "tests/test_batch_multicurrency.py", "tests/test_multi_currency.py",
             "tests/test_executor_hitl.py", "tests/test_executor_pool.py"]
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", *files], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2500:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    command = "python3 verifier/v18/verify.py"
    excluded = "python3 verifier/v14/verify.py" not in text
    return command in text and excluded, {"v18_command_present": command in text,
                                          "historical_v14_excluded": excluded,
                                          "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v17/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v17_complete"] = prior.returncode == 0
    values["v17_exit"] = prior.returncode
    if prior.returncode:
        values["v17_stderr"] = prior.stderr[-2500:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("real_batch_owner_crash_settle_and_admit", check_batch_owner_crash),
                         ("recovery_accounting_and_regression_contracts", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v18/verify.py", "version": "v18",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v18.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
