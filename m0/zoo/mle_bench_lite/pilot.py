"""Small, paired MLE-Bench Lite pilots; never a full-suite benchmark result.

All arms finish and their submissions are frozen before any official grading.
The CLI uses one composed implementation with explicit baseline/full variants.
Offline injected graders/commands are labelled protocol fixtures throughout.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib
import importlib.util
import json
import math
import os
import platform
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import sysconfig
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
GOVERNANCE_ARMS = ("one_control", "two_controls")
GOVERNANCE_SCHEDULES = {"one_control": (0,), "two_controls": (0, 2)}
from zoo.mle_bench_lite.public_train import PROTOCOL, load_anonymization_key
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


def _comparison_source_state(repo: Path) -> dict:
    """Identify a clean committed checkout; not runtime attestation."""
    root = Path(repo).resolve()
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}
    def git(*args):
        result = subprocess.run(['git', '-C', str(root), *args], env=env, capture_output=True,
                                text=True, timeout=15, check=True)
        return result.stdout.strip()
    try:
        top, commit, tree = git('rev-parse', '--show-toplevel'), git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
        dirty = git('status', '--porcelain=v1', '--untracked-files=normal')
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('comparison requires a verifiable clean source checkout') from error
    if Path(top).resolve() != root or not re.fullmatch(r'[0-9a-f]{40}', commit) or \
            not re.fullmatch(r'[0-9a-f]{40}', tree) or dirty:
        raise ValueError('comparison requires a clean committed source checkout')
    try:
        entries = subprocess.run(['git', '-C', str(root), 'ls-tree', '-rz', '--full-tree', commit],
                                 env=env, capture_output=True, timeout=15, check=True).stdout
        tracked = set()
        for entry in entries.split(b'\0'):
            if not entry:
                continue
            header, name = entry.split(b'\t', 1)
            mode, kind, expected = header.split(b' ')
            path = root / os.fsdecode(name)
            tracked.add(path)
            if kind != b'blob' or mode not in (b'100644', b'100755', b'120000'):
                raise ValueError('comparison requires a clean checkout without submodules')
            info = path.lstat()
            if mode == b'120000':
                if not stat.S_ISLNK(info.st_mode):
                    raise ValueError('comparison source file type changed')
                content = os.fsencode(os.readlink(path))
            else:
                if not stat.S_ISREG(info.st_mode) or bool(info.st_mode & 0o111) != (mode == b'100755'):
                    raise ValueError('comparison source file mode changed')
                content = path.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest().encode()
            if actual != expected:
                raise ValueError('comparison requires clean committed source bytes')
        source = root / 'm0'
        if source.is_dir():
            for directory, dirs, files in os.walk(source, followlinks=False):
                current = Path(directory)
                dirs[:] = [name for name in dirs if name != '__pycache__']
                if any((current / name).is_symlink() for name in dirs):
                    raise ValueError('comparison has an untracked importable source symlink')
                for name in files:
                    path = current / name
                    if path.is_symlink():
                        raise ValueError('comparison has a source symlink')
                    if name.endswith(('.py', '.pyc', '.so')) and path not in tracked:
                        raise ValueError('comparison has an untracked importable source file')
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('comparison requires verifiable clean source bytes') from error
    return {'commit': commit, 'tree': tree, 'scope': 'clean-checkout-not-runtime-attestation'}


def _comparison_runtime_source() -> dict:
    import core
    import zoo
    from zoo.mle_bench_lite import composed_agent
    root = Path(__file__).resolve().parents[3]
    for module, relative in ((core, 'm0/core/__init__.py'), (zoo, 'm0/zoo/__init__.py'),
                             (composed_agent, 'm0/zoo/mle_bench_lite/composed_agent.py')):
        if not getattr(module, '__file__', None) or Path(module.__file__).resolve() != root / relative:
            raise ValueError('comparison imports differ from the clean source checkout')
    return _comparison_source_state(root)


def _comparison_dependency_identity(paths) -> dict:
    """Hash installed dependency bytes under the trusted host's package roots."""
    roots = sorted({Path(path).resolve() for path in paths}, key=str)
    if not roots:
        raise ValueError('comparison requires installed dependency roots')
    result = {}
    for root in roots:
        if not root.is_dir():
            raise ValueError('comparison dependency root is missing')
        digestor = hashlib.sha256()
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError('comparison dependency roots cannot contain symlinks')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('comparison dependency contains a non-regular file')
            digestor.update(relative.encode() + b'\0' + file_digest(path).encode() + b'\0')
        result[str(root)] = digestor.hexdigest()
    return result


def _comparison_dependency_roots():
    return sorted({Path(sysconfig.get_path(name)).resolve() for name in ('purelib', 'platlib')}, key=str)


def _comparison_frozen_runtime(spec):
    return (_comparison_runtime_source() == spec['source'] and
            _comparison_dependency_identity(_comparison_dependency_roots()) == spec['comparison_dependencies'])


def _profile(variant: str, token_budget: int, seed: int, iterations: int, *,
             runtime='legacy', max_completion_tokens=MAX_COMPLETION_TOKENS) -> dict:
    from zoo.mle_bench_lite.composed_agent import build_profile, build_governed_profile
    if runtime == 'legacy':
        return build_profile(variant=variant, token_budget=token_budget, seed=seed, iterations=iterations)
    if runtime == 'm7':
        return build_governed_profile(variant=variant, token_budget=token_budget, seed=seed,
                                      iterations=iterations, max_completion_tokens=max_completion_tokens)
    raise ValueError('unknown pilot runtime')



def _runtime_profile(variant, token_budget, seed, iterations, *, runtime, max_completion_tokens):
    if runtime == 'legacy':
        return _profile(variant, token_budget, seed, iterations)
    return _profile(variant, token_budget, seed, iterations, runtime=runtime,
                    max_completion_tokens=max_completion_tokens)


def _comparison_profile(arm, token_budget, seed, iterations, *, max_completion_tokens):
    from zoo.mle_bench_lite.composed_agent import build_governed_profile
    if arm not in GOVERNANCE_SCHEDULES:
        raise ValueError('unknown governance comparison arm')
    return build_governed_profile(variant='full', token_budget=token_budget, seed=seed, iterations=iterations,
        max_completion_tokens=max_completion_tokens, control_cycles=GOVERNANCE_SCHEDULES[arm])


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


