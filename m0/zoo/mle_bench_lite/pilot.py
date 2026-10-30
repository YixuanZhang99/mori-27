"""Small, paired MLE-Bench Lite pilots; never a full-suite benchmark result.

All arms finish and their submissions are frozen before any official grading.
The CLI uses one composed implementation with explicit baseline/full variants.
Offline injected graders/commands are labelled protocol fixtures throughout.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Callable

from core.tasks.adapter import Workspace
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite.adapter import REVISION, TASK_LIST_SHA256
from zoo.mle_bench_lite.usage_audit import audit_usage
from zoo.mle_bench_lite.runner import _atomic_json, _execute_agent, _required_token_cost, preflight

DEFAULT_TASKS = (
    "spooky-author-identification", "leaf-classification",
    "nomad2018-predict-transparent-conductors",
)
ARMS = ("baseline", "full")
PROTOCOL = "mle-public-train-composed-v1"
MAX_COMPLETION_TOKENS = 4096


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def public_snapshot(root: Path) -> dict:
    """Hash bytes and names, rejecting links and special files before copying."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("public data root must be a real directory")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("public data must not contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("public data contains a non-regular file")
        files[path.relative_to(root).as_posix()] = file_digest(path)
    if not files:
        raise ValueError("public data is empty")
    return {"files": files, "sha256": digest(files)}


def _profile(variant: str, token_budget: int, seed: int, iterations: int) -> dict:
    from zoo.mle_bench_lite.composed_agent import build_profile
    return build_profile(variant=variant, token_budget=token_budget,
                         seed=seed, iterations=iterations)


def _protected_host_path(path: Path) -> None:
    resolved = path.resolve()
    for root in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        exposed = Path(root).resolve()
        if resolved == exposed or exposed in resolved.parents:
            raise ValueError("benchmark data, graders and results must be outside sandbox-visible system directories")


def _verify_official_checkout(root: Path) -> None:
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError("official_root must be a clean checkout of the locked revision")
        return result.stdout.strip()
    if (Path(git("rev-parse", "--show-toplevel")).resolve() != root.resolve()
            or git("rev-parse", "HEAD") != REVISION
            or git("status", "--porcelain", "--untracked-files=no")):
        raise ValueError("official_root must be a clean checkout of the locked revision")


def _regular_under(path: Path, root: Path) -> Path:
    root = root.resolve()
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError("official prepared file escapes its expected directory") from None
    current = root
    if root.is_symlink() or not root.is_dir():
        raise ValueError("official prepared directory must exist without symlinks")
    for part in relative.parts:
        if part in {".", ".."}:
            raise ValueError("official prepared path contains traversal")
        current = current / part
        if current.is_symlink():
            raise ValueError("official prepared files must not use symlinks")
    if not path.is_file():
        raise ValueError("official prepared file is missing or not a regular file")
    return path


