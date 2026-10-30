#!/usr/bin/env python3
"""Check pinned MLE source and CPU dependencies with synthetic data only.

No model, Kaggle credentials or real task dataset is used. Official registry,
preparer imports and the complete official CSV grading path are executed for
the three supported tasks; the resulting values are not benchmark results.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TASKS = ("spooky-author-identification", "leaf-classification",
         "nomad2018-predict-transparent-conductors")
PACKAGES = ("dacite", "numpy", "openai", "PyYAML", "appdirs", "pandas",
            "scikit-learn", "kaggle", "py7zr", "diskcache", "tqdm", "tenacity")


def _disable_network(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("network access is forbidden in the synthetic runtime smoke")


def verify_runtime(official_root: Path) -> dict:
    official_root = official_root.resolve()
    from zoo.mle_bench_lite.adapter import MLEBenchLiteAdapter, REVISION

    head = subprocess.check_output(
        ["git", "-C", str(official_root), "rev-parse", "HEAD"], text=True).strip()
    if head != REVISION:
        raise ValueError("official checkout HEAD differs from the locked MLE revision")
    subprocess.run(["git", "-C", str(official_root), "diff", "--quiet", "HEAD", "--"], check=True)
    spec = importlib.util.find_spec("mlebench")
    if spec is None or spec.origin is None or Path(spec.origin).resolve() != official_root / "mlebench/__init__.py":
        raise ValueError("mlebench is not imported from the exact official checkout")
    lock = (ROOT / "scripts/requirements-mle-pilot.lock").read_text()
    versions = {}
    for package in PACKAGES:
        pin = re.search(r"^" + re.escape(package) + r"==([^\s;\\]+)", lock, flags=re.I | re.M)
        installed = importlib.metadata.version(package)
        if pin is None or installed != pin.group(1):
            raise ValueError(f"installed {package} does not match the CPU environment lock")
        versions[package] = installed

    # The CLI/grading imports open a local disk cache. Keep it in this disposable
    # directory, and prove those imports require neither secrets nor network.
    sys.addaudithook(_disable_network)
    tasks = []
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="mori27-mle-runtime-") as temporary:
        work = Path(temporary)
        try:
            os.chdir(work)
            import numpy as np
            import pandas as pd
            from mlebench.grade import grade_csv
            from mlebench.registry import Registry
            importlib.import_module("mlebench.cli")
            registry = Registry(work / "synthetic-data")
            for task_id in TASKS:
                adapter = MLEBenchLiteAdapter(task_id, official_root, registry.get_data_dir())
                competition = registry.get_competition(task_id)
                if competition.id != task_id or not callable(competition.prepare_fn):
                    raise ValueError("official registry did not load the requested task")
                module = importlib.import_module(f"mlebench.competitions.{task_id}.grade")
                source = Path(module.__file__).resolve()
                if source != official_root / f"mlebench/competitions/{task_id}/grade.py":
                    raise ValueError("task grader was loaded outside the pinned source")
                if hasattr(module, "CLASSES"):
                    classes = list(module.CLASSES)
                    count = len(classes)
                    answers = pd.DataFrame(np.eye(count), columns=classes)
                    answers.insert(0, "id", [f"synthetic-{index}" for index in range(count)])
                    worse = answers.copy()
                    worse[classes] = 1.0 / count
                else:
                    answers = pd.DataFrame({"id": [1, 2, 3],
                        "formation_energy_ev_natom": [0.1, 0.5, 1.0],
                        "bandgap_energy_ev": [0.0, 1.5, 2.0]})
                    worse = answers.copy()
                    worse["formation_energy_ev_natom"] += 1
                    worse["bandgap_energy_ev"] += 1
                competition.answers.parent.mkdir(parents=True)
                competition.sample_submission.parent.mkdir(parents=True)
                answers.to_csv(competition.answers, index=False)
                worse.to_csv(competition.sample_submission, index=False)
                perfect_path = work / f"{task_id}-synthetic-perfect.csv"
                worse_path = work / f"{task_id}-synthetic-worse.csv"
                answers.to_csv(perfect_path, index=False)
                worse.to_csv(worse_path, index=False)
                perfect = grade_csv(perfect_path, competition).to_dict()
                comparison = grade_csv(worse_path, competition).to_dict()
                for result in (perfect, comparison):
                    if (result["competition_id"] != task_id
                            or result["valid_submission"] is not True
                            or type(result["score"]) not in (int, float)
                            or not math.isfinite(result["score"])):
                        raise ValueError("official synthetic grading failed")
                if not perfect["score"] < comparison["score"]:
                    raise ValueError("official synthetic score ordering is incorrect")
                if adapter.eval_contract().metric_direction != "minimize":
                    raise ValueError("unexpected official task metric direction")
                adapter.verify_protected()
                tasks.append({"task_id": task_id, "protected_snapshot_verified": True,
                              "registry_and_preparer_loaded": True,
                              "official_csv_grading_with_synthetic_data_passed": True})
        finally:
            os.chdir(original_cwd)
    return {"schema_version": 1, "passed": True,
            "evidence_kind": "official_code_synthetic_data_smoke",
            "official_revision": head, "python": platform.python_version(),
            "system": platform.system(), "machine": platform.machine(),
            "package_versions": versions,
            "requirements_sha256": hashlib.sha256(lock.encode()).hexdigest(), "tasks": tasks,
            "network_access_disabled": True, "external_provider_called": False,
            "kaggle_data_downloaded": False, "external_benchmark_executed": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = verify_runtime(args.official_root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
            output.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
