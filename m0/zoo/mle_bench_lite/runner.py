"""Real paired MLE-Bench Lite campaign runner.

No submission, no official grading report, or an incomplete task/seed matrix produces
an incomplete campaign, never a synthetic BenchmarkRunRecord or comparison score.
The agent wallclock limit excludes the final official grading call.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import signal
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from core.tasks.adapter import Workspace
from core.tasks.benchmark import compare_same_budget
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite.adapter import TASK_LIST_SHA256, MLEBenchLiteAdapter
from zoo.mle_bench_lite.agent_common import token_usage_summary


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def preflight(official_root: Path, data_root: Path, task_ids: list[str],
              require_official_package: bool = True,
              manifest_path: str | Path | None = None) -> dict[str, MLEBenchLiteAdapter]:
    """Validate every requested task before creating any agent run."""
    registry = None
    if require_official_package:
        from mlebench.registry import Registry
        registry = Registry(data_root)
    adapters = {}
    for task_id in task_ids:
        adapter = MLEBenchLiteAdapter(task_id, official_root, data_root, manifest_path)
        sample = data_root / task_id / "prepared/public/sample_submission.csv"
        if not sample.is_file():
            raise FileNotFoundError(f"prepared public data missing: {task_id}")
        if registry is not None:
            registry.get_competition(task_id)  # includes prepared private grading data
        adapters[task_id] = adapter
    return adapters


def _command(template: str, workspace: Path, task_id: str, seed: int,
             arm: str, time_limit: float) -> list[str]:
    values = {"workspace": str(workspace), "submission": str(workspace / "submission.csv"),
              "task": task_id, "seed": str(seed), "arm": arm,
              "time_limit": str(time_limit)}
    return [token.format(**values) for token in shlex.split(template)]


def _execute_agent(template: str, workspace: Path, task_id: str, seed: int,
                   arm: str, time_limit: float, run_dir: Path,
                   agent_env: dict[str, str] | None = None) -> dict:
    command = _command(template, workspace, task_id, seed, arm, time_limit)
    env = os.environ.copy()  # credentials may be inherited, never serialized by this runner
    env.update({"MLE_TASK_ID": task_id, "MLE_SEED": str(seed), "MLE_ARM": arm,
                "MLE_WALLCLOCK_BUDGET": str(time_limit)})
    if agent_env:
        env.update(agent_env)
    started = time.monotonic()
    with (run_dir / "stdout.log").open("wb") as stdout, \
            (run_dir / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=workspace, env=env,
                                   stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        timed_out = False
        try:
            returncode = process.wait(timeout=time_limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
    return {"agent_returncode": returncode, "timed_out": timed_out,
            "actual_costs": {"wallclock": time.monotonic() - started}}


def _required_token_cost(run_dir: Path, token_budget: int) -> tuple[int, str, dict]:
    summary_path = run_dir / "agent_artifacts/agent_run.json"
    if not summary_path.is_file():
        raise ValueError("token usage evidence is missing: agent_run.json")
    agent_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    usage = token_usage_summary(run_dir / "agent_artifacts/token_usage")
    if agent_summary.get("token_usage") != usage:
        raise ValueError("agent token usage summary does not match independent receipts")
    if agent_summary.get("token_budget") != token_budget:
        raise ValueError("agent and campaign token budgets differ")
    if usage["total_tokens"] > token_budget:
        raise ValueError(f"token budget exceeded: {usage['total_tokens']} > {token_budget}")
    if len(usage["models"]) != 1:
        raise ValueError("token receipts must establish exactly one actual backbone")
    model = usage["models"][0]
    if agent_summary.get("actual_model") != model:
        raise ValueError("agent summary and token receipt backbones differ")
    return usage["total_tokens"], model, usage


def run_campaign(official_root: str | Path, data_root: str | Path,
                 output_root: str | Path, host_command: str, governed_command: str,
                 backbone: str, time_limit: float, seeds: tuple[int, ...] = (1, 2, 3),
                 task_ids: list[str] | None = None, noise_floor: float = 0.0,
                 grader_factory=None, manifest_path: str | Path | None = None,
                 token_budget: int | None = None) -> dict:
    if (not backbone or isinstance(time_limit, bool)
            or not isinstance(time_limit, (int, float)) or not math.isfinite(time_limit)
            or time_limit <= 0 or not seeds or len(set(seeds)) != len(seeds)
            or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)):
        raise ValueError("backbone, finite positive time_limit and unique integer seeds are required")
    if not math.isfinite(noise_floor) or not 0 <= noise_floor <= 1:
        raise ValueError("noise_floor must be finite and in [0,1]")
    if token_budget is not None and (isinstance(token_budget, bool)
            or not isinstance(token_budget, int) or token_budget <= 0):
        raise ValueError("token_budget must be a positive integer or None")
    official_root, data_root, output_root = map(Path, (official_root, data_root, output_root))
    tasks = list(task_ids or MLEBenchLiteAdapter.task_ids())
    if not tasks or len(set(tasks)) != len(tasks):
        raise ValueError("campaign tasks must be non-empty and unique")
    adapters = preflight(official_root, data_root, tasks,
                         require_official_package=grader_factory is None,
                         manifest_path=manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise FileExistsError("campaign output_root must be empty; evidence is not overwritten")
    expected = [(task, seed, arm) for task in tasks for seed in seeds
                for arm in ("host", "governed")]
    budget = {"wallclock": time_limit}
    if token_budget is not None:
        budget["token"] = token_budget
    records, failures, attempts = [], [], 0
    actual_models = {}
    for task_id, seed, arm in expected:
        run_dir = output_root / task_id / f"seed_{seed}" / arm
        workspace = run_dir / "workspace"
        run_dir.mkdir(parents=True)
        audit = AppendOnlyStore(run_dir / "audit.jsonl")
        summary = {"benchmark": "mle_bench_lite", "task_id": task_id,
                   "seed": seed, "arm": arm, "backbone": backbone,
                   "budget": dict(budget), "measured": False}
        try:
            adapter = adapters[task_id]
            adapter.setup(Workspace(workspace, audit), include_data=True)
            command = host_command if arm == "host" else governed_command
            execution = _execute_agent(
                command, workspace, task_id, seed, arm, time_limit, run_dir,
                agent_env={"MLE_OFFICIAL_ROOT": str(official_root.resolve()),
                           "MLE_DATA_ROOT": str(data_root.resolve()),
                           "MLE_MANIFEST_PATH": str(adapter.manifest_path.resolve()),
                           "MLE_AUDIT_PATH": str(run_dir / "audit.jsonl"),
                           "MLE_TOKEN_BUDGET": str(token_budget or 60_000)})
            attempts += 1
            summary.update(execution)
            if token_budget is not None:
                token_cost, actual_model, usage = _required_token_cost(run_dir, token_budget)
                execution["actual_costs"]["token"] = token_cost
                actual_models[(task_id, seed, arm)] = actual_model
                summary.update(actual_model=actual_model, token_usage=usage,
                               actual_costs=dict(execution["actual_costs"]))
            if not (workspace / "submission.csv").is_file():
                summary["status"] = "no_submission"
                failures.append({"task_id": task_id, "seed": seed, "arm": arm,
                                 "error": "no_submission"})
            else:
                grader = grader_factory(task_id) if grader_factory is not None else None
                adapter.grade_submission(Workspace(workspace), "audit", audit, grader=grader)
                raw = list(audit.read("official_grading_report"))[-1]["payload"]["report"]
                evidence_ref = str(run_dir / "audit.jsonl")
                record = adapter.measured_run_record(
                    raw, seed, arm, backbone, budget,
                    execution["actual_costs"], (evidence_ref,))
                record.validate_measured()
                records.append(record)
                summary.update(status="officially_graded", measured=True,
                               valid_submission=record.valid_submission,
                               any_medal=record.any_medal,
                               above_median=record.above_median,
                               evidence_refs=record.evidence_refs)
                _atomic_json(run_dir / "benchmark_run.json", asdict(record))
        except Exception as error:
            summary["status"] = "failed"
            summary["error"] = f"{type(error).__name__}: {error}"[-4000:]
            failures.append({"task_id": task_id, "seed": seed, "arm": arm,
                             "error": summary["error"]})
        _atomic_json(run_dir / "run.json", summary)

    host = [record for record in records if record.arm == "host"]
    governed = [record for record in records if record.arm == "governed"]
    full_matrix = set(tasks) == set(MLEBenchLiteAdapter.task_ids()) and len(seeds) >= 3
    comparison = None
    comparison_error = None
    backbone_evidence_complete = None
    if token_budget is not None:
        backbone_evidence_complete = (len(actual_models) == len(expected)
                                      and len(set(actual_models.values())) == 1)
    if len(records) == len(expected) and full_matrix and backbone_evidence_complete is False:
        comparison_error = "actual backbone evidence is incomplete or differs across runs"
    elif len(records) == len(expected) and full_matrix:
        try:
            comparison = asdict(compare_same_budget(
                host, governed, noise_floor,
                expected_task_ids=set(MLEBenchLiteAdapter.task_ids()), min_seeds=3,
                store=AppendOnlyStore(output_root / "comparison.jsonl"),
                required_cost_units=set(budget)))
        except Exception as error:
            comparison_error = f"{type(error).__name__}: {error}"
    elif len(records) != len(expected):
        comparison_error = "measured task-seed-arm matrix is incomplete"
    else:
        comparison_error = "RUBRIC B2 requires all 22 tasks and at least 3 seeds"
    report = {
        "benchmark": "mle_bench_lite", "official_revision": adapters[tasks[0]].manifest["revision"],
        "task_list_sha256": TASK_LIST_SHA256,
        "backbone": backbone, "budget": budget, "seeds": list(seeds),
        "backbone_evidence_complete": backbone_evidence_complete,
        "actual_backbones": {f"{task}:{seed}:{arm}": model
                             for (task, seed, arm), model in actual_models.items()},
        "task_ids": tasks, "expected_runs": len(expected), "agent_executions": attempts,
        "officially_graded_runs": len(records), "execution_complete": attempts == len(expected),
        "comparison_complete": comparison is not None, "comparison_error": comparison_error,
        "comparison": comparison, "failures": failures,
        "benchmark_run_records": [asdict(record) for record in records]}
    _atomic_json(output_root / "campaign.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--host-command")
    parser.add_argument("--governed-command")
    parser.add_argument("--backbone", default="declared-same-backbone")
    parser.add_argument("--time-limit", type=float, default=3600)
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--tasks", nargs="+")
    parser.add_argument("--noise-floor", type=float, default=0.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    tasks = args.tasks or MLEBenchLiteAdapter.task_ids()
    try:
        if args.preflight_only:
            preflight(args.official_root, args.data_root, tasks,
                      manifest_path=args.manifest_path)
            print(json.dumps({"preflight": "ready", "task_count": len(tasks),
                              "benchmark_execution": False}))
            return 0
        if not (args.output_root and args.host_command and args.governed_command):
            parser.error("campaign requires output-root, host-command and governed-command")
        report = run_campaign(args.official_root, args.data_root, args.output_root,
                              args.host_command, args.governed_command, args.backbone,
                              args.time_limit, tuple(args.seeds), tasks, args.noise_floor,
                              manifest_path=args.manifest_path, token_budget=args.token_budget)
        print(json.dumps({"expected_runs": report["expected_runs"],
                          "agent_executions": report["agent_executions"],
                          "officially_graded_runs": report["officially_graded_runs"],
                          "comparison_complete": report["comparison_complete"],
                          "comparison_error": report["comparison_error"]}, indent=2))
        return 0 if report["comparison_complete"] else 1
    except Exception as error:
        print(json.dumps({"preflight_or_campaign_error": f"{type(error).__name__}: {error}",
                          "comparison_complete": False}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