def _official_prepared_identity(official_root: Path, data_root: Path, tasks: list[str], adapters: dict) -> dict:
    """Validate official code and prepared bytes without exposing answer contents."""
    import yaml
    official_root, data_root = official_root.resolve(), data_root.resolve()
    _verify_official_checkout(official_root)
    package_root = official_root / "mlebench"
    modules, sources = {}, {}
    for name, filename in (("mlebench", "__init__.py"), ("mlebench.registry", "registry.py"),
                           ("mlebench.data", "data.py"), ("mlebench.grade", "grade.py")):
        module = importlib.import_module(name)
        actual = Path(getattr(module, "__file__", ""))
        expected = _regular_under(package_root / filename, package_root)
        if actual.resolve() != expected.resolve():
            raise ValueError("imported mlebench package does not match the locked official_root")
        modules[name], sources[filename] = module, file_digest(expected)
    registry = modules["mlebench.registry"].Registry(data_root)
    prepared = {}
    for task in tasks:
        adapter = adapters[task]
        adapter.verify_protected()
        competition = registry.get_competition(task)
        task_root = data_root / task / "prepared"
        public, private = task_root / "public", task_root / "private"
        for path, expected in ((competition.public_dir, public), (competition.private_dir, private)):
            if Path(path).absolute() != expected or expected.is_symlink() or not expected.is_dir():
                raise ValueError("official prepared public/private directory is missing or has changed")
        checksums_path = official_root / "mlebench/competitions" / task / "checksums.yaml"
        if Path(competition.checksums).resolve() != checksums_path.resolve():
            raise ValueError("Registry checksums do not belong to the locked task")
        if not modules["mlebench.data"].is_dataset_prepared(competition):
            raise ValueError("official is_dataset_prepared rejected the task")
        expected_sums = yaml.safe_load(checksums_path.read_text())
        if not isinstance(expected_sums, dict):
            raise ValueError("official prepared checksums are missing")
        task_record = {"checksums_sha256": file_digest(checksums_path), "files": {}, "registry_files": {}}
        for split, directory in (("public", public), ("private", private)):
            checksums = expected_sums.get(split)
            if not isinstance(checksums, dict) or not checksums:
                raise ValueError("official prepared checksum split is missing")
            csv_sums = {name: value for name, value in checksums.items() if isinstance(name, str) and name.endswith(".csv")}
            if not csv_sums or set(csv_sums) != {path.name for path in directory.glob("*.csv")}:
                raise ValueError("prepared CSV files differ from the official checksum manifest")
            for name, expected_md5 in csv_sums.items():
                if Path(name).name != name or not isinstance(expected_md5, str):
                    raise ValueError("official prepared checksum path is invalid")
                path = _regular_under(directory / name, task_root)
                checksum = hashlib.md5()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(block)
                if checksum.hexdigest() != expected_md5:
                    raise ValueError(f"official prepared {split} CSV checksum mismatch for {task}")
                task_record["files"][f"{split}/{name}"] = {"md5": expected_md5, "sha256": file_digest(path)}
        for field, expected_directory in (("answers", private), ("gold_submission", private),
                                           ("sample_submission", public)):
            path = _regular_under(Path(getattr(competition, field)), task_root)
            if path.parent != expected_directory or path.relative_to(task_root).as_posix() not in task_record["files"]:
                raise ValueError("Registry answers/gold/sample are not covered by official prepared checksums")
            task_record["registry_files"][field] = path.relative_to(task_root).as_posix()
        prepared[task] = task_record
    return {"revision": REVISION, "package_sources": sources, "prepared_tasks": prepared}


def _dataset_manifest(public_root: Path, task: str, seed: int) -> dict:
    from zoo.mle_bench_lite.public_train import PublicTrainBundle
    with tempfile.TemporaryDirectory(prefix="mle-pilot-preflight-") as temporary:
        return PublicTrainBundle(public_root, Path(temporary) / "inputs", task, seed).manifest


def _validate_plan(model, token_budget, time_limit, solution_timeout, iterations,
                   seeds, tasks) -> None:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("an explicit nonempty model is required")
    if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
        raise ValueError("token_budget must be a positive integer")
    for name, value in (("time_limit", time_limit), ("solution_timeout", solution_timeout)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if solution_timeout > time_limit:
        raise ValueError("solution_timeout cannot exceed the per-run time_limit")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 3:
        raise ValueError("pilot iterations must be at least 3 to exercise crossover and feedback")
    if not seeds or len(seeds) != len(set(seeds)) or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds):
        raise ValueError("seeds must be unique nonnegative integers")
    if not 3 <= len(tasks) <= 5 or len(set(tasks)) != len(tasks):
        raise ValueError("a pilot requires 3–5 unique task IDs")