def _dataset_manifest(public_root: Path, task: str, seed: int, *, anonymization_key=None) -> dict:
    from zoo.mle_bench_lite.public_train import PublicTrainBundle
    with tempfile.TemporaryDirectory(prefix="mle-pilot-preflight-") as temporary:
        return PublicTrainBundle(public_root, Path(temporary) / "inputs", task, seed,
            anonymization_key=anonymization_key if anonymization_key is not None else secrets.token_bytes(32)).manifest


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


def _plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks,
          *, spending_ledger_path=None, runtime='legacy', comparison=None):
    if runtime not in {'legacy', 'm7'}:
        raise ValueError('unknown pilot runtime')
    if comparison not in (None, 'governance-intensity'):
        raise ValueError('unknown pilot comparison')
    if comparison is not None and runtime != 'm7':
        raise ValueError('governance comparison requires m7 runtime')
    if runtime == 'm7':
        if spending_ledger_path is None:
            raise ValueError('m7 requires the existing campaign ledger')
        _profile('baseline', token_budget, seeds[0] if seeds else 0, iterations,
                 runtime='m7', max_completion_tokens=16384)
        if comparison is not None:
            for arm in GOVERNANCE_ARMS:
                _comparison_profile(arm, token_budget, seeds[0] if seeds else 0, iterations,
                                    max_completion_tokens=16384)
    _validate_plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks)
    endpoint = os.environ.get("OPENAI_API_BASE", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    parsed = urllib.parse.urlsplit(endpoint)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("provider endpoint must be HTTPS without credentials/query (loopback HTTP fixtures excepted)")
    arms = GOVERNANCE_ARMS if comparison is not None else ARMS
    plan = {"schema_version": 1, "protocol": PROTOCOL, "benchmark": "mle_bench_lite",
            "scope": "task_subset_pilot", "subset_only": True,
            "formal_benchmark_complete": False,
            "official_revision": REVISION, "official_task_list_sha256": TASK_LIST_SHA256,
            "task_ids": list(tasks), "seeds": list(seeds), "arms": list(arms),
            "model": model, "provider_base_url": endpoint, "provider_timeout": max(30.0, solution_timeout),
            "response_model_lock": "one returned model identifier across the pilot; stop on drift",
            "immutable_snapshot_verified": False,
            "budget": {"token": token_budget, "wallclock": float(time_limit)},
            "solution_timeout": float(solution_timeout), "iterations": iterations,
            "provider_sampling": {"temperature": 0.0, "max_completion_tokens": MAX_COMPLETION_TOKENS, "seed_sent_to_provider": False},
            "seed_scope": "local data split and search sampling only; provider output is not reproducible",
            "grading_timing": "after_all_submissions_frozen",
            "wallclock_excludes_official_grading": True,
            "usd_budget_enforced": False,
            "expected_runs": len(tasks) * len(seeds) * len(arms)}
    if comparison is not None:
        plan['comparison'] = {'kind': comparison, 'search_variant': 'full',
            'control_schedules': {arm: list(GOVERNANCE_SCHEDULES[arm]) for arm in arms},
            'interpretation': 'additional resident control under equal declared budgets; not no-governance'}
    if parsed.hostname == "api.deepseek.com" or spending_ledger_path is not None:
        plan["currency_ledger_required"] = True
        plan["provider_sampling"].update(max_completion_tokens=16384, request_format="deepseek",
            thinking={"type": "enabled"}, reasoning_effort="high", wire_output_field="max_tokens",
            temperature_applied=False)
        plan["official_model_mapping"] = {"api_id": "deepseek-flash", "display_name": "DeepSeek-V4.1-Flash-1017",
            "verified_date": "2026-11-04", "source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
            "immutable_snapshot_verified": False}
    if runtime == 'm7':
        plan['runtime'] = 'm7'
    return plan


def _bind_campaign(plan, path, *, output_root=None):
    if not plan.get("currency_ledger_required"):
        return None
    if path is None:
        raise ValueError("an explicitly configured existing campaign ledger is required")
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    path = Path(path).absolute()
    SandboxRunner.validate_paths(path)
    if output_root is not None:
        output = Path(output_root).resolve()
        if path.resolve() == output or output in path.resolve().parents:
            raise ValueError("campaign ledger must stay outside replaceable pilot output_root")
    ledger = CampaignBudget(path)
    policy, snapshot = ledger.manifest_binding(), ledger.snapshot()
    parsed = urllib.parse.urlsplit(plan["provider_base_url"])
    if (plan["model"] != policy["model"] or (plan["provider_base_url"] != policy["provider_base_url"]
            and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("pilot model or endpoint differs from the campaign price policy")
    if snapshot["pending_calls"]:
        raise ValueError("campaign has unresolved provider usage; no new paid run allowed")
    allowance = min(plan["provider_sampling"]["max_completion_tokens"], plan["budget"]["token"])
    if snapshot["remaining_micro_cny"] < policy["context_tokens"] * 2 + allowance * 8:
        raise ValueError("campaign CNY budget exhausted before pilot execution")
    if (plan.get('comparison') or {}).get('kind') == 'governance-intensity':
        per_call = ledger.quote_call(plan['provider_sampling']['max_completion_tokens'])['reserved_micro_cny']
        max_calls = (plan['iterations'] + 2) * plan['expected_runs']
        upper = max_calls * per_call
        if snapshot['remaining_micro_cny'] < upper:
            raise ValueError('campaign cannot cover the comparison worst-case call bounds')
        plan['comparison'].update(conservative_max_calls=max_calls,
                                  conservative_max_currency_micro_cny=upper)
    plan["currency_campaign"] = policy
    return ledger


def preflight_pilot(official_root: str | Path, data_root: str | Path, *,
                    model: str, token_budget: int, time_limit: float = 600,
                    solution_timeout: float = 60, iterations: int = 4,
                    seeds: tuple[int, ...] = (1,), task_ids=None,
                    manifest_path: str | Path | None = None, spending_ledger_path=None,
                    runtime='legacy', comparison=None) -> dict:
    """Read-only readiness report. No provider request or agent process is started."""
    tasks = list(DEFAULT_TASKS if task_ids is None else task_ids)
    plan = _plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks,
                 spending_ledger_path=spending_ledger_path, runtime=runtime, comparison=comparison)
    missing = []
    if comparison:
        missing.append({'requirement': 'comparison_runtime_attestation',
                        'reason': 'trusted pre-import bootstrap and dependency identity are not implemented'})
        try:
            plan['source'] = _comparison_runtime_source()
            plan['comparison_dependencies'] = _comparison_dependency_identity(_comparison_dependency_roots())
        except (ValueError, OSError) as error:
            missing.append({'requirement': 'comparison_source', 'reason': str(error)})
    try:
        campaign = _bind_campaign(plan, spending_ledger_path)
        if runtime == 'm7':
            snapshot = campaign.snapshot()
            if snapshot.get('journal_schema_version') != 2 or snapshot.get('protection_breaches'):
                raise ValueError('M7 requires an enabled and intact governance journal')
            per_call = campaign.quote_call(plan['provider_sampling']['max_completion_tokens'])['reserved_micro_cny']
            required_calls = 4 if comparison == 'governance-intensity' else 2
            if snapshot['remaining_micro_cny'] < required_calls * per_call:
                raise ValueError('campaign cannot reserve required main and control call bounds')
    except (ValueError, OSError) as error:
        missing.append({"requirement": "campaign_currency_budget", "reason": str(error)})
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        missing.append({"requirement": "execution_host", "reason": "Linux x86_64 is required for the sandboxed real pilot"})
    if not shutil.which("bwrap"):
        missing.append({"requirement": "bubblewrap", "reason": "bwrap executable is unavailable"})
    if not any(item["requirement"] in {"execution_host", "bubblewrap"} for item in missing):
        from zoo.mle_bench_lite.composed_domain import SandboxRunner
        try:
            plan["candidate_runtime"] = SandboxRunner().preflight(required_modules=("numpy", "pandas", "sklearn"))
        except (RuntimeError, OSError, ValueError) as error:
            missing.append({"requirement": "candidate_runtime", "reason": str(error)})
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
        plan["profiles"] = {f"{seed}:{arm}": (
            _comparison_profile(arm, token_budget, seed, iterations,
                                max_completion_tokens=plan['provider_sampling']['max_completion_tokens'])
            if comparison else _runtime_profile(arm, token_budget, seed, iterations,
                runtime=runtime, max_completion_tokens=plan['provider_sampling']['max_completion_tokens']))
            for seed in seeds for arm in plan['arms']}
        if importlib.util.find_spec("mlebench") is not None:
            plan["official_prepared_identity"] = _official_prepared_identity(
                Path(official_root), Path(data_root), tasks, adapters)
    except Exception as error:
        missing.append({"requirement": "official_snapshot_and_prepared_data",
                        "reason": f"{type(error).__name__}: {error}"})
    return {"ready": not missing, "benchmark_execution": False,
            "missing": missing, "plan": plan, "plan_sha256": digest(plan)}


def _command(model, token_budget, solution_timeout, iterations, *,
             max_completion_tokens=MAX_COMPLETION_TOKENS, spending_ledger_path=None, runtime='legacy') -> str:
    argv = [sys.executable, "-m", "zoo.mle_bench_lite.composed_agent",
            "--workspace", "{workspace}", "--task", "{task}", "--seed", "{seed}",
            "--variant", "{arm}", "--model", model, "--token-budget", str(token_budget),
            "--solution-timeout", str(solution_timeout), "--iterations", str(iterations),
            "--max-completion-tokens", str(max_completion_tokens)]
    if runtime not in {'legacy', 'm7'}:
        raise ValueError('unknown pilot runtime')
    if runtime == 'm7':
        argv.extend(['--runtime', 'm7'])
    if spending_ledger_path is not None:
        argv.extend(["--spending-ledger", str(Path(spending_ledger_path).absolute()).replace("{", "{{").replace("}", "}}")])
    # The shared runner expands its known placeholders after shlex parsing.
    # Escape braces in the user-supplied model, which is never a shell command.
    argv[argv.index("--model") + 1] = model.replace("{", "{{").replace("}", "}}")
    return shlex.join(argv)


def _comparison_command(model, token_budget, solution_timeout, iterations, *, arm,
                        spending_ledger_path, max_completion_tokens=16384,
                        runtime_identity=None, official_root=None, pycache_root=None):
    if arm not in GOVERNANCE_SCHEDULES:
        raise ValueError('unknown governance comparison arm')
    argv = shlex.split(_command(model, token_budget, solution_timeout, iterations,
        max_completion_tokens=max_completion_tokens, spending_ledger_path=spending_ledger_path, runtime='m7'))
    argv[argv.index('--variant') + 1] = 'full'
    argv.extend(['--control-cycles', *(str(cycle) for cycle in GOVERNANCE_SCHEDULES[arm])])
    if runtime_identity is not None:
        if official_root is None or pycache_root is None:
            raise ValueError('isolated comparison requires the official source and empty cache roots')
        def escaped(value):
            return str(value).replace('{', '{{').replace('}', '}}')
        root = Path(__file__).resolve().parents[3]
        argv = [argv[0], '-I', '-S', '-B', '-X', escaped('pycache_prefix=' + str(pycache_root)),
                escaped(Path(__file__).with_name('comparison_bootstrap.py')),
                escaped(json.dumps(runtime_identity, sort_keys=True)), escaped(root / 'm0'),
                escaped(Path(official_root).resolve()), argv[2], *argv[3:]]
    return shlex.join(argv)


def _validate_agent_summary(summary: dict, *, task, seed, arm, model, token_budget,
                            profile: dict, public_data: dict, dataset: dict, iterations: int, solution_timeout: float,
                            max_completion_tokens=MAX_COMPLETION_TOKENS, currency_campaign=None,
                            currency_audit=None) -> None:
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
                         "temperature": 0.0, "max_completion_tokens": max_completion_tokens}.items():
        if settings.get(field) != value:
            raise ValueError(f"agent {field} differs from the frozen runtime settings")
    if currency_campaign is not None:
        if (summary.get("currency_campaign") != currency_campaign
                or summary.get("currency_audit") != currency_audit
                or settings.get("provider_request_format") != "deepseek"):
            raise ValueError("agent currency evidence differs from the independently audited campaign")
    # The agent freezes precise selected CSVs and split membership. The runner
    # additionally binds the complete public input tree independently.
    if summary.get("public_data_sha256") != public_data["sha256"]:
        raise ValueError("agent public data identity differs from the frozen snapshot")



def _audit_m7_result(run_dir, bundle, ledger, *, task, seed, arm, model, token_budget,
                     iterations, solution_timeout, max_completion_tokens, expected_profile,
                     expected_public_data, expected_dataset, expected_endpoint):
    """Independently reject inconsistent M7 evidence before freezing a submission."""
    from core.composition.contracts import AssemblyConfig
    from core.x1.checkpoint import RunCheckpoint
    from zoo.mle_bench_lite.m7_pilot_audit import (_record, audit_currency_receipts,
                                                    audit_physical_and_submission)
    run_dir = Path(run_dir)
    artifacts = run_dir / 'agent_artifacts'
    run_root = artifacts / 'composed'
    summary_path = artifacts / 'agent_run.json'
    if summary_path.is_symlink() or not summary_path.is_file():
        raise ValueError('M7 run summary is missing or unsafe')
    summary = json.loads(summary_path.read_text())
    _validate_agent_summary(summary, task=task, seed=seed, arm=arm, model=model,
        token_budget=token_budget, profile=expected_profile, public_data=expected_public_data,
        dataset=expected_dataset, iterations=iterations, solution_timeout=solution_timeout,
        max_completion_tokens=max_completion_tokens)
    if summary.get('runtime') != 'composed-v9-m7-governed-external' or summary.get('actual_model') != model \
            or summary.get('submission_materialized') is not True or bundle.manifest != expected_dataset:
        raise ValueError('M7 runtime, response model or dataset differs from pilot')
    checkpoint = RunCheckpoint.load(run_root / 'checkpoint.json').payload
    assembly = AssemblyConfig.from_dict(expected_profile).to_dict()
    if checkpoint['manifest']['assembly'] != assembly:
        raise ValueError('M7 checkpoint assembly differs from frozen pilot profile')
    preparation = _record(run_root / '.governed-cny/plan-prepared.json')
    manifests = preparation['manifests']
    cycles = assembly['governance']['controls']['after_main_cycles']
    expected_sessions = {'main'} | {f'control-{index:04d}' for index in range(len(cycles))}
    if set(manifests) != expected_sessions:
        raise ValueError('M7 provider session coverage differs')
    for manifest in manifests.values():
        expected = {'requested_model': model, 'base_url': expected_endpoint.rstrip('/'),
                    'max_completion_tokens': max_completion_tokens, 'timeout': float(max(30.0, solution_timeout)),
                    'request_format': 'deepseek', 'retry_policy': 'never', 'response_model_required': True,
                    'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high',
                    'temperature_applied': False, 'seed_applied': False, 'campaign': ledger.manifest_binding()}
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise ValueError('M7 provider settings differ from frozen pilot')
    from zoo.mle_bench_lite.governance_intensity import control_timing
    timing_rows = list(AppendOnlyStore(run_root / 'x1.jsonl').read())
    timing = control_timing(preparation['run']['physical_plan'], cycles, timing_rows,
                            logical_run_id=preparation['run']['logical_run_id'])
    currency = audit_currency_receipts(run_root, ledger, expected_model=model)
    physical = audit_physical_and_submission(run_root, bundle, run_dir / 'workspace/submission.csv',
                                             expected_tokens=currency['total_tokens'])
    if physical['selected_candidate_id'] != summary.get('selected_candidate_id') or \
            physical['submission_sha256'] != summary.get('submission_sha256') or \
            summary.get('token_usage', {}).get('total_tokens') != currency['total_tokens'] or \
            currency['total_tokens'] > token_budget:
        raise ValueError('M7 selected submission or usage differs from independent audit')
    certificates = [row['payload'] for row in AppendOnlyStore(run_root / 'x1.jsonl').read('replay_certificate')]
    cert = summary.get('recorded_replay')
    if not certificates or certificates[-1] != cert or not all(cert.get(key) is True for key in (
            'passed', 'snapshot_match', 'result_match', 'receipt_chain_match', 'transcript_consumed')) \
            or cert.get('mode') != 'recorded_outcomes' or cert.get('external_calls') != 0:
        raise ValueError('M7 recorded replay evidence is incomplete')
    return {'known_tokens': currency['total_tokens'], 'actual_model': model,
            'receipt_count': currency['construction']['provider_calls'],
            'currency_audit': currency, 'physical_submission_audit': physical,
            'complete': True, 'costs_complete': True, 'unresolved_calls': [],
            'actual_models': [model], 'usage': {'total_tokens': currency['total_tokens']},
            'control_timing': timing}


def _validate_provider_settings(run_dir: Path, spec: dict, *, fixture: bool):
    calls = run_dir / "agent_artifacts/token_usage_calls"
    starts = list(calls.glob("*.started.json"))
    if not starts and fixture and not spec.get("currency_ledger_required"):
        return
    if not starts:
        raise ValueError("provider invocation settings are missing")
    expected = {"requested_model": spec["model"], "base_url": spec["provider_base_url"],
                "temperature": spec["provider_sampling"]["temperature"],
                "max_completion_tokens": spec["provider_sampling"]["max_completion_tokens"],
                "timeout": spec["provider_timeout"], "token_budget": spec["budget"]["token"],
                "retry_policy": "never", "response_model_required": True}
    if spec.get("currency_ledger_required"):
        expected.update(request_format="deepseek", campaign=spec["currency_campaign"],
            thinking={"type": "enabled"}, reasoning_effort="high", wire_output_field="max_tokens",
            temperature_applied=False, immutable_snapshot_verified=False)
    for path in starts:
        manifest = json.loads(path.read_text()).get("provider", {})
        for field, value in expected.items():
            if manifest.get(field) != value:
                raise ValueError(f"actual provider {field} differs from the frozen pilot settings")


def _summary_report(spec, rows, fixture: bool, spending_ledger=None):
    comparison = (spec.get('comparison') or {}).get('kind') == 'governance-intensity'
    arms = GOVERNANCE_ARMS if comparison else ARMS
    complete = len(rows) == spec["expected_runs"] and all(row["status"] == "graded" for row in rows)
    actual_models = sorted({row["actual_model"] for row in rows if row.get("actual_model")})
    observed_models = sorted({model for row in rows for model in row.get("usage_audit", {}).get("actual_models", [])})
    same_backbone = len(observed_models) == 1
    backbone_complete = same_backbone and sum(bool(row.get("actual_model")) for row in rows) == spec["expected_runs"]
    complete = complete and backbone_complete
    pairs = []
    for task in spec["task_ids"]:
        for seed in spec["seeds"]:
            matched = [row for row in rows if row["task_id"] == task and row["seed"] == seed]
            by_arm = {row["arm"]: row for row in matched}
            pair = {"task_id": task, "seed": seed, "complete": all(
                by_arm.get(arm, {}).get("status") == "graded" for arm in arms)}
            if comparison and (len(matched) != len(arms) or set(by_arm) != set(arms)):
                pair.update(complete=False, error='paired arm coverage differs')
                complete = False
            if pair["complete"] and not same_backbone:
                pair.update(complete=False, error="actual provider model differs across pilot runs")
            if pair["complete"]:
                baseline, full = (by_arm[arms[0]], by_arm[arms[1]])
                if comparison and any(row.get('official_result', {}).get('valid_submission') is not True or
                        row.get('usage_audit', {}).get('control_timing', {}).get('all_on_schedule') is not True or
                        row.get('usage_audit', {}).get('complete') is not True or
                        row.get('usage_audit', {}).get('costs_complete') is not True or
                        row.get('usage_audit', {}).get('unresolved_calls')
                        for row in (baseline, full)):
                    pair.update(complete=False, error='invalid submission or control timing differs from plan')
                    complete = False
                if baseline["dataset_identity"] != full["dataset_identity"]:
                    pair.update(complete=False, error="paired dataset identities differ")
                    complete = False
                elif comparison and baseline['metric_direction'] != full['metric_direction']:
                    pair.update(complete=False, error='paired metric directions differ')
                    complete = False
                elif pair['complete']:
                    scores = [row["official_result"]["score"] for row in (baseline, full)]
                    if comparison and any(type(score) not in (int, float) or not math.isfinite(score) for score in scores):
                        pair.update(complete=False, error='paired official scores are unavailable')
                        complete = False
                        pairs.append(pair)
                        continue
                    if comparison:
                        pair.update(metric_direction=baseline['metric_direction'], one_control_score=scores[0],
                            two_controls_score=scores[1], score_delta_two_minus_one=(scores[1] - scores[0])
                            if all(score is not None for score in scores) else None,
                            token_delta_two_minus_one=full['actual_costs']['token'] - baseline['actual_costs']['token'],
                            wallclock_delta_two_minus_one=full['actual_costs']['wallclock'] - baseline['actual_costs']['wallclock'])
                    else:
                        pair.update(metric_direction=baseline["metric_direction"],
                                    baseline_score=scores[0], full_score=scores[1],
                                    score_delta_full_minus_baseline=(scores[1] - scores[0])
                                        if all(score is not None for score in scores) else None,
                                    token_delta_full_minus_baseline=full["actual_costs"]["token"] - baseline["actual_costs"]["token"],
                                    wallclock_delta_full_minus_baseline=full["actual_costs"]["wallclock"] - baseline["actual_costs"]["wallclock"])
            pairs.append(pair)
    totals = {}
    for arm in arms:
        arm_rows = [row for row in rows if row["arm"] == arm]
        graded = [row for row in arm_rows if row["status"] == "graded"]
        costs = [row.get("actual_costs", {}) for row in arm_rows]
        totals[arm] = {"planned_runs": len(spec["task_ids"]) * len(spec["seeds"]),
                      "graded_runs": len(graded), "failed_runs": (sum(row['status'] == 'failed' for row in arm_rows)
                                                                     if comparison else len(arm_rows) - len(graded)),
                      "valid_submissions": sum(row["official_result"]["valid_submission"] for row in graded),
                      "known_tokens": sum(row.get("usage_audit", {}).get("known_tokens", 0) for row in arm_rows),
                      "unknown_token_runs": sum(not row.get("usage_audit", {}).get("costs_complete", False) for row in arm_rows),
                      "incomplete_identity_runs": sum(not row.get("usage_audit", {}).get("complete", False) for row in arm_rows),
                      "known_wallclock": sum(cost.get("wallclock", 0) for cost in costs)}
        if comparison:
            totals[arm]['ungraded_runs'] = sum(row['status'] == 'ungraded' for row in arm_rows)
    currency = None
    if spending_ledger is not None:
        try:
            currency = spending_ledger.snapshot()
            currency["complete"] = not currency["pending_calls"]
        except (ValueError, OSError) as error:
            currency = {"complete": False, "invoice_verified": False, "error_type": type(error).__name__}
        complete = complete and currency["complete"]
    return {"schema_version": 1, "benchmark": "mle_bench_lite", "scope": "task_subset_pilot",
            "subset_only": True, "formal_benchmark_complete": False,
            "official_benchmark_measurement": not fixture and any(row["status"] == "graded" for row in rows),
            "evidence_kind": "protocol_fixture" if fixture else "official_task_subset",
            "spec_sha256": digest(spec), "spec": spec, "pilot_complete": complete,
            "expected_runs": spec["expected_runs"], "runs": rows, "pairs": pairs, "arms": totals,
            "requested_model": spec["model"], "actual_models": actual_models,
            "observed_response_models": observed_models, "backbone_evidence_complete": backbone_complete,
            "response_identifier_evidence_complete": backbone_complete, "immutable_snapshot_verified": False,
            "currency_campaign": currency,
            "statistical_significance_claimed": False, "host_parity_claimed": False,
            "failure_count": sum(row["status"] != "graded" for row in rows)}


def _comparison_grading_ready(spec, rows, output_root, spending_ledger):
    """Require every planned comparison submission to be frozen and intact."""
    arms = tuple(spec['arms'])
    if arms != GOVERNANCE_ARMS:
        raise ValueError('comparison arm identities differ')
    expected = {(task, seed, arm) for task in spec['task_ids'] for seed in spec['seeds'] for arm in arms}
    identities = [(row['task_id'], row['seed'], row['arm']) for row in rows]
    if len(rows) != spec['expected_runs'] or len(rows) != len(expected) or set(identities) != expected or \
            len(set(identities)) != len(identities) or any(row['status'] != 'frozen' for row in rows):
        raise ValueError('not every comparison slot is frozen')
    root = Path(output_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('comparison output root is unsafe')
    if spending_ledger is None:
        raise ValueError('comparison requires the original campaign ledger')
    snapshot = spending_ledger.snapshot()
    if snapshot.get('journal_schema_version') != 2 or snapshot.get('pending_calls') or \
            snapshot.get('protection_breaches') or snapshot.get('reserved_micro_cny') or \
            snapshot.get('protected_micro_cny'):
        raise ValueError('comparison campaign has unresolved or protected currency')
    for row in rows:
        task, seed, arm = row['task_id'], row['seed'], row['arm']
        if type(task) is not str or not task or Path(task).name != task or task in {'.', '..'} or \
                type(seed) is not int or seed < 0:
            raise ValueError('comparison slot identity is unsafe')
        audit = row.get('usage_audit', {})
        if audit.get('complete') is not True or audit.get('costs_complete') is not True or \
                audit.get('unresolved_calls') or audit.get('control_timing', {}).get('all_on_schedule') is not True:
            raise ValueError('comparison control timing or accounting is incomplete')
        parts = (task, f'seed_{seed}', arm, 'frozen', 'submission.csv')
        path = root
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise ValueError('comparison submission path is unsafe')
        if not path.is_file() or file_digest(path) != row['submission_sha256']:
            raise ValueError('comparison frozen submission differs')
    for task in spec['task_ids']:
        for seed in spec['seeds']:
            pair = [row for row in rows if row['task_id'] == task and row['seed'] == seed]
            if pair[0]['dataset_identity'] != pair[1]['dataset_identity'] or \
                    pair[0]['metric_direction'] != pair[1]['metric_direction']:
                raise ValueError('comparison paired dataset or metric differs')


def _comparison_reaudit(spec, rows, output_root, spending_ledger, keys):
    """Recheck original run artifacts and authority immediately before scoring."""
    from zoo.mle_bench_lite.public_train import PublicTrainBundle
    for row in rows:
        task, seed, arm = row['task_id'], row['seed'], row['arm']
        run_dir = Path(output_root) / task / f'seed_{seed}' / arm
        workspace = run_dir / 'workspace'
        if public_snapshot(workspace / 'data') != spec['public_data'][task]:
            raise ValueError('comparison public input changed before scoring')
        bundle = PublicTrainBundle(workspace / 'data', run_dir / 'agent_artifacts/public_inputs',
                                   task, seed, anonymization_key=keys[(task, seed)])
        checked = _audit_m7_result(run_dir, bundle, spending_ledger, task=task, seed=seed,
            arm='full', model=spec['model'], token_budget=spec['budget']['token'],
            iterations=spec['iterations'], solution_timeout=spec['solution_timeout'],
            max_completion_tokens=spec['provider_sampling']['max_completion_tokens'],
            expected_profile=spec['profiles'][f'{seed}:{arm}'], expected_public_data=spec['public_data'][task],
            expected_dataset=spec['datasets'][f'{task}:{seed}'], expected_endpoint=spec['provider_base_url'])
        prior = row['usage_audit']
        if any(checked[key] != prior[key] for key in ('known_tokens', 'actual_model', 'receipt_count',
                'physical_submission_audit', 'control_timing')) or \
                any(checked['currency_audit'][key] != prior['currency_audit'][key] for key in
                    ('total_tokens', 'settled_micro_cny', 'model', 'invoice_verified', 'construction')) or \
                checked['physical_submission_audit']['submission_sha256'] != row['submission_sha256']:
            raise ValueError('comparison run evidence changed before scoring')


@contextmanager
def _comparison_campaign_lock(ledger_path):
    """Hold the existing cooperative campaign lock for a complete comparison."""
    if ledger_path is None:
        raise ValueError('comparison requires the original campaign ledger')
    ledger = Path(ledger_path).absolute()
    parent = ledger.parent
    _protected_host_path(parent)
    if ledger.is_symlink() or not ledger.is_file() or parent.is_symlink() or not parent.is_dir() or \
            parent.stat().st_uid != os.getuid() or stat.S_IMODE(parent.stat().st_mode) != 0o700:
        raise ValueError('comparison requires a private existing campaign directory and ledger')
    fd = os.open(parent / 'authorized-pilot.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('comparison campaign lock must be a private ordinary file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('comparison campaign lock is already held') from error
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _run_pilot_impl(official_root: str | Path, data_root: str | Path, output_root: str | Path, *,
              model: str, token_budget: int, time_limit: float = 600,
              solution_timeout: float = 60, iterations: int = 4,
              seeds: tuple[int, ...] = (1,), task_ids=None,
              manifest_path: str | Path | None = None, grader_factory: Callable | None = None,
              _fixture_agent_command: str | None = None, spending_ledger_path=None, runtime='legacy',
              comparison=None) -> dict:
    """Run fixed paired variants. Test injections cannot emit production evidence."""
    tasks = list(DEFAULT_TASKS if task_ids is None else task_ids)
    spec = _plan(model, token_budget, time_limit, solution_timeout, iterations, seeds, tasks,
                 spending_ledger_path=spending_ledger_path, runtime=runtime, comparison=comparison)
    if comparison and grader_factory is not None:
        endpoint = urllib.parse.urlsplit(spec['provider_base_url'])
        if (endpoint.hostname not in {'127.0.0.1', '::1'} or
                os.environ.get('OPENAI_API_KEY') != 'fixture-only' or
                spending_ledger_path is None or Path(spending_ledger_path).name != 'fixture-campaign.db'):
            raise ValueError('comparison fixtures require loopback, fixture-only credentials and a fixture-campaign.db ledger')
    spending_ledger = _bind_campaign(spec, spending_ledger_path, output_root=output_root)
    if comparison:
        if grader_factory is None:
            spec['source'] = _comparison_runtime_source()
            spec['comparison_dependencies'] = _comparison_dependency_identity(_comparison_dependency_roots())
        else:
            spec['comparison']['source_scope'] = 'synthetic-fixture-unverified'
    if _fixture_agent_command is not None and grader_factory is None:
        raise ValueError("custom agent commands are reserved for labelled protocol fixtures")
    if grader_factory is None:
        for protected_root in (official_root, data_root, output_root):
            _protected_host_path(Path(protected_root))
        readiness = preflight_pilot(official_root, data_root, model=model,
            token_budget=token_budget, time_limit=time_limit, solution_timeout=solution_timeout,
            iterations=iterations, seeds=seeds, task_ids=tasks, manifest_path=manifest_path,
            spending_ledger_path=spending_ledger_path, runtime=runtime, comparison=comparison)
        if not readiness["ready"]:
            raise ValueError("pilot preflight failed: " + json.dumps(readiness["missing"]))
        if comparison and (readiness['plan'].get('source') != spec['source'] or
                           readiness['plan'].get('comparison_dependencies') != spec['comparison_dependencies']):
            raise ValueError('comparison source changed during preflight')
    official_root, data_root, output_root = map(lambda p: Path(p).resolve(),
                                               (official_root, data_root, output_root))
    adapters = preflight(official_root, data_root, tasks,
                         require_official_package=grader_factory is None, manifest_path=manifest_path)
    if grader_factory is None:
        spec["official_prepared_identity"] = _official_prepared_identity(official_root, data_root, tasks, adapters)
    spec["public_data"] = {task: public_snapshot(data_root / task / "prepared/public") for task in tasks}
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise FileExistsError("pilot output_root must be empty; evidence is not overwritten")
    # One trusted key per paired dataset, never copied into a candidate mount.
    key_paths = {(task, seed): output_root / "private" / task / f"seed_{seed}.key"
                 for task in tasks for seed in seeds}
    keys = {pair: load_anonymization_key(path, create=True) for pair, path in key_paths.items()}
    spec["datasets"] = {f"{task}:{seed}": _dataset_manifest(
        data_root / task / "prepared/public", task, seed, anonymization_key=keys[(task, seed)])
        for task in tasks for seed in seeds}
    spec["official_manifest_sha256"] = file_digest(adapters[tasks[0]].manifest_path)
    spec["profiles"] = {f"{seed}:{arm}": (
        _comparison_profile(arm, token_budget, seed, iterations,
                            max_completion_tokens=spec['provider_sampling']['max_completion_tokens'])
        if comparison else _runtime_profile(arm, token_budget, seed, iterations, runtime=runtime,
            max_completion_tokens=spec['provider_sampling']['max_completion_tokens']))
        for seed in seeds for arm in spec['arms']}
    spec["profile_sha256"] = {key: digest(value) for key, value in spec["profiles"].items()}
    spec["execution_host"] = {"system": platform.system(), "machine": platform.machine(),
                              "cpu_count": os.cpu_count(), "python": platform.python_version()}
    _atomic_json(output_root / "pilot_spec.json", {"spec": spec, "sha256": digest(spec)})
    command = _fixture_agent_command or _command(model, token_budget, solution_timeout, iterations,
        max_completion_tokens=spec["provider_sampling"]["max_completion_tokens"],
        spending_ledger_path=spending_ledger_path, runtime=runtime)
    rows = []
    observed_backbones = set()
    stop_reason = None
    for task in tasks:
        for seed in seeds:
            # Deterministically alternate which variant runs first to avoid one
            # always receiving the warm machine, while keeping paired seeds.
            arms = tuple(spec['arms'])
            order = arms if (tasks.index(task) + seeds.index(seed)) % 2 == 0 else tuple(reversed(arms))
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
                currency_before = None
                execution_started = False
                try:
                    if stop_reason is not None:
                        row["blocked_before_execution"] = True
                        raise ValueError(stop_reason)
                    if comparison and grader_factory is None:
                        try:
                            if not _comparison_frozen_runtime(spec):
                                raise ValueError('comparison source identity changed')
                        except Exception as error:
                            stop_reason = 'comparison source verification failed; remaining paid runs are blocked'
                            row['blocked_before_execution'] = True
                            raise ValueError(stop_reason) from error
                    if spending_ledger is not None:
                        currency_before = spending_ledger.snapshot()
                        if currency_before["pending_calls"]:
                            stop_reason = "campaign has unresolved usage; remaining paid runs are blocked"
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
                    execution_started = True
                    cache_root = None
                    if comparison and grader_factory is None:
                        cache_root = run_dir / 'comparison-empty-pycache'
                        cache_root.mkdir(mode=0o700)
                    arm_command = (_comparison_command(model, token_budget, solution_timeout, iterations, arm=arm,
                        spending_ledger_path=spending_ledger_path,
                        max_completion_tokens=spec['provider_sampling']['max_completion_tokens'],
                        runtime_identity=spec.get('comparison_dependencies') if grader_factory is None else None,
                        official_root=official_root if grader_factory is None else None, pycache_root=cache_root)
                        if comparison and _fixture_agent_command is None else command)
                    execution = _execute_agent(arm_command, workspace, task, seed, arm, time_limit, run_dir, {
                        "MLE_OFFICIAL_ROOT": str(official_root), "MLE_DATA_ROOT": str(data_root),
                        "MLE_MANIFEST_PATH": str(adapter.manifest_path.resolve()),
                        "MLE_AUDIT_PATH": str(run_dir / "audit.jsonl"),
                        "MLE_TOKEN_BUDGET": str(token_budget),
                        "MLE_ANONYMIZATION_KEY_PATH": str(key_paths[(task, seed)]),
                        "MLE_CNY_LEDGER_PATH": str(spending_ledger.path) if spending_ledger is not None else "",
                        "MLE_PILOT_SPEC_SHA256": digest(spec),
                        "MLE_PILOT_PUBLIC_DATA_SHA256": spec["public_data"][task]["sha256"],
                        **({'PYTHONPATH': os.pathsep.join((str(Path(__file__).resolve().parents[3] / 'm0'), str(official_root))),
                            'MLE_COMPARISON_SOURCE_COMMIT': spec['source']['commit'],
                            'MLE_COMPARISON_ENV_ONLY': '1', 'OPENAI_API_BASE': spec['provider_base_url']}
                           if comparison and grader_factory is None else {}),
                        **({'MLE_FIXTURE_ENV_ONLY': '1', 'OPENAI_API_BASE': spec['provider_base_url'],
                            'PYTHONPATH': os.pathsep.join((str(Path(__file__).resolve().parents[3] / 'm0'), str(official_root)))}
                           if comparison and grader_factory is not None else {}),
                    })
                    row.update(execution)
                    if comparison and grader_factory is None and not _comparison_frozen_runtime(spec):
                        stop_reason = 'comparison source changed during execution; remaining paid runs are blocked'
                        raise ValueError(stop_reason)
                    if runtime == 'm7':
                        # Any missing or inconsistent evidence stops all later paid slots.
                        row['usage_audit'] = {'complete': False, 'costs_complete': False,
                            'known_tokens': 0, 'receipt_count': 0, 'started_calls': 0,
                            'completed_calls': 0, 'unresolved_calls': ['unverified'], 'errors': [],
                            'actual_models': [], 'usage': None}
                        try:
                            if execution['timed_out'] or execution['agent_returncode'] != 0:
                                raise ValueError('M7 agent timed out or exited unsuccessfully')
                            from zoo.mle_bench_lite.public_train import PublicTrainBundle
                            bundle = PublicTrainBundle(workspace / 'data', run_dir / 'agent_artifacts/public_inputs',
                                task, seed, anonymization_key=keys[(task, seed)])
                            checked = _audit_m7_result(run_dir, bundle, spending_ledger, task=task, seed=seed,
                                arm='full' if comparison else arm, model=model, token_budget=token_budget, iterations=iterations,
                                solution_timeout=solution_timeout,
                                max_completion_tokens=spec['provider_sampling']['max_completion_tokens'],
                                expected_profile=spec['profiles'][f'{seed}:{arm}'],
                                expected_public_data=spec['public_data'][task],
                                expected_dataset=spec['datasets'][f'{task}:{seed}'],
                                expected_endpoint=spec['provider_base_url'])
                            if comparison and not checked['control_timing']['all_on_schedule']:
                                raise ValueError('control was drained before its frozen comparison schedule')
                        except Exception:
                            stop_reason = 'M7 execution or independent evidence is incomplete; remaining paid runs are blocked'
                            raise
                        row['usage_audit'] = checked
                        observed_backbones.update(checked['actual_models'])
                        row['actual_costs']['token'] = checked['known_tokens']
                        row.update(actual_model=checked['actual_model'], token_usage=checked['usage'])
                        summary = json.loads((run_dir / 'agent_artifacts/agent_run.json').read_text())
                    else:
                        # An unfinished second request cannot disappear behind the
                        # first request's valid receipt. Keep known and unknown costs separate.
                        usage_audit = audit_usage(run_dir / "agent_artifacts/token_usage",
                                                  allow_fixture_receipts=grader_factory is not None,
                                                  spending_ledger=spending_ledger)
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
                            iterations=iterations, solution_timeout=solution_timeout,
                            max_completion_tokens=spec["provider_sampling"]["max_completion_tokens"],
                            currency_campaign=spec.get("currency_campaign"), currency_audit=usage_audit.get("currency_audit"))
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
                    if runtime == 'm7' and execution_started:
                        stop_reason = stop_reason or 'M7 execution or independent evidence failed; remaining paid runs are blocked'
                        row.setdefault('usage_audit', {'complete': False, 'costs_complete': False,
                            'known_tokens': 0, 'receipt_count': 0, 'started_calls': 0,
                            'completed_calls': 0, 'unresolved_calls': ['unverified'], 'errors': [],
                            'actual_models': [], 'usage': None})
                if spending_ledger is not None and currency_before is not None:
                    try:
                        currency_after = spending_ledger.snapshot()
                        row['currency_settled_upper_bound_micro_cny'] = (
                            currency_after['settled_upper_bound_micro_cny'] - currency_before['settled_upper_bound_micro_cny'])
                        previous_ids = {item["call_id"] for item in currency_before["operations"]}
                        row["currency_call_ids"] = [item["call_id"] for item in currency_after["operations"]
                                                     if item["call_id"] not in previous_ids]
                        if currency_after["pending_calls"]:
                            stop_reason = "campaign has unresolved usage; remaining paid runs are blocked"
                    except (ValueError, OSError):
                        row.update(status="failed", currency_integrity_error=True)
                        stop_reason = "campaign integrity failed; remaining paid runs are blocked"
                _atomic_json(run_dir / "run.json", row)
                rows.append(row)
                _atomic_json(output_root / "pilot.json", _summary_report(spec, rows, grader_factory is not None, spending_ledger))
    # Comparison mode reads no hidden score unless every planned submission is
    # frozen, on schedule and rechecked before the first grader invocation.
    grading_block = None
    if comparison:
        try:
            _comparison_grading_ready(spec, rows, output_root, spending_ledger)
            _comparison_reaudit(spec, rows, output_root, spending_ledger, keys)
            if grader_factory is None and not _comparison_frozen_runtime(spec):
                raise ValueError('comparison source changed before scoring')
            if grader_factory is None and _official_prepared_identity(
                    official_root, data_root, tasks, adapters) != spec['official_prepared_identity']:
                raise ValueError('official prepared identity changed before comparison scoring')
            _comparison_grading_ready(spec, rows, output_root, spending_ledger)
        except Exception as error:
            grading_block = f'{type(error).__name__}: comparison pre-grading verification failed'
    for row in rows:
        if row["status"] != "frozen":
            continue
        task, seed, arm = row["task_id"], row["seed"], row["arm"]
        run_dir = output_root / task / f"seed_{seed}" / arm
        if grading_block is not None:
            row.update(status='ungraded', grading_blocked=grading_block)
            _atomic_json(run_dir / 'run.json', row)
            continue
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
    report = _summary_report(spec, rows, grader_factory is not None, spending_ledger)
    _atomic_json(output_root / "pilot.json", report)
    return report


def run_pilot(official_root: str | Path, data_root: str | Path, output_root: str | Path, *,
              model: str, token_budget: int, time_limit: float = 600,
              solution_timeout: float = 60, iterations: int = 4,
              seeds: tuple[int, ...] = (1,), task_ids=None,
              manifest_path: str | Path | None = None, grader_factory: Callable | None = None,
              _fixture_agent_command: str | None = None, spending_ledger_path=None, runtime='legacy',
              comparison=None) -> dict:
    options = dict(model=model, token_budget=token_budget, time_limit=time_limit,
        solution_timeout=solution_timeout, iterations=iterations, seeds=seeds, task_ids=task_ids,
        manifest_path=manifest_path, grader_factory=grader_factory, _fixture_agent_command=_fixture_agent_command,
        spending_ledger_path=spending_ledger_path, runtime=runtime, comparison=comparison)
    if comparison == 'governance-intensity':
        if grader_factory is not None:
            if spending_ledger_path is not None:
                raise ValueError('comparison fixtures cannot use a caller-supplied campaign ledger')
            from zoo.mle_bench_lite.cny_budget import CampaignBudget
            parent = Path(output_root).absolute().parent
            fixture_dir = Path(tempfile.mkdtemp(prefix='mori-comparison-fixture-', dir=parent))
            fixture_ledger = CampaignBudget.create(fixture_dir / 'fixture-campaign.db')
            fixture_ledger.enable_governance(expected_policy_sha256=fixture_ledger.manifest_binding()['policy_sha256'],
                                             expected_head=fixture_ledger.snapshot()['journal_head'])
            spending_ledger_path = fixture_ledger.path
            options['spending_ledger_path'] = spending_ledger_path
        with _comparison_campaign_lock(spending_ledger_path):
            return _run_pilot_impl(official_root, data_root, output_root, **options)
    return _run_pilot_impl(official_root, data_root, output_root, **options)


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
    parser.add_argument("--runtime", choices=("legacy", "m7"), default="legacy")
    parser.add_argument("--comparison", choices=("governance-intensity",))
    parser.add_argument("--spending-ledger", type=Path)
    args = parser.parse_args(argv)
    values = dict(model=args.model, token_budget=args.token_budget, time_limit=args.time_limit,
                  solution_timeout=args.solution_timeout, iterations=args.iterations,
                  seeds=tuple(args.seeds), task_ids=args.tasks, manifest_path=args.manifest_path,
                  spending_ledger_path=args.spending_ledger or os.environ.get("MLE_CNY_LEDGER_PATH") or None,
                  runtime=args.runtime, comparison=args.comparison)
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
