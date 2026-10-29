#!/usr/bin/env python3
"""Verifier v11: v10 plus Framework main-loop governed-state migration."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.frontier import ResearchFrontier
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "verifier v11 governed main loop"


class StaticLLM:
    def __call__(self, prompt: str) -> str:
        return "Solve the problem carefully."


def config(stop=None, resume=False, generations=6):
    return LoopConfig(max_generations=generations, baseline_every=2,
                      checkpoint_enabled=True, resume_from_checkpoint=resume,
                      stop_after_generation=stop)


def checkpoint_state(root):
    payload = json.loads((Path(root) / "checkpoint.json").read_text())["payload"]
    return payload["frontier_checkpoint"], payload["memory"]


def memory_candidates(memory_state):
    found = set()
    for entry in memory_state["entries"]:
        for ref in entry["provenance"]["evidence_refs"]:
            if ref.startswith("evidence://"):
                found.add(ref.split("/")[2])
    return found


def check_main_loop(root):
    fw = Framework(StaticLLM(), toy_evaluator, config(generations=4), str(root))
    result = fw.evolve(TASK)
    state = result["governed_state"]
    operations = Counter(record["payload"]["op"]
                         for record in fw.store.read("state_mutation"))
    frontier_raw, memory_state = checkpoint_state(root)
    restored = ResearchFrontier.restore(frontier_raw.encode("utf-8"))
    eligible = set(restored.sample(len(restored.nodes), "greedy"))
    expected_ops = {"add_node": 5, "update_node": 5, "write_memory": 5,
                    "promote_memory": 5, "merge": 1, "prune": 4}
    source = (ROOT / "core/loop.py").read_text()
    wired = ("policy.absorb" in source and "applier.apply_all" in source
             and "policy.select" in source and "frontier.add(" not in source
             and "memory.write(" not in source)
    passed = (state["frontier_nodes"] == 5
              and state["merged_ids"] == result["accepted_candidate_ids"]
              and len(state["merged_ids"]) == 1 and len(state["pruned_ids"]) == 4
              and eligible == set(state["merged_ids"])
              and state["memory_entries"] == 5
              and state["memory_levels"] == {"L1": 0, "L2": 5, "L3": 0}
              and state["mutation_receipts"] == 25 and operations == expected_ops
              and len(memory_state["entries"]) == 5 and wired)
    return passed, {"operations": dict(operations), "governed_state": state,
                    "eligible_parent_ids": sorted(eligible),
                    "main_loop_uses_absorb_and_serial_applier": wired,
                    "legacy_m0_main_loop_migrated": True,
                    "executor_pool_migrated": False}


def check_control(root):
    fw = Framework(MockLLM(), toy_evaluator, config(generations=6), str(root))
    result = fw.evolve(TASK)
    frontier_raw, memory_state = checkpoint_state(root)
    nodes = {node["id"] for node in json.loads(frontier_raw)["payload"]["nodes"]}
    baseline_ids = {record["payload"]["candidate_id"]
                    for record in fw.store.read("baseline")}
    memory_ids = memory_candidates(memory_state)
    passed = (len(baseline_ids) == 3 and not baseline_ids.intersection(nodes)
              and not baseline_ids.intersection(memory_ids)
              and result["ledger"]["spent"]["control"] > 0
              and result["governed_state"]["baseline_in_frontier"] is False)
    return passed, {"baseline_candidates": len(baseline_ids),
                    "baseline_frontier_overlap": sorted(baseline_ids.intersection(nodes)),
                    "baseline_memory_overlap": sorted(baseline_ids.intersection(memory_ids)),
                    "control_spent": result["ledger"]["spent"]["control"]}


def check_resume(root):
    reference_dir = root / "reference"
    reference_fw = Framework(MockLLM(), toy_evaluator, config(), str(reference_dir))
    expected = reference_fw.evolve(TASK)
    run_dir = root / "resumed"
    Framework(MockLLM(), toy_evaluator, config(stop=3), str(run_dir)).evolve(TASK)
    resumed_fw = Framework(MockLLM(), toy_evaluator, config(resume=True), str(run_dir))
    actual = resumed_fw.evolve(TASK)
    replay = resumed_fw.replay()
    resumed_state = checkpoint_state(run_dir)
    reference_state = checkpoint_state(reference_dir)
    receipts_before = len(list(resumed_fw.store.read("receipt")))
    mutations_before = len(list(resumed_fw.store.read("state_mutation")))
    completed_fw = Framework(MockLLM(), toy_evaluator, config(resume=True), str(run_dir))
    completed = completed_fw.evolve(TASK)
    passed = (actual["governed_state"] == expected["governed_state"]
              and replay["governed_state"] == expected["governed_state"]
              and completed["governed_state"] == expected["governed_state"]
              and resumed_state == reference_state
              and checkpoint_state(run_dir) == reference_state
              and len(list(completed_fw.store.read("receipt"))) == receipts_before
              and len(list(completed_fw.store.read("state_mutation"))) == mutations_before)
    return passed, {"frontier_memory_equal": resumed_state == reference_state,
                    "replay_governed_state_equal": replay["governed_state"] == expected["governed_state"],
                    "receipts_after_completed_resume": len(list(completed_fw.store.read("receipt"))),
                    "mutations_after_completed_resume": len(list(completed_fw.store.read("state_mutation"))),
                    "power_loss_injection_executed": False,
                    "external_inflight_recovery": False}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_loop_governed_state.py",
                           "tests/test_loop_checkpoint.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2000:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py"
        for version in ("v5", "v6", "v7", "v8", "v9", "v10", "v11")]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    prior = subprocess.run([sys.executable, "verifier/v10/verify.py"], cwd=ROOT,
                           text=True, capture_output=True)
    checks["v10_complete"] = prior.returncode == 0
    values["v10_exit"] = prior.returncode
    if prior.returncode:
        values["v10_stderr"] = prior.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("main_loop_absorption_and_admission", check_main_loop),
                         ("resident_control_isolation", check_control),
                         ("governed_state_resume", check_resume),
                         ("loop_governed_state_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v11/verify.py", "version": "v11",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v11.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