def _plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks):
    _validate_plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks)
    endpoint = os.environ.get("OPENAI_API_BASE", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    parsed = urllib.parse.urlsplit(endpoint)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("provider endpoint must be HTTPS without credentials/query (loopback HTTP fixtures excepted)")
    return {"schema_version": 1, "protocol": PROTOCOL, "benchmark": "mle_bench_lite",
            "scope": "task_subset_pilot", "subset_only": True,
            "formal_benchmark_complete": False,
            "official_revision": REVISION, "official_task_list_sha256": TASK_LIST_SHA256,
            "task_ids": list(tasks), "seeds": list(seeds), "arms": list(ARMS),
            "model": model, "provider_base_url": endpoint, "provider_timeout": max(30.0, solution_timeout),
            "response_model_lock": "one actual snapshot across the complete pilot; stop on drift", "budget": {"token": token_budget, "wallclock": float(time_limit)},
            "solution_timeout": float(solution_timeout), "iterations": iterations,
            "provider_sampling": {"temperature": 0.0, "max_completion_tokens": MAX_COMPLETION_TOKENS, "seed_sent_to_provider": False},
            "seed_scope": "local data split and search sampling only; provider output is not reproducible",
            "grading_timing": "after_all_submissions_frozen",
            "wallclock_excludes_official_grading": True,
            "usd_budget_enforced": False,
            "expected_runs": len(tasks) * len(seeds) * len(ARMS)}


def preflight_pilot(official_root: str | Path, data_root: str | Path, *,
                    model: str, token_budget: int, time_limit: float = 600,
                    solution_timeout: float = 60, iterations: int = 4,
                    seeds: tuple[int, ...] = (1,), task_ids=None,
                    manifest_path: str | Path | None = None) -> dict:
    """Read-only readiness report. No provider request or agent process is started."""
    tasks = list(DEFAULT_TASKS if task_ids is None else task_ids)
    plan = _plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks)
    missing = []
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        missing.append({"requirement": "execution_host", "reason": "Linux x86_64 is required for the sandboxed real pilot"})
    if not shutil.which("bwrap"):
        missing.append({"requirement": "bubblewrap", "reason": "bwrap executable is unavailable"})
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append({"requirement": "model_credentials", "reason": "OPENAI_API_KEY is not configured"})
    if importlib.util.find_spec("mlebench") is None:
        missing.append({"requirement": "official_grader", "reason": "the pinned mlebench package is not installed"})
    try:
        _protected_host_path(Path(official_root))
        _protected_host_path(Path(data_root))
        adapters = preflight(Path(official_root), Path(data_root), tasks,
                             require_official_package=False, manifest_path=manifest_path)
        plan["public_data"] = {task: public_snapshot(
            Path(data_root) / task / "prepared/public") for task in tasks}
        plan["datasets"] = {f"{task}:{seed}": _dataset_manifest(
            Path(data_root) / task / "prepared/public", task, seed) for task in tasks for seed in seeds}
        plan["official_manifest_sha256"] = file_digest(adapters[tasks[0]].manifest_path)
        plan["profiles"] = {f"{seed}:{arm}": _profile(arm, token_budget, seed, iterations)
                            for seed in seeds for arm in ARMS}
        if importlib.util.find_spec("mlebench") is not None:
            plan["official_prepared_identity"] = _official_prepared_identity(
                Path(official_root), Path(data_root), tasks, adapters)
    except Exception as error:
        missing.append({"requirement": "official_snapshot_and_prepared_data",
                        "reason": f"{type(error).__name__}: {error}"})
    return {"ready": not missing, "benchmark_execution": False,
            "missing": missing, "plan": plan, "plan_sha256": digest(plan)}


def _command(model, token_budget, solution_timeout, iterations) -> str:
    argv = [sys.executable, "-m", "zoo.mle_bench_lite.composed_agent",
            "--workspace", "{workspace}", "--task", "{task}", "--seed", "{seed}",
            "--variant", "{arm}", "--model", model, "--token-budget", str(token_budget),
            "--solution-timeout", str(solution_timeout), "--iterations", str(iterations),
            "--max-completion-tokens", str(MAX_COMPLETION_TOKENS)]
    # The shared runner expands its known placeholders after shlex parsing.
    # Escape braces in the user-supplied model, which is never a shell command.
    argv[argv.index("--model") + 1] = model.replace("{", "{{").replace("}", "}}")
    return shlex.join(argv)


def _validate_agent_summary(summary: dict, *, task, seed, arm, model, token_budget,
                            profile: dict, public_data: dict, dataset: dict, iterations: int, solution_timeout: float) -> None:
    expected = {"task_id": task, "seed": seed, "variant": arm, "protocol": PROTOCOL,
                "requested_model": model, "token_budget": token_budget,
                "profile": profile, "profile_sha256": digest(profile)}
    for field, value in expected.items():
        if summary.get(field) != value:
            raise ValueError(f"agent {field} differs from the frozen pilot contract")
    manifest = summary.get("dataset_manifest")
    if not isinstance(manifest, dict) or summary.get("dataset_identity") != digest(manifest):
        raise ValueError("agent dataset identity is missing or inconsistent")
    if manifest != dataset:
        raise ValueError("agent dataset manifest differs from the independently frozen splits")
    settings = summary.get("details", {})
    for field, value in {"iterations": iterations, "solution_timeout": solution_timeout,
                         "temperature": 0.0, "max_completion_tokens": MAX_COMPLETION_TOKENS}.items():
        if settings.get(field) != value:
            raise ValueError(f"agent {field} differs from the frozen runtime settings")
    # The agent freezes precise selected CSVs and split membership. The runner
    # additionally binds the complete public input tree independently.
    if summary.get("public_data_sha256") != public_data["sha256"]:
        raise ValueError("agent public data identity differs from the frozen snapshot")


