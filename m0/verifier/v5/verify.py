#!/usr/bin/env python3
"""Verifier v5: v4 plus standalone CI axioms and M2/M4 extensions."""
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

from core.eval.gate import AdmissionGate
from core.eval.types import EvalResult, ItemResult
from core.frontier.pareto import ParetoArchive, PerformanceCostPoint
from core.operator.ops import (EVOLVE_END, EVOLVE_START, crossover,
                               crossover_with_debug_fallback, debug)
from core.operator.types import CrossoverContract, OperatorSpec
from core.x1.store import AppendOnlyStore


def block(body):
    return f"HEAD\n{EVOLVE_START}\n{body}\n{EVOLVE_END}\nTAIL"


def parent(cid):
    return {"candidate_id": cid, "prompt": block("old")}


def check_static(_root):
    run = subprocess.run([sys.executable, "ci/check_axioms.py"], cwd=ROOT,
                         text=True, capture_output=True)
    payload = json.loads(run.stdout)
    passed = run.returncode == 0 and payload["exit_code"] == 0 and all(payload["checks"].values())
    return passed, {"exit": run.returncode, "checks": payload["checks"],
                    "public_api": payload["values"].get("public_instance_api"),
                    "cycles": payload["values"].get("dependency_cycles")}


def check_ci_wiring(_root):
    path = ROOT / ".github/workflows/axioms.yml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    required = ["push:", "pull_request:", "python3 ci/check_axioms.py",
                "python3 -m pytest -q", "python3 verifier/v5/verify.py"]
    missing = [command for command in required if command not in text]
    return not missing, {"path": str(path.relative_to(ROOT)), "missing": missing,
                         "hosted_execution_claimed": False}


def check_debug_and_crossover(_root):
    repair = OperatorSpec("dbg", "debug", "v1", representation="evolve_block")
    repaired = debug(lambda p: "fixed", repair, "p", block("bug"),
                     {"item_id": "i", "error": "AssertionError", "source": "env_fact"})
    try:
        debug(lambda p: "x", repair, "p", block("bug"),
              {"item_id": "i", "error": "looks bad", "source": "llm_judgment"})
        judgment_refused = False
    except ValueError:
        judgment_refused = True

    spec = OperatorSpec("xo", "crossover", "v2", representation="evolve_block")
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return "composed"

    first = crossover(llm, spec, CrossoverContract(), (parent("a"), parent("b")), 17)
    second = crossover(llm, spec, CrossoverContract(), (parent("b"), parent("a")), 17)
    incompatible_calls = []
    incompatible = parent("b")
    incompatible["prompt"] = incompatible["prompt"].replace("HEAD", "OTHER")
    try:
        crossover(lambda p: incompatible_calls.append(p) or "x", spec,
                  CrossoverContract(), (parent("a"), incompatible), 17)
        incompatible_refused = False
    except ValueError:
        incompatible_refused = True
    passed = (repaired.patch_text == block("fixed") and judgment_refused
              and prompts[0] == prompts[1]
              and first.parent_ids == second.parent_ids
              and first.crossover_meta == second.crossover_meta
              and first.patch_text == block("composed")
              and incompatible_refused and not incompatible_calls)
    return passed, {"debug_structure_preserved": repaired.patch_text == block("fixed"),
                    "llm_judgment_refused": judgment_refused,
                    "parent_order_replayable": first.parent_ids == second.parent_ids,
                    "parent_order": first.parent_ids,
                    "incompatible_refused_before_llm": incompatible_refused and not incompatible_calls}


