#!/usr/bin/env python3
"""Verifier v9: v8 plus real Framework cycle interruption/recovery drills."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.archive import IslandArchive
from core.extensions import H2MonitorExtension
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "verifier v9 checkpointed research"
COMPARE = ("best_prompt", "best_score", "main_scores", "baseline_scores",
           "accepted_candidate_ids", "generations", "ledger", "health", "archive_health")


def config(stop=None, resume=False, generations=8):
    return LoopConfig(max_generations=generations, baseline_every=2,
                      checkpoint_enabled=True, resume_from_checkpoint=resume,
                      stop_after_generation=stop)


def differences(actual, expected):
    return [key for key in COMPARE if actual[key] != expected[key]]


def check_resume(root):
    reference = Framework(MockLLM(), toy_evaluator, config(), str(root / "reference"))
    expected = reference.evolve(TASK)
    interrupted_dir = root / "interrupted"
    partial = Framework(MockLLM(), toy_evaluator, config(stop=3),
                        str(interrupted_dir)).evolve(TASK)
    checkpoint = json.loads((interrupted_dir / "checkpoint.json").read_text())
    resumed_fw = Framework(MockLLM(), toy_evaluator, config(resume=True),
                           str(interrupted_dir))
    resumed = resumed_fw.evolve(TASK)
    replay = resumed_fw.replay()
    diff = differences(resumed, expected)
    replay_diff = differences(replay, expected)
    genesis = [record for record in resumed_fw.store.read("gate_evidence")
               if record["payload"]["rule_id"] == "genesis"]
    passed = (not partial["completed"] and partial["next_generation"] == 4
              and resumed["completed"] and resumed["resumed"]
              and not diff and not replay_diff and len(genesis) == 1
              and checkpoint["payload"]["inflight_executor"] == []
              and not (interrupted_dir / "checkpoint.json.tmp").exists())
    return passed, {"stop_next_generation": partial["next_generation"],
                    "resume_differences": diff, "replay_differences": replay_diff,
                    "genesis_executions": len(genesis),
                    "accepted_candidates": len(resumed["accepted_candidate_ids"]),
                    "checkpoint_schema": checkpoint["schema_version"],
                    "inflight_executor": checkpoint["payload"]["inflight_executor"]}


def island_framework(path, cfg):
    return Framework(MockLLM(), toy_evaluator, cfg, str(path),
                     extensions=[H2MonitorExtension(window=3, min_effective_parents=2)],
                     archive=IslandArchive(num_islands=2, migration_interval=2))


def check_archive(root):
    expected_fw = island_framework(root / "archive-reference", config())
    expected = expected_fw.evolve(TASK)
    island_framework(root / "archive-resume", config(stop=3)).evolve(TASK)
    resumed_fw = island_framework(root / "archive-resume", config(resume=True))
    resumed = resumed_fw.evolve(TASK)
    diff = differences(resumed, expected)
    expected_alarms = [r["payload"] for r in expected_fw.store.read("extension_alarm")]
    resumed_alarms = [r["payload"] for r in resumed_fw.store.read("extension_alarm")]
    passed = (not diff and resumed_alarms == expected_alarms
              and resumed["archive_health"]["migration_count"] >= 1)
    return passed, {"differences": diff, "alarm_sequences_equal": resumed_alarms == expected_alarms,
                    "migration_count": resumed["archive_health"]["migration_count"]}


def check_noop_refusals(root):
    run_dir = root / "complete"
    first_fw = Framework(MockLLM(), toy_evaluator, config(generations=4), str(run_dir))
    first = first_fw.evolve(TASK)
    receipts = len(list(first_fw.store.read("receipt")))
    resumed = Framework(MockLLM(), toy_evaluator, config(resume=True, generations=4),
                        str(run_dir)).evolve(TASK)
    receipt_after = len(list(first_fw.store.read("receipt")))
    refusal_dir = root / "refusal"
    Framework(MockLLM(), toy_evaluator, config(stop=1), str(refusal_dir)).evolve(TASK)
    path = refusal_dir / "checkpoint.json"
    original = path.read_bytes()
    tampered = json.loads(original)
    tampered["payload"]["main_scores"][0] = 999
    path.write_text(json.dumps(tampered))
    refusals = []
    try:
        Framework(MockLLM(), toy_evaluator, config(resume=True), str(refusal_dir)).evolve(TASK)
        refusals.append(False)
    except ValueError:
        refusals.append(True)
    path.write_bytes(original)
    for cfg, task in ((config(resume=True, generations=9), TASK),
                      (config(resume=True), "different task")):
        try:
            Framework(MockLLM(), toy_evaluator, cfg, str(refusal_dir)).evolve(task)
            refusals.append(False)
        except ValueError:
            refusals.append(True)
    passed = (not differences(resumed, first) and receipt_after == receipts and all(refusals))
    return passed, {"receipts_before": receipts, "receipts_after_completed_resume": receipt_after,
                    "completed_resume_differences": differences(resumed, first),
                    "integrity_config_task_refusals": refusals}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_loop_checkpoint.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2000:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py"
        for version in ("v5", "v6", "v7", "v8", "v9")]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    v8 = subprocess.run([sys.executable, "verifier/v8/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v8_complete"] = v8.returncode == 0
    values["v8_exit"] = v8.returncode
    if v8.returncode:
        values["v8_stderr"] = v8.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("uninterrupted_equivalence", check_resume),
                         ("archive_extension_recovery", check_archive),
                         ("completed_resume_noop_and_refusals", check_noop_refusals),
                         ("loop_checkpoint_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v9/verify.py", "version": "v9",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v9.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