def _validate_provider_settings(run_dir: Path, spec: dict, *, fixture: bool):
    calls = run_dir / "agent_artifacts/token_usage_calls"
    starts = list(calls.glob("*.started.json"))
    if not starts and fixture:
        return
    if not starts:
        raise ValueError("provider invocation settings are missing")
    expected = {"requested_model": spec["model"], "base_url": spec["provider_base_url"],
                "temperature": spec["provider_sampling"]["temperature"],
                "max_completion_tokens": spec["provider_sampling"]["max_completion_tokens"],
                "timeout": spec["provider_timeout"], "token_budget": spec["budget"]["token"],
                "retry_policy": "never", "response_model_required": True}
    for path in starts:
        manifest = json.loads(path.read_text()).get("provider", {})
        for field, value in expected.items():
            if manifest.get(field) != value:
                raise ValueError(f"actual provider {field} differs from the frozen pilot settings")


def _summary_report(spec, rows, fixture: bool):
    complete = len(rows) == spec["expected_runs"] and all(row["status"] == "graded" for row in rows)
    actual_models = sorted({row["actual_model"] for row in rows if row.get("actual_model")})
    observed_models = sorted({model for row in rows for model in row.get("usage_audit", {}).get("actual_models", [])})
    same_backbone = len(observed_models) == 1
    backbone_complete = same_backbone and sum(bool(row.get("actual_model")) for row in rows) == spec["expected_runs"]
    complete = complete and backbone_complete
    pairs = []
    for task in spec["task_ids"]:
        for seed in spec["seeds"]:
            by_arm = {row["arm"]: row for row in rows if row["task_id"] == task and row["seed"] == seed}
            pair = {"task_id": task, "seed": seed, "complete": all(
                by_arm.get(arm, {}).get("status") == "graded" for arm in ARMS)}
            if pair["complete"] and not same_backbone:
                pair.update(complete=False, error="actual provider model differs across pilot runs")
            if pair["complete"]:
                baseline, full = by_arm["baseline"], by_arm["full"]
                if baseline["dataset_identity"] != full["dataset_identity"]:
                    pair.update(complete=False, error="paired dataset identities differ")
                    complete = False
                else:
                    scores = [row["official_result"]["score"] for row in (baseline, full)]
                    pair.update(metric_direction=baseline["metric_direction"],
                                baseline_score=scores[0], full_score=scores[1],
                                score_delta_full_minus_baseline=(scores[1] - scores[0])
                                    if all(score is not None for score in scores) else None,
                                token_delta_full_minus_baseline=full["actual_costs"]["token"] - baseline["actual_costs"]["token"],
                                wallclock_delta_full_minus_baseline=full["actual_costs"]["wallclock"] - baseline["actual_costs"]["wallclock"])
            pairs.append(pair)
    totals = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        graded = [row for row in arm_rows if row["status"] == "graded"]
        costs = [row.get("actual_costs", {}) for row in arm_rows]
        totals[arm] = {"planned_runs": len(spec["task_ids"]) * len(spec["seeds"]),
                      "graded_runs": len(graded), "failed_runs": len(arm_rows) - len(graded),
                      "valid_submissions": sum(row["official_result"]["valid_submission"] for row in graded),
                      "known_tokens": sum(row.get("usage_audit", {}).get("known_tokens", 0) for row in arm_rows),
                      "unknown_token_runs": sum(not row.get("usage_audit", {}).get("costs_complete", False) for row in arm_rows),
                      "incomplete_identity_runs": sum(not row.get("usage_audit", {}).get("complete", False) for row in arm_rows),
                      "known_wallclock": sum(cost.get("wallclock", 0) for cost in costs)}
    return {"schema_version": 1, "benchmark": "mle_bench_lite", "scope": "task_subset_pilot",
            "subset_only": True, "formal_benchmark_complete": False,
            "official_benchmark_measurement": not fixture and any(row["status"] == "graded" for row in rows),
            "evidence_kind": "protocol_fixture" if fixture else "official_task_subset",
            "spec_sha256": digest(spec), "spec": spec, "pilot_complete": complete,
            "expected_runs": spec["expected_runs"], "runs": rows, "pairs": pairs, "arms": totals,
            "requested_model": spec["model"], "actual_models": actual_models,
            "observed_response_models": observed_models, "backbone_evidence_complete": backbone_complete,
            "statistical_significance_claimed": False, "host_parity_claimed": False,
            "failure_count": sum(row["status"] != "graded" for row in rows)}


