#!/usr/bin/env python3
"""Verifier v2: v1 plus M4 island/archive and M3 health acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.archive import IslandArchive
from core.loop import Framework, LoopConfig
from examples.funsearch_offline import run as run_funsearch
from examples.toy_gepa import MockLLM, toy_evaluator


def main() -> int:
    checks: dict[str, bool] = {}
    values: dict = {}
    v1 = subprocess.run([sys.executable, "verifier/v1/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v1_complete"] = v1.returncode == 0
    values["v1_exit"] = v1.returncode

    with tempfile.TemporaryDirectory() as td:
        fs = run_funsearch(str(Path(td) / "funsearch"), generations=20)
        improves = [f for f in fs["funnels"] if f.operator == "improve"]
        checks["funsearch_real_behavior"] = (
            fs["best_score"] == 1.0 and fs["archive_health"]["migration_count"] >= 1
            and all(f.applicable == 1 for f in improves)
            and "<EVOLVE-BLOCK>" in fs["best_prompt"])
        values["funsearch"] = {"best_score": fs["best_score"],
                               "archive": fs["archive_health"]}

        mismatched_llm = (lambda p: "Solve the problem carefully."
                          if p.startswith("[draft") else "replacement")
        bad = Framework.from_profile("funsearch_island", mismatched_llm, toy_evaluator,
                                     LoopConfig(max_generations=2), str(Path(td) / "bad"))
        bad_out = bad.evolve("mismatch")
        bad_improves = [f for f in bad_out["funnels"] if f.operator == "improve"]
        checks["failed_apply_contained"] = bool(bad_improves) and all(
            f.runnable == 0 and f.admitted == 0 for f in bad_improves)

        archive = IslandArchive(num_islands=2, migration_interval=2)
        fw = Framework(MockLLM(), toy_evaluator, LoopConfig(max_generations=8),
                       str(Path(td) / "archive"), archive=archive)
        first = fw.evolve("archive replay")
        replay = fw.replay()
        checks["island_replay"] = (
            replay["main_scores"] == first["main_scores"]
            and replay["archive_health"] == first["archive_health"])
        archive.evict(first["accepted_candidate_ids"][0], "verifier")
        checks["soft_eviction"] = (
            archive.entries[first["accepted_candidate_ids"][0]].soft_deleted
            and first["accepted_candidate_ids"][0] in archive.entries)

        health_run = Framework(MockLLM(), toy_evaluator,
                               LoopConfig(max_generations=10), str(Path(td) / "health"))
        health_out = health_run.evolve("health")
        health = health_out["health"]
        checks["m3_health_metrics"] = (
            health["effective_budget_ratio"] == 1.0
            and abs(health["control_fulfillment_ratio"] - 2 / 3) < 1e-9
            and health["reconcile_delta_ratio"] >= 0
            and health["admitted_per_1k_tokens"] > 0)
        values["health"] = health

    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v2/verify.py", "version": "v2",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values}
    with (ROOT / "verifier/runs/v2.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
