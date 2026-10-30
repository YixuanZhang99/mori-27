#!/usr/bin/env python3
"""Explicit CPU pilot on a disposable runner; never invoked by push/PR CI.

Data and full experiment evidence remain local to the runner. Only an allowlisted
numeric summary is exported for artifacts in this public repository.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TASKS = ("spooky-author-identification", "leaf-classification",
         "nomad2018-predict-transparent-conductors")


def request_from_environment(env) -> dict:
    model = env.get("PILOT_MODEL", "").strip()
    if not model or len(model) > 200 or any(ord(ch) < 32 for ch in model):
        raise ValueError("PILOT_MODEL must name one explicit model")
    mode = env.get("PILOT_MODE", "preflight")
    if mode not in {"preflight", "run"}:
        raise ValueError("PILOT_MODE must be preflight or run")
    values = {}
    for name, key, default, low, high in (
        ("token_budget", "PILOT_TOKEN_BUDGET", "", 1000, 100000),
        ("time_limit", "PILOT_TIME_LIMIT", "600", 60, 1800),
        ("iterations", "PILOT_ITERATIONS", "4", 3, 20),
    ):
        raw = env.get(key, default)
        if not raw.isdecimal() or not low <= int(raw) <= high:
            raise ValueError(f"{key} must be an integer between {low} and {high}")
        values[name] = int(raw)
    raw_seeds = env.get("PILOT_SEEDS", "1").split()
    if not 1 <= len(raw_seeds) <= 3 or any(not x.isdecimal() for x in raw_seeds):
        raise ValueError("PILOT_SEEDS requires 1–3 nonnegative integer seeds")
    seeds = [int(x) for x in raw_seeds]
    if len(set(seeds)) != len(seeds) or any(x > 2**31 - 1 for x in seeds):
        raise ValueError("PILOT_SEEDS must be unique 32-bit integers")
    if 6 * len(seeds) * values["time_limit"] > 18000:
        raise ValueError("planned search exceeds the 5-hour cloud allowance")
    return {"model": model, "mode": mode, "seeds": seeds, "task_ids": list(TASKS),
            "solution_timeout": min(120, values["time_limit"]), **values,
            "planned_runs": 6 * len(seeds),
            "total_declared_tokens": 6 * len(seeds) * values["token_budget"],
            "usd_cap_enforced": False}


def prepare_data(data_root: Path, log_root: Path, env) -> None:
    if not env.get("KAGGLE_USERNAME") or not env.get("KAGGLE_KEY"):
        raise ValueError("KAGGLE_USERNAME and KAGGLE_KEY must be configured; competition rules must already be accepted")
    log_root.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        # Official preparation verifies its dataset checksums. Never pass skip
        # verification or overwrite protected leaderboard/checksum switches.
        command = [sys.executable, "-m", "mlebench.cli", "prepare", "-c", task,
                   "--data-dir", str(data_root)]
        with (log_root / f"prepare-{task}.log").open("xb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=1200, env=dict(env))
        if result.returncode:
            raise RuntimeError(f"official preparation failed for {task}; no model calls started")


def export_summary(output_root: Path, destination: Path) -> dict:
    """Never recursively upload candidate workspaces, raw data, logs or secrets."""
    source = output_root / "pilot.json"
    if not source.is_file() or source.is_symlink():
        value = {"pilot_complete": False, "external_model_result_available": False,
                 "reason": "pilot report was not produced"}
    else:
        original = json.loads(source.read_text())
        value = {key: original.get(key) for key in (
            "schema_version", "benchmark", "scope", "subset_only", "formal_benchmark_complete",
            "evidence_kind", "pilot_complete", "expected_runs", "failure_count",
            "statistical_significance_claimed", "host_parity_claimed", "spec_sha256",
            "requested_model", "actual_models")}
        value["source_commit"] = os.environ.get("GITHUB_SHA")
        spec = original.get("spec", {})
        value["plan"] = {key: spec.get(key) for key in (
            "model", "task_ids", "seeds", "arms", "budget", "iterations",
            "solution_timeout", "provider_sampling", "official_revision", "execution_host")}
        value["runs"] = []
        for row in original.get("runs", []):
            item = {key: row.get(key) for key in (
                "task_id", "seed", "arm", "status", "budget", "actual_costs",
                "actual_model", "submission_sha256", "metric_direction", "dataset_identity",
                "profile_sha256", "official_report_sha256", "agent_summary_sha256")}
            audit = row.get("usage_audit", {})
            item["provider_usage"] = {key: audit.get(key) for key in (
                "known_tokens", "receipt_count", "started_calls", "completed_calls",
                "costs_complete", "complete", "actual_models")}
            item["unresolved_provider_calls"] = len(audit.get("unresolved_calls", []))
            failure_type = str(row.get("error", "")).split(":", 1)[0]
            item["failure_type"] = failure_type if failure_type in {
                "ValueError", "UsageError", "RuntimeError", "OSError", "FileNotFoundError",
                "TimeoutExpired", "PermissionError", "TypeError", "KeyError"} else None
            item["official_result"] = {key: row.get("official_result", {}).get(key) for key in (
                "score", "valid_submission", "above_median", "any_medal")}
            value["runs"].append(item)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "prepare", "execute", "export"))
    parser.add_argument("--official-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--public-report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "export":
            export_summary(args.output_root, args.public_report)
            return 0
        plan = request_from_environment(os.environ)
        if args.action == "validate":
            print(json.dumps(plan))
            return 0
        if args.action == "prepare":
            prepare_data(args.data_root, args.output_root / "preparation", os.environ)
            return 0
        from zoo.mle_bench_lite.pilot import preflight_pilot, run_pilot
        kwargs = {key: plan[key] for key in ("model", "token_budget", "time_limit",
                  "solution_timeout", "iterations", "seeds", "task_ids")}
        if plan["mode"] == "preflight":
            result = preflight_pilot(args.official_root, args.data_root, **kwargs)
            args.public_report.mkdir(parents=True, exist_ok=True)
            (args.public_report / "preflight.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"ready": result["ready"], "benchmark_execution": False}))
            return 0 if result["ready"] else 2
        result = run_pilot(args.official_root, args.data_root, args.output_root / "campaign", **kwargs)
        print(json.dumps({"pilot_complete": result["pilot_complete"], "scope": "task_subset_pilot"}))
        return 0 if result["pilot_complete"] else 1
    except Exception as error:
        # Logs on a public repo must not include server messages or data values.
        print(json.dumps({"error_type": type(error).__name__, "operation": args.action,
                          "completed": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
