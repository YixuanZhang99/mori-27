"""Real paired RE-Bench campaign runner using Vivaria score logs and official aggregation.

No score log, no finite official aggregate, or an incomplete seven-task/seed matrix
produces no B3 comparison. Protocol fixtures never become external benchmark scores.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time

from core.tasks.adapter import Workspace
from core.tasks.benchmark import compare_scores_same_budget
from core.x1.store import AppendOnlyStore
from zoo.re_bench.adapter import REVISION, TASK_LIST_SHA256, REBenchAdapter


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def preflight(official_root: Path, task_ids: list[str], require_official_runner: bool = True,
              manifest_path: str | Path | None = None) -> dict[str, REBenchAdapter]:
    if require_official_runner:
        if shutil.which("viv") is None:
            raise RuntimeError("RE-Bench requires the official Vivaria viv CLI")
        if importlib.util.find_spec("metr.task_protected_scoring") is None:
            raise RuntimeError("RE-Bench requires metr.task_protected_scoring")
    return {task: REBenchAdapter(task, official_root, manifest_path) for task in task_ids}


def _command(template: str, workspace: Path, task_id: str, seed: int,
             arm: str, time_limit: float, score_log: Path, official_root: Path) -> list[str]:
    values = {"workspace": str(workspace), "task": task_id, "seed": str(seed), "arm": arm,
              "time_limit": str(time_limit), "score_log": str(score_log),
              "official_root": str(official_root)}
    return [token.format(**values) for token in shlex.split(template)]


def _execute_agent(template: str, workspace: Path, task_id: str, seed: int,
                   arm: str, time_limit: float, score_log: Path, official_root: Path,
                   run_dir: Path) -> dict:
    command = _command(template, workspace, task_id, seed, arm, time_limit,
                       score_log, official_root)
    env = os.environ.copy()  # credentials are inherited, never serialized by this runner
    env.update({"RE_TASK_ID": task_id, "RE_SEED": str(seed), "RE_ARM": arm,
                "RE_WALLCLOCK_BUDGET": str(time_limit), "RE_SCORE_LOG": str(score_log),
                "RE_OFFICIAL_ROOT": str(official_root)})
    started = time.monotonic()
    with (run_dir / "stdout.log").open("wb") as stdout, \
            (run_dir / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=workspace, env=env,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            returncode = process.wait(timeout=time_limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
    return {"agent_returncode": returncode, "timed_out": timed_out,
            "actual_costs": {"wallclock": time.monotonic() - started}}


def run_campaign(official_root: str | Path, output_root: str | Path,
                 host_command: str, governed_command: str, backbone: str,
                 time_limit: float, seeds: tuple[int, ...] = (1, 2, 3),
                 task_ids: list[str] | None = None, noise_floor: float = 0.0,
                 aggregator_factory=None, manifest_path: str | Path | None = None) -> dict:
    if (not backbone or isinstance(time_limit, bool)
            or not isinstance(time_limit, (int, float)) or not math.isfinite(time_limit)
            or time_limit <= 0 or not seeds or len(set(seeds)) != len(seeds)
            or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)):
        raise ValueError("backbone, finite positive time_limit and unique integer seeds are required")
    if not math.isfinite(noise_floor) or noise_floor < 0:
        raise ValueError("score noise_floor must be finite and non-negative")
    official_root, output_root = Path(official_root), Path(output_root)
    tasks = list(task_ids or REBenchAdapter.task_ids())
    if not tasks or len(set(tasks)) != len(tasks):
        raise ValueError("RE-Bench campaign tasks must be non-empty and unique")
    adapters = preflight(official_root, tasks, require_official_runner=aggregator_factory is None,
                         manifest_path=manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise FileExistsError("campaign output_root must be empty; evidence is not overwritten")
    expected = [(task, seed, arm) for task in tasks for seed in seeds
                for arm in ("host", "governed")]
    budget = {"wallclock": time_limit}
    records, failures, attempts = [], [], 0
    for task_id, seed, arm in expected:
        run_dir = output_root / task_id / f"seed_{seed}" / arm
        workspace = run_dir / "workspace"
        audit_dir = run_dir / "audit"
        audit_dir.mkdir(parents=True)
        score_log = audit_dir / "score_log.json"
        audit = AppendOnlyStore(audit_dir / "audit.jsonl")
        summary = {"benchmark": "re_bench", "official_revision": REVISION,
                   "task_id": task_id, "seed": seed, "arm": arm, "backbone": backbone,
                   "budget": dict(budget), "measured": False}
        try:
            adapter = adapters[task_id]
            adapter.setup(Workspace(workspace, audit))
            command = host_command if arm == "host" else governed_command
            execution = _execute_agent(command, workspace, task_id, seed, arm, time_limit,
                                       score_log, official_root.resolve(), run_dir)
            attempts += 1
            summary.update(execution)
            if not score_log.is_file():
                raise FileNotFoundError("official Vivaria score log is missing")
            if execution["timed_out"] and not adapter.score_on_usage_limits():
                raise ValueError("task does not permit scoring on usage limits")
            aggregator = aggregator_factory(task_id) if aggregator_factory is not None else None
            report = adapter.grade_score_log(score_log, audit, aggregator=aggregator)
            evidence_refs = (str(audit.path), str(score_log))
            record = adapter.measured_run_record(
                report, seed, arm, backbone, budget, execution["actual_costs"],
                evidence_refs, timed_out=execution["timed_out"])
            record.validate_measured()
            records.append(record)
            summary.update(status="officially_scored", measured=True,
                           evidence_refs=evidence_refs)
            _atomic_json(run_dir / "benchmark_run.json", asdict(record))
        except Exception as error:
            summary["status"] = "failed"
            summary["error"] = f"{type(error).__name__}: {error}"[-4000:]
            failures.append({"task_id": task_id, "seed": seed, "arm": arm,
                             "error": summary["error"]})
        _atomic_json(run_dir / "run.json", summary)

    host = [record for record in records if record.arm == "host"]
    governed = [record for record in records if record.arm == "governed"]
    full_matrix = set(tasks) == set(REBenchAdapter.task_ids()) and len(seeds) >= 3
    comparison = None
    comparison_error = None
    if len(records) == len(expected) and full_matrix:
        try:
            comparison = asdict(compare_scores_same_budget(
                host, governed, noise_floor, expected_task_ids=set(REBenchAdapter.task_ids()),
                min_seeds=3, store=AppendOnlyStore(output_root / "comparison.jsonl"),
                required_cost_units={"wallclock"}))
        except Exception as error:
            comparison_error = f"{type(error).__name__}: {error}"
    elif len(records) != len(expected):
        comparison_error = "measured RE-Bench task-seed-arm matrix is incomplete"
    else:
        comparison_error = "RUBRIC B3 requires all 7 tasks and at least 3 seeds"
    report = {"benchmark": "re_bench", "official_revision": REVISION,
              "task_list_sha256": TASK_LIST_SHA256, "backbone": backbone,
              "budget": budget, "seeds": list(seeds), "task_ids": tasks,
              "expected_runs": len(expected), "agent_executions": attempts,
              "officially_scored_runs": len(records),
              "execution_complete": attempts == len(expected),
              "comparison_complete": comparison is not None,
              "comparison_error": comparison_error, "comparison": comparison,
              "failures": failures,
              "benchmark_run_records": [asdict(record) for record in records]}
    _atomic_json(output_root / "campaign.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--host-command")
    parser.add_argument("--governed-command")
    parser.add_argument("--backbone", default="declared-same-backbone")
    parser.add_argument("--time-limit", type=float, default=8 * 3600)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--tasks", nargs="+")
    parser.add_argument("--noise-floor", type=float, default=0.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    tasks = args.tasks or REBenchAdapter.task_ids()
    try:
        if args.preflight_only:
            preflight(args.official_root, tasks, manifest_path=args.manifest_path)
            print(json.dumps({"preflight": "ready", "task_count": len(tasks),
                              "benchmark_execution": False}))
            return 0
        if not (args.output_root and args.host_command and args.governed_command):
            parser.error("campaign requires output-root, host-command and governed-command")
        report = run_campaign(args.official_root, args.output_root, args.host_command,
                              args.governed_command, args.backbone, args.time_limit,
                              tuple(args.seeds), tasks, args.noise_floor,
                              manifest_path=args.manifest_path)
        print(json.dumps({"expected_runs": report["expected_runs"],
                          "agent_executions": report["agent_executions"],
                          "officially_scored_runs": report["officially_scored_runs"],
                          "comparison_complete": report["comparison_complete"],
                          "comparison_error": report["comparison_error"]}, indent=2))
        return 0 if report["comparison_complete"] else 1
    except Exception as error:
        print(json.dumps({"preflight_or_campaign_error": f"{type(error).__name__}: {error}",
                          "comparison_complete": False}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
