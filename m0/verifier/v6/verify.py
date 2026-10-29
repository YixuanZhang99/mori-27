#!/usr/bin/env python3
"""Verifier v6: v5 plus external benchmark adapter/comparison protocol."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.tasks.adapter import Workspace
from core.tasks.benchmark import BenchmarkRunRecord, compare_same_budget
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite.adapter import REVISION, TASK_LIST_SHA256, MLEBenchLiteAdapter

TASK = "aerial-cactus-identification"


def check_locked_snapshot(_root):
    adapter_dir = ROOT / "zoo/mle_bench_lite"
    split = adapter_dir / "assets/low.txt"
    manifest = json.loads((adapter_dir / "assets/snapshot_manifest.json").read_text())
    ids = MLEBenchLiteAdapter.task_ids()
    passed = (len(ids) == 22 and len(set(ids)) == 22
              and hashlib.sha256(split.read_bytes()).hexdigest() == TASK_LIST_SHA256
              and manifest["revision"] == REVISION and len(manifest["files"]) == 111
              and all(manifest["files"].get(f"mlebench/competitions/{task}/grade.py")
                      for task in ids))
    return passed, {"tasks": len(ids), "task_list_sha256": TASK_LIST_SHA256,
                    "revision": REVISION, "protected_files": len(manifest["files"])}


def fixture(root):
    official, data = root / "official", root / "data"
    task_dir = official / "mlebench/competitions" / TASK
    task_dir.mkdir(parents=True)
    (official / "experiments/splits").mkdir(parents=True)
    split = (ROOT / "zoo/mle_bench_lite/assets/low.txt").read_bytes()
    (official / "experiments/splits/low.txt").write_bytes(split)
    bodies = {"config.yaml": "id: fixture\n", "grade.py": "# protected\n",
              "checksums.yaml": "files: {}\n", "description.md": "task\n"}
    for name, body in bodies.items():
        (task_dir / name).write_text(body)
    (task_dir / "leaderboard.csv").write_text("team,score\na,0.9\nb,0.5\nc,0.1\n")
    sample = data / TASK / "prepared/public/sample_submission.csv"
    sample.parent.mkdir(parents=True)
    sample.write_text("id,prediction\n1,0\n")
    files = {}
    for name in (*bodies, "leaderboard.csv"):
        rel = f"mlebench/competitions/{TASK}/{name}"
        files[rel] = hashlib.sha256((task_dir / name).read_bytes()).hexdigest()
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"revision": REVISION, "files": files}))
    return official, data, manifest


def check_adapter(root):
    official, data, manifest = fixture(root)
    adapter = MLEBenchLiteAdapter(TASK, official, data, manifest)
    workspace = root / "workspace"
    adapter.setup(Workspace(workspace, AppendOnlyStore(root / "setup.jsonl")))
    visible = {p.name for p in workspace.iterdir()}
    report = {"competition_id": TASK, "valid_submission": True, "score": .9,
              "above_median": True, "any_medal": True, "gold_medal": True,
              "silver_medal": False, "bronze_medal": False}
    dev = adapter.public_report(report, "dev")
    admission = adapter.public_report(report, "admission")
    audit = adapter.public_report(report, "audit")
    (official / f"mlebench/competitions/{TASK}/grade.py").write_text("# tampered\n")
    try:
        adapter.verify_protected()
        tamper_refused = False
    except ValueError:
        tamper_refused = True
    passed = (visible == {"description.md", "sample_submission.csv", "task.json", ".git"}
              and adapter.eval_contract().metric_direction == "maximize"
              and dev == {"competition_id": TASK, "valid_submission": True}
              and "score" not in admission and "audit/score" not in admission
              and audit["audit/score"] == .9 and tamper_refused)
    return passed, {"visible": sorted(visible), "dev_fields": sorted(dev),
                    "admission_fields": sorted(admission), "audit_score_visible": True,
                    "tamper_refused": tamper_refused}


def run(task, seed, arm, measured=True):
    return BenchmarkRunRecord(
        "mle_bench_lite", TASK_LIST_SHA256, task, seed, arm, "same-model",
        {"wallclock": 24, "eval_count": 5}, {"wallclock": 20, "usd": 1},
        valid_submission=seed != 3, any_medal=seed == 1,
        evidence_refs=(f"external://{arm}/{task}/{seed}/report.json",), measured=measured)


def check_comparison(root):
    tasks = {"task-a", "task-b"}
    host = [run(task, seed, "host") for task in tasks for seed in (1, 2, 3)]
    governed = [run(task, seed, "governed") for task in tasks for seed in (1, 2, 3)]
    store = AppendOnlyStore(root / "comparison.jsonl")
    report = compare_same_budget(host, governed, .1, tasks, store=store)
    unmeasured = list(governed)
    unmeasured[0] = replace(unmeasured[0], measured=False)
    unfair = list(governed)
    unfair[0] = replace(unfair[0], budget={"wallclock": 48})
    refusals = []
    for runs in (unmeasured, unfair, governed[:-1]):
        try:
            compare_same_budget(host, runs, .1)
            refusals.append(False)
        except ValueError:
            refusals.append(True)
    passed = (report.paired_runs == 6 and report.task_count == 2
              and report.host_valid_rate == report.governed_valid_rate == 2 / 3
              and report.medal_delta == 0 and report.verdict == "within_noise_floor"
              and all(refusals) and len(list(store.read("same_budget_comparison"))) == 1)
    return passed, {"paired_runs": report.paired_runs, "valid_rate": report.governed_valid_rate,
                    "medal_delta": report.medal_delta, "verdict": report.verdict,
                    "unmeasured_unfair_incomplete_refused": refusals,
                    "external_benchmark_executed": False}


def main() -> int:
    checks, values = {}, {}
    v5 = subprocess.run([sys.executable, "verifier/v5/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v5_complete"] = v5.returncode == 0
    values["v5_exit"] = v5.returncode
    if v5.returncode:
        values["v5_stderr"] = v5.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("locked_official_lite_snapshot", check_locked_snapshot),
                         ("workspace_protection_and_report_visibility", check_adapter),
                         ("measured_same_budget_comparison", check_comparison)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v6/verify.py", "version": "v6",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v6.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