def check_fallback(_root):
    spec = OperatorSpec("xo", "crossover", "v2", representation="evolve_block")
    repair = OperatorSpec("dbg", "debug", "v3", representation="evolve_block")
    stages = []

    def llm(prompt):
        stage = "debug" if prompt.startswith("[debug") else "crossover"
        stages.append(stage)
        return "repaired" if stage == "debug" else "composed"

    executed = []

    def run_child(proposal):
        executed.append(proposal.proposal_id)
        return {"item_id": "i", "error": "TimeoutExpired", "source": "env_fact"}

    result = crossover_with_debug_fallback(
        llm, spec, repair, CrossoverContract(), (parent("a"), parent("b")), 3, run_child)
    invalid_executed = []

    def empty_then_fix(prompt):
        return "fixed" if prompt.startswith("[debug") else ""

    apply_repair = crossover_with_debug_fallback(
        empty_then_fix, spec, repair, CrossoverContract(), (parent("a"), parent("b")), 3,
        lambda proposal: invalid_executed.append(proposal.proposal_id))
    passed = (stages == ["crossover", "debug"] and len(executed) == 1
              and result.crossover_meta["debug_fallback_of"] == executed[0]
              and len(result.crossover_meta["crossover_parent_ids"]) == 2
              and not invalid_executed and apply_repair.apply_result == "ok")
    return passed, {"stages": stages, "runtime_children_executed": len(executed),
                    "invalid_children_executed": len(invalid_executed),
                    "apply_fallback_result": apply_repair.apply_result}


def point(cid, performance, token, usd):
    return PerformanceCostPoint(cid, performance, {"token": token, "usd": usd},
                                f"receipt-{cid}", "anchor-v1")


def check_pareto(root):
    store = AppendOnlyStore(root / "pareto.jsonl")
    archive = ParetoArchive(store)
    for p in (point("balanced", .8, 100, 1), point("cheap", .7, 80, .8),
              point("dominated", .6, 120, 1.2), point("fast", .9, 150, .5)):
        archive.offer(p)
    before = set(archive.entries)
    try:
        archive.offer(PerformanceCostPoint("mixed", 1, {"token": 1}, "r", "v1"))
        mixed_refused = False
    except ValueError:
        mixed_refused = True
    frontier = [p.candidate_id for p in archive.frontier()]
    passed = (frontier == ["fast", "balanced", "cheap"]
              and archive.dominated_by("dominated") == ["balanced", "cheap"]
              and len(archive.entries) == 4 and set(archive.entries) == before
              and mixed_refused and len(list(store.read("pareto_offer"))) == 4)
    return passed, {"frontier": frontier, "retained": sorted(archive.entries),
                    "dominated_by": archive.dominated_by("dominated"),
                    "mixed_unit_offer_atomic": mixed_refused and set(archive.entries) == before}


def check_cost_not_gate(root):
    gate = AdmissionGate(AppendOnlyStore(root / "cost-gate.jsonl"))
    old = EvalResult("old", "s0", [ItemResult("i", 0)], combined_score=.5)
    low = EvalResult("low", "s1", [ItemResult("i", 1)], combined_score=.1,
                     private={"costs": {"token": 1, "usd": .01}})
    high = EvalResult("high", "s2", [ItemResult("i", 1)], combined_score=999,
                      private={"costs": {"token": 10**9, "usd": 10**6}})
    a, b = gate.judge(low, old), gate.judge(high, old)
    passed = (a.verdict.kind == b.verdict.kind == "ACCEPT"
              and a.verdict.rationale_ref == b.verdict.rationale_ref)
    return passed, {"low_cost_verdict": a.verdict.kind,
                    "high_cost_verdict": b.verdict.kind,
                    "rationale": a.verdict.rationale_ref}


def main() -> int:
    checks, values = {}, {}
    v4 = subprocess.run([sys.executable, "verifier/v4/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v4_complete"] = v4.returncode == 0
    values["v4_exit"] = v4.returncode
    if v4.returncode:
        values["v4_stderr"] = v4.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("standalone_static_axioms", check_static),
                         ("ci_workflow_wiring", check_ci_wiring),
                         ("debug_crossover_deterministic_contract", check_debug_and_crossover),
                         ("crossover_debug_fallback_behavior", check_fallback),
                         ("performance_cost_pareto_archive", check_pareto),
                         ("cost_independent_m9_admission", check_cost_not_gate)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v5/verify.py", "version": "v5",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values}
    with (ROOT / "verifier/runs/v5.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
