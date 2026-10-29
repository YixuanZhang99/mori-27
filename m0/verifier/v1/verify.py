#!/usr/bin/env python3
"""Independent offline verifier v1. Run from any directory: python3 verifier/v1/verify.py"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.extensions import H2MonitorExtension, NoveltyGateExtension
from core.loop import Framework, LoopConfig
from core.profiles import load_profile
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM, toy_evaluator


def static_checks() -> dict:
    forbidden_imports = {"openai", "requests", "urllib", "socket", "time", "datetime"}
    findings = []
    files = list((ROOT / "core/policy").rglob("*.py"))
    files += list((ROOT / "core/budget").rglob("*.py"))
    files += [ROOT / "core/eval/gate.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_imports:
                        findings.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in forbidden_imports:
                    findings.append(f"{path.name}: from {node.module}")
                if node.module == "core.llm":
                    findings.append(f"{path.name}: execution LLM imported into sync path")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"now", "utcnow", "urlopen", "request"}:
                    findings.append(f"{path.name}: forbidden call {node.func.attr}")
    gate_text = (ROOT / "core/eval/gate.py").read_text(encoding="utf-8")
    if "combined_score" in gate_text:
        findings.append("gate reads aggregate score")
    store = AppendOnlyStore(ROOT / "verifier" / "runs" / ".probe.jsonl")
    if hasattr(store, "update") or hasattr(store, "delete"):
        findings.append("evidence store exposes mutation")
    return {"pass": not findings, "findings": findings,
            "files_scanned": len(files)}


def main() -> int:
    checks: dict[str, bool] = {}
    values: dict = {}

    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
                          text=True, capture_output=True)
    checks["pytest"] = proc.returncode == 0
    values["pytest_tail"] = (proc.stdout + proc.stderr).strip().splitlines()[-3:]

    with tempfile.TemporaryDirectory() as td:
        fw = Framework(MockLLM(), toy_evaluator, LoopConfig(max_generations=20),
                       str(Path(td) / "run"))
        result = fw.evolve("verifier toy")
        inspection = fw.inspect()
        replay = fw.replay()
        checks["toy_self_attestation"] = (
            result["best_score"] == 1.0 and bool(result["baseline_scores"])
            and all(s < 1.0 for s in result["baseline_scores"])
            and result["ledger"]["spent"]["control"] > 0)
        checks["funnels_monotone"] = all(
            f.proposed >= f.applicable >= f.runnable >= f.admitted
            for f in result["funnels"])
        checks["inspect_receipt_coverage"] = inspection["accepted_receipt_coverage"]
        checks["deterministic_replay"] = all(
            replay[k] == result[k] for k in
            ("best_prompt", "best_score", "main_scores", "baseline_scores"))
        values["best_score"] = result["best_score"]
        values["baseline_scores"] = result["baseline_scores"]
        values["control_spent"] = result["ledger"]["spent"]["control"]
        values["receipts"] = inspection["receipt_count"]

    static = static_checks()
    checks["static_architecture_guards"] = static["pass"]
    values["static"] = static

    try:
        gepa = load_profile("gepa_reflective")
        funsearch = load_profile("funsearch_island")
        checks["profiles_compile"] = (
            gepa["operators"]["improve"] == "llm_reflective"
            and funsearch["operators"]["improve"] == "llm_evolve_block")
    except Exception as exc:
        checks["profiles_compile"] = False
        values["profile_error"] = str(exc)

    try:
        novelty = NoveltyGateExtension(0.9)
        proposal = type("P", (), {"patch_text": "abcdef"})()
        pool = [{"candidate_id": "old", "prompt": "abcdef"}]
        h2 = H2MonitorExtension(window=2)
        h2.after_parent_selection(pool[0], 1)
        alarm = h2.after_parent_selection(pool[0], 2)
        checks["extensions_execute"] = (
            novelty.admission_veto(proposal, None, pool) is not None
            and alarm["kind"] == "h2_collapse_alarm")
    except Exception as exc:
        checks["extensions_execute"] = False
        values["extension_error"] = str(exc)

    required_docs = [ROOT / "README.md", ROOT / "verifier/README.md",
                     ROOT.parent / "autoresearch-fw/VISION.md",
                     ROOT.parent / "autoresearch-fw/RUBRIC.md",
                     ROOT.parent / "autoresearch-fw/开发指南-v1.md"]
    checks["required_docs"] = all(p.exists() for p in required_docs)
    values["missing_docs"] = [str(p) for p in required_docs if not p.exists()]

    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v1/verify.py", "version": "v1",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values}
    with (ROOT / "verifier/runs/v1.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
