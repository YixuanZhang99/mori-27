#!/usr/bin/env python3
"""Verifier v8: v7 plus M4 edge isolation and portable checkpoint recovery."""
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

from core.executor import Candidate, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.x1.store import AppendOnlyStore


def candidate(node, parents=()):
    return Candidate(node, parents=list(parents), hypothesis=f"h:{node}",
                     operator="improve" if parents else "draft")


def evidence(node, score):
    return EvidenceRecord(node, EvalResult(EvalStatus.OK, {"dev/score": score}),
                          f"branch/{node}", "scored", 1, result_text=f"result:{node}")


def populated(store=None):
    frontier = ResearchFrontier(store=store, sample_seed=17)
    frontier.add(candidate("root"), evidence("root", .5))
    frontier.add(candidate("left", ("root",)), evidence("left", .8))
    frontier.add(candidate("right", ("root",)), evidence("right", .7))
    frontier.add(candidate("child", ("left",)), evidence("child", .9))
    return frontier


def check_edges(root):
    store = AppendOnlyStore(root / "frontier.jsonl")
    frontier = populated(store)
    before = frontier.sample(4, "uniform")
    frontier.add_reference("right", "left", "information only")
    after = frontier.sample(4, "uniform")
    best_before = frontier.get_best()
    pruned = frontier.prune("left", "regression")
    passed = (frontier.nodes["child"].depth == 2 and before == after
              and best_before == "child" and pruned == ["child", "left"]
              and frontier.nodes["right"].status == "done"
              and frontier.get_best() == "right"
              and frontier.edges["reference"][0]["target"] == "left"
              and list(store.read("frontier_pruned"))[0]["payload"]["hard_deleted"] is False)
    return passed, {"depth": frontier.nodes["child"].depth,
                    "reference_sampling_stable": before == after,
                    "pruned": pruned, "referencing_node_status": frontier.nodes["right"].status,
                    "best_after_prune": frontier.get_best()}


def check_checkpoint(root):
    store = AppendOnlyStore(root / "checkpoint.jsonl")
    frontier = ResearchFrontier(store=store,
                                git_state={"branch": "run/1", "head": "abc123"},
                                messages=[{"role": "system", "content": "frozen"}])
    frontier.add(candidate("root"), evidence("root", .5))
    frontier.add(candidate("running", ("root",)), None)
    frontier.start("running")
    raw = frontier.checkpoint()
    restored = ResearchFrontier.restore(raw, store)
    byte_identical = restored.checkpoint() == raw
    restored.add(candidate("running", ("root",)), evidence("running", .75))
    envelope = json.loads(raw)
    tampered = json.loads(raw)
    tampered["payload"]["nodes"][0]["score"] = 999
    refusals = []
    for payload in (json.dumps(tampered).encode(), b"not-json"):
        try:
            ResearchFrontier.restore(payload)
            refusals.append(False)
        except ValueError:
            refusals.append(True)
    passed = (envelope["schema_version"] == 1
              and envelope["payload"]["git_state"]["head"] == "abc123"
              and envelope["payload"]["inflight_executor"] == ["running"]
              and envelope["payload"]["messages"][0]["content"] == "frozen"
              and byte_identical and restored.get_best() == "running"
              and json.loads(restored.checkpoint())["payload"]["inflight_executor"] == []
              and all(refusals))
    return passed, {"schema_version": envelope["schema_version"],
                    "git_state": envelope["payload"]["git_state"],
                    "inflight_before": envelope["payload"]["inflight_executor"],
                    "byte_identical_roundtrip": byte_identical,
                    "best_after_resume": restored.get_best(),
                    "integrity_refusals": refusals,
                    "full_framework_cycle_resume": False}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_research_frontier.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2000:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py" for version in ("v5", "v6", "v7", "v8")]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    v7 = subprocess.run([sys.executable, "verifier/v7/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v7_complete"] = v7.returncode == 0
    values["v7_exit"] = v7.returncode
    if v7.returncode:
        values["v7_stderr"] = v7.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("skeleton_reference_isolation", check_edges),
                         ("portable_checkpoint_recovery", check_checkpoint),
                         ("frontier_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v8/verify.py", "version": "v8",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v8.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
