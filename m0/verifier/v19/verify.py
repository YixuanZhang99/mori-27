#!/usr/bin/env python3
"""Verifier v19: idempotent recovery from real crashes inside settlement.

Requires v18, SIGKILL after a journaled token settle and inside a multi-unit basket,
exact cost reconciliation, missing-unit-only settlement, exactly-once ledger/batch/
admission evidence, completed no-op resume and CI wiring. No power-loss or external
benchmark claim is made.
"""
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

from core.executor import GitWorktree
from core.x1.store import AppendOnlyStore
from tests.test_batch_execution_recovery import IDS, admission, components
from tests.test_settlement_crash_recovery import (fast_repo, kill_at_marker,
                                                  multi_components, settle_keys,
                                                  start_owner)


def check_settlement_crash(root: Path, multi: bool):
    repo = fast_repo(root)
    store_path, worktrees = root / "evidence.jsonl", root / "worktrees"
    marker = root / "settled.marker"
    mode = "--owner-multi" if multi else "--owner-single"
    owner = start_owner(mode, repo, store_path, worktrees, marker)
    kill_at_marker(owner, marker)
    store = AppendOnlyStore(store_path)
    initial_keys = settle_keys(store)
    initial_batch = len(list(store.read("batch_execution_settled")))
    if multi:
        scheduler, pool, ledger, frontier, memory = multi_components(repo, store)
    else:
        scheduler, pool, ledger, frontier, memory = components(repo, store, recover=True)
    workspace = GitWorktree(repo, worktrees)
    initial = scheduler.recovery_state()
    results = asyncio.run(scheduler.resume(admission, workspace))
    keys = settle_keys(store)
    expected_keys = 12 if multi else 2
    before_repeat = list(store.read())
    repeated = asyncio.run(scheduler.resume(admission, workspace))
    after_repeat = list(store.read())
    if multi:
        physical_costs_ok = (ledger.spent["token"]["exploit"] == 0
                             and ledger.spent["usd"]["exploit"] == 0
                             and ledger.spent["wallclock"]["exploit"] > 0)
    else:
        physical_costs_ok = ledger.spent["exploit"] == 0
    passed = (len(initial_keys) == 1 and initial_batch == 0
              and initial["status"] == "accounting_ambiguous"
              and initial["accounting_recovery_safe"]
              and [item.candidate_id for item in results] == IDS
              and len(keys) == expected_keys and set(keys.values()) == {1}
              and physical_costs_ok and not ledger.reserves
              and len(ledger.settled_intents) == 2
              and [frontier.nodes[node].status for node in IDS] == ["merged", "pruned"]
              and len(memory.entries) == 2
              and len(list(store.read("batch_execution_settled"))) == 2
              and len(list(store.read("executor_process_started"))) == 2
              and len(list(store.read("batch_cycle_completed"))) == 1
              and scheduler.recovery_state()["status"] == "completed"
              and not list(worktrees.iterdir())
              and [asdict(item) for item in repeated] == [asdict(item) for item in results]
              and after_repeat == before_repeat)
    pool.close()
    return passed, {"owner_returncode": owner.returncode,
                    "initial_settlement_keys": len(initial_keys),
                    "final_settlement_keys": len(keys),
                    "settlement_multiplicity": sorted(set(keys.values())),
                    "initial_batch_records": initial_batch,
                    "initial_state": initial, "physical_costs_ok": physical_costs_ok,
                    "node_statuses": [frontier.nodes[node].status for node in IDS],
                    "repeat_appended_records": len(after_repeat) - len(before_repeat)}


def check_tests(_root):
    files = ["tests/test_settlement_crash_recovery.py",
             "tests/test_batch_execution_recovery.py", "tests/test_executor_recovery.py",
             "tests/test_batch_recovery.py", "tests/test_batch_scheduler.py",
             "tests/test_batch_multicurrency.py", "tests/test_multi_currency.py",
             "tests/test_executor_hitl.py", "tests/test_executor_pool.py"]
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", *files], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2500:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    command = "python3 verifier/v19/verify.py"
    excluded = "python3 verifier/v14/verify.py" not in text
    return command in text and excluded, {"v19_command_present": command in text,
                                          "historical_v14_excluded": excluded,
                                          "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v18/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v18_complete"] = prior.returncode == 0
    values["v18_exit"] = prior.returncode
    if prior.returncode:
        values["v18_stderr"] = prior.stderr[-2500:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scenarios = (("token_settle_gap_crash", False),
                     ("multi_unit_partial_settle_crash", True))
        for name, multi in scenarios:
            try:
                checks[name], values[name] = check_settlement_crash(root / name, multi)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
        for name, fn in (("settlement_recovery_contracts", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v19/verify.py", "version": "v19",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v19.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