def run_pilot(official_root: str | Path, data_root: str | Path, output_root: str | Path, *,
              model: str, token_budget: int, time_limit: float = 600,
              solution_timeout: float = 60, iterations: int = 4,
              seeds: tuple[int, ...] = (1,), task_ids=None,
              manifest_path: str | Path | None = None, grader_factory: Callable | None = None,
              _fixture_agent_command: str | None = None) -> dict:
    """Run fixed paired variants. Test injections cannot emit production evidence."""
    tasks = list(DEFAULT_TASKS if task_ids is None else task_ids)
    spec = _plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks)
    if _fixture_agent_command is not None and grader_factory is None:
        raise ValueError("custom agent commands are reserved for labelled protocol fixtures")
    if grader_factory is None:
        for protected_root in (official_root, data_root, output_root):
            _protected_host_path(Path(protected_root))
        readiness = preflight_pilot(official_root, data_root, model=model,
            token_budget=token_budget, time_limit=time_limit, solution_timeout=solution_timeout,
            iterations=iterations, seeds=seeds, task_ids=tasks, manifest_path=manifest_path)
        if not readiness["ready"]:
            raise ValueError("pilot preflight failed: " + json.dumps(readiness["missing"]))
    official_root, data_root, output_root = map(lambda p: Path(p).resolve(),
                                               (official_root, data_root, output_root))
    adapters = preflight(official_root, data_root, tasks,
                         require_official_package=grader_factory is None, manifest_path=manifest_path)
    if grader_factory is None:
        spec["official_prepared_identity"] = _official_prepared_identity(official_root, data_root, tasks, adapters)
    spec["public_data"] = {task: public_snapshot(data_root / task / "prepared/public") for task in tasks}
    spec["datasets"] = {f"{task}:{seed}": _dataset_manifest(
        data_root / task / "prepared/public", task, seed) for task in tasks for seed in seeds}
    spec["official_manifest_sha256"] = file_digest(adapters[tasks[0]].manifest_path)
    spec["profiles"] = {f"{seed}:{arm}": _profile(arm, token_budget, seed, iterations)
                        for seed in seeds for arm in ARMS}
    spec["profile_sha256"] = {key: digest(value) for key, value in spec["profiles"].items()}
    spec["execution_host"] = {"system": platform.system(), "machine": platform.machine(),
                              "cpu_count": os.cpu_count(), "python": platform.python_version()}
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise FileExistsError("pilot output_root must be empty; evidence is not overwritten")
    _atomic_json(output_root / "pilot_spec.json", {"spec": spec, "sha256": digest(spec)})
    command = _fixture_agent_command or _command(model, token_budget, solution_timeout, iterations)
    rows = []
    observed_backbones = set()
    stop_reason = None
    for task in tasks:
        for seed in seeds:
            # Deterministically alternate which variant runs first to avoid one
            # always receiving the warm machine, while keeping paired seeds.
            order = ARMS if (tasks.index(task) + seeds.index(seed)) % 2 == 0 else tuple(reversed(ARMS))
            for arm in order:
                run_dir = output_root / task / f"seed_{seed}" / arm
                run_dir.mkdir(parents=True)
                workspace = run_dir / "workspace"
                row = {"task_id": task, "seed": seed, "arm": arm, "status": "pending",
                       "budget": dict(spec["budget"]), "actual_costs": {"token": 0, "wallclock": 0},
                       "usage_audit": {"known_tokens": 0, "receipt_count": 0,
                           "started_calls": 0, "completed_calls": 0, "unresolved_calls": [],
                           "errors": [], "costs_complete": True, "complete": True,
                           "actual_models": [], "usage": None, "not_executed": True},
                       "evidence_kind": "protocol_fixture" if grader_factory else "official_task_subset"}
                adapter = adapters[task]
                try:
                    if stop_reason is not None:
                        row["blocked_before_execution"] = True
                        raise ValueError(stop_reason)
                    if grader_factory is None:
                        try:
                            identity = _official_prepared_identity(official_root, data_root, tasks, adapters)
                            if identity != spec["official_prepared_identity"]:
                                raise ValueError("official prepared identity changed after pilot was frozen")
                        except Exception:
                            stop_reason = "official environment or prepared data changed; remaining paid runs are blocked"
                            raise
                    if public_snapshot(data_root / task / "prepared/public") != spec["public_data"][task]:
                        raise ValueError("public dataset changed after pilot was frozen")
                    adapter.setup(Workspace(workspace, AppendOnlyStore(run_dir / "audit.jsonl")), include_data=True)
                    if public_snapshot(workspace / "data") != spec["public_data"][task]:
                        raise ValueError("copied public dataset differs from frozen snapshot")
                    # From this point launch/operation failures need measured
                    # evidence; a prior preflight refusal has known zero cost.
                    row["actual_costs"] = {}
                    row.pop("usage_audit")
                    execution = _execute_agent(command, workspace, task, seed, arm, time_limit, run_dir, {
                        "MLE_OFFICIAL_ROOT": str(official_root), "MLE_DATA_ROOT": str(data_root),
                        "MLE_MANIFEST_PATH": str(adapter.manifest_path.resolve()),
                        "MLE_AUDIT_PATH": str(run_dir / "audit.jsonl"),
                        "MLE_TOKEN_BUDGET": str(token_budget),
                        "MLE_PILOT_SPEC_SHA256": digest(spec),
                        "MLE_PILOT_PUBLIC_DATA_SHA256": spec["public_data"][task]["sha256"],
                    })
                    row.update(execution)
                    # An unfinished second request cannot disappear behind the
                    # first request's valid receipt. Keep known and unknown costs separate.
                    usage_audit = audit_usage(run_dir / "agent_artifacts/token_usage",
                                              allow_fixture_receipts=grader_factory is not None)
                    if not usage_audit["receipt_count"] and not usage_audit["started_calls"]:
                        usage_audit.update(costs_complete=False, complete=False)
                        usage_audit["errors"].append({"kind": "absence", "call_id": "",
                            "reason": "agent left no call or usage evidence"})
                    row["usage_audit"] = usage_audit
                    observed_backbones.update(usage_audit["actual_models"])
                    if len(observed_backbones) > 1:
                        stop_reason = "actual provider model changed; remaining paid runs are blocked"
                    elif usage_audit["unresolved_calls"]:
                        stop_reason = "provider operation has unresolved usage; remaining paid runs are blocked"
                    elif not usage_audit["complete"] and (usage_audit["receipt_count"]
                            or usage_audit["started_calls"] or usage_audit["completed_calls"]):
                        stop_reason = "provider billing or identity evidence is invalid; remaining paid runs are blocked"
                    if usage_audit["costs_complete"]:
                        row["actual_costs"]["token"] = usage_audit["known_tokens"]
                    if usage_audit["usage"] is not None:
                        row["token_usage"] = usage_audit["usage"]
                    if execution["timed_out"] or execution["agent_returncode"] != 0:
                        raise ValueError("agent timed out or exited unsuccessfully")
                    if len(observed_backbones) > 1:
                        raise ValueError(stop_reason)
                    if not usage_audit["complete"] or not usage_audit["receipt_count"]:
                        raise ValueError("provider calls have incomplete usage or identity evidence")
                    _validate_provider_settings(run_dir, spec, fixture=grader_factory is not None)
                    token_cost, actual_model, usage = _required_token_cost(run_dir, token_budget)
                    row.update(actual_model=actual_model, token_usage=usage)
                    row["actual_costs"]["token"] = token_cost
                    summary = json.loads((run_dir / "agent_artifacts/agent_run.json").read_text())
                    _validate_agent_summary(summary, task=task, seed=seed, arm=arm, model=model,
                        token_budget=token_budget, profile=spec["profiles"][f"{seed}:{arm}"],
                        public_data=spec["public_data"][task], dataset=spec["datasets"][f"{task}:{seed}"],
                        iterations=iterations, solution_timeout=solution_timeout)
                    if public_snapshot(workspace / "data") != spec["public_data"][task]:
                        raise ValueError("agent modified the public input snapshot")
                    row["dataset_identity"] = summary["dataset_identity"]
                    row["profile_sha256"] = summary["profile_sha256"]
                    row["metric_direction"] = adapter.eval_contract().metric_direction
                    submission = workspace / "submission.csv"
                    if submission.is_symlink() or not submission.is_file():
                        raise ValueError("selected submission must be a regular non-link file")
                    frozen = run_dir / "frozen/submission.csv"
                    frozen.parent.mkdir()
                    shutil.copyfile(submission, frozen)
                    row.update(status="frozen", submission_sha256=file_digest(frozen),
                               submission_ref=str(frozen), agent_summary_sha256=file_digest(
                                   run_dir / "agent_artifacts/agent_run.json"))
                except Exception as error:
                    row.update(status="failed", error=f"{type(error).__name__}: {error}"[-2000:])
                _atomic_json(run_dir / "run.json", row)
                rows.append(row)
                _atomic_json(output_root / "pilot.json", _summary_report(spec, rows, grader_factory is not None))
    # No official hidden score exists until every arm has stopped and selected.
    for row in rows:
        if row["status"] != "frozen":
            continue
        task, seed, arm = row["task_id"], row["seed"], row["arm"]
        run_dir = output_root / task / f"seed_{seed}" / arm
        try:
            if grader_factory is None and _official_prepared_identity(
                    official_root, data_root, tasks, adapters) != spec["official_prepared_identity"]:
                raise ValueError("official prepared identity changed before final scoring")
            frozen = run_dir / "frozen/submission.csv"
            if file_digest(frozen) != row["submission_sha256"]:
                raise ValueError("frozen submission changed before official grading")
            audit = AppendOnlyStore(run_dir / "audit.jsonl")
            grader = grader_factory(task) if grader_factory else None
            public = adapters[task].grade_submission(Workspace(frozen.parent), "audit", audit, grader=grader)
            raw = list(audit.read("official_grading_report"))[-1]["payload"]["report"]
            score = raw.get("score")
            if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)):
                raise ValueError("official score must be finite or unavailable")
            valid = public["valid_submission"]
            if valid and score is None:
                raise ValueError("valid official submission has no numeric score")
            if file_digest(frozen) != row["submission_sha256"]:
                raise ValueError("frozen submission changed during official grading")
            row.update(status="graded", official_result={"score": score,
                "valid_submission": valid, "above_median": public["audit/above_median"],
                "any_medal": public["audit/any_medal"]},
                official_report_sha256=digest(raw), audit_ref=str(run_dir / "audit.jsonl"))
        except Exception as error:
            row.update(status="failed", error=f"{type(error).__name__}: {error}"[-2000:])
        _atomic_json(run_dir / "run.json", row)
    report = _summary_report(spec, rows, grader_factory is not None)
    _atomic_json(output_root / "pilot.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--token-budget", type=int, required=True)
    parser.add_argument("--time-limit", type=float, default=600)
    parser.add_argument("--solution-timeout", type=float, default=60)
    parser.add_argument("--iterations", type=int, default=4)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1])
    parser.add_argument("--tasks", nargs="+", default=list(DEFAULT_TASKS))
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    values = dict(model=args.model, token_budget=args.token_budget, time_limit=args.time_limit,
                  solution_timeout=args.solution_timeout, iterations=args.iterations,
                  seeds=tuple(args.seeds), task_ids=args.tasks, manifest_path=args.manifest_path)
    try:
        if args.preflight_only:
            report = preflight_pilot(args.official_root, args.data_root, **values)
            if args.output_root:
                args.output_root.mkdir(parents=True, exist_ok=True)
                if any(args.output_root.iterdir()):
                    raise FileExistsError("preflight output_root must be empty")
                _atomic_json(args.output_root / "preflight.json", report)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["ready"] else 2
        if not args.output_root:
            parser.error("--output-root is required to preserve pilot evidence")
        report = run_pilot(args.official_root, args.data_root, args.output_root, **values)
        print(json.dumps({key: report[key] for key in ("pilot_complete", "expected_runs",
              "failure_count", "subset_only", "formal_benchmark_complete")}, indent=2))
        return 0 if report["pilot_complete"] else 1
    except Exception as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}", "pilot_complete": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
