#!/usr/bin/env python3
"""Verifier v7: v6 plus grading evidence, real M7 execution and X2 control."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.executor import (Candidate, EvalRequest, EvalStatus, ExecutorSpec,
                           GitWorktree, GitWorktreeExecutor)
from core.hitl import HITLController
from core.tasks.adapter import EvalContract, FidelityLevel, Workspace
from core.x1.store import AppendOnlyStore
from verifier.v6.verify import TASK, fixture
from zoo.mle_bench_lite.adapter import MLEBenchLiteAdapter


def check_grading(root):
    official, data, manifest = fixture(root)
    adapter = MLEBenchLiteAdapter(TASK, official, data, manifest)
    workspace = root / "grading"
    adapter.setup(Workspace(workspace))
    (workspace / "submission.csv").write_text("id,prediction\n1,1\n")
    raw = {"competition_id": TASK, "valid_submission": True, "score": .75,
           "above_median": True, "any_medal": False, "gold_medal": False,
           "silver_medal": False, "bronze_medal": False}
    calls = []
    audit = AppendOnlyStore(root / "grading-audit.jsonl")
    public = adapter.grade_submission(Workspace(workspace), "dev", audit,
                                     grader=lambda path: calls.append(path) or raw)
    records = list(audit.read("official_grading_report"))
    measured = adapter.measured_run_record(
        raw, 1, "governed", "model", {"wallclock": 24}, {"wallclock": 20},
        ("audit://grading-report-1",))
    measured.validate_measured()
    passed = (calls == [workspace / "submission.csv"]
              and public == {"competition_id": TASK, "valid_submission": True}
              and len(records) == 1 and records[0]["payload"]["report"]["score"] == .75
              and measured.measured and not measured.any_medal)
    return passed, {"dev_fields": sorted(public), "raw_audit_reports": len(records),
                    "measured_record": measured.measured,
                    "protocol_fixture_not_external_run": True}


def git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=repo, text=True,
                          capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def executor_fixture(root, hitl=None):
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "verifier@example.invalid")
    git(repo, "config", "user.name", "Verifier")
    (repo / "solution.py").write_text("VALUE = 0\n")
    (repo / "eval.py").write_text('''import json, pathlib, time
root = pathlib.Path(__file__).parent
mode = json.loads((root / "candidate.json").read_text())["id"]
if mode == "timeout": time.sleep(5)
if mode == "crash": raise RuntimeError("fixture crash")
if mode == "tamper": (root / "eval.py").write_text("# tampered\\n")
if mode != "missing":
    (root / "submission.csv").write_text("id,prediction\\n1,1\\n")
    (root / "metrics.json").write_text(json.dumps({"dev/score": 0.75}))
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    contract = EvalContract(
        "maximize", f"{sys.executable} {{cwd}}/eval.py",
        (FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        ("submission.csv",), ("eval.py",))
    store = AppendOnlyStore(root / "executor.jsonl")
    executor = GitWorktreeExecutor(
        contract, lambda cand, path: (path / "candidate.json").write_text(
            json.dumps({"id": cand.id})), store, hitl=hitl)
    return repo, GitWorktree(repo, root / "worktrees"), executor, store


def run(executor, workspace, candidate, limit=10):
    return asyncio.run(executor.execute(
        ExecutorSpec(hypothesis="h"), Candidate(candidate, hypothesis="h"),
        workspace, EvalRequest("dev", time_limit=limit, seed_set=[7])))


def check_executor(root):
    repo, workspace, executor, store = executor_fixture(root)
    success = run(executor, workspace, "ok")
    timeout = run(executor, workspace, "timeout", 1)
    crash = run(executor, workspace, "crash")
    missing = run(executor, workspace, "missing")
    tamper = run(executor, workspace, "tamper")
    artifact = git(repo, "show", f"{success.branch_ref}:submission.csv")
    stages = [r["payload"]["stage"] for r in store.read("executor_protected_check")]
    statuses = {name: evidence.executor_status for name, evidence in (
        ("success", success), ("timeout", timeout), ("crash", crash),
        ("missing", missing), ("tamper", tamper))}
    passed = (success.eval_result.status is EvalStatus.OK
              and success.eval_result.metrics == {"dev/score": .75}
              and artifact.startswith("id,prediction")
              and timeout.eval_result.status is EvalStatus.TIMEOUT
              and crash.eval_result.status is EvalStatus.FAILED_TO_RUN
              and missing.eval_result.status is EvalStatus.INVALID
              and tamper.eval_result.status is EvalStatus.INVALID
              and "protected paths modified" in tamper.result_text
              and stages == ["startup", "pre_merge", "startup", "startup",
                             "startup", "startup", "pre_merge"]
              and len(list(store.read("executor_evidence"))) == 5
              and not list(workspace.run_root.iterdir()))
    return passed, {"statuses": statuses, "protected_stages": stages,
                    "artifact_resolvable": True, "evidence_records": 5,
                    "worktrees_remaining": len(list(workspace.run_root.iterdir()))}


def check_hitl(root):
    store = AppendOnlyStore(root / "hitl.jsonl")
    control = HITLController(store, "review")
    pending = control.authorize("admission.merge", {"candidate": "c1"})
    control.approve(pending.request_id, "reviewer", "checked")
    altered = control.authorize("admission.merge", {"candidate": "c2"})
    restored = HITLController(store, "review")
    allowed = restored.authorize("admission.merge", {"candidate": "c1"})
    reused = restored.authorize("admission.merge", {"candidate": "c1"})
    restored.pause("operator", "stop")
    denied = HITLController(store, "auto").authorize("executor.execute", {"candidate": "c1"})
    restored.resume("operator", "continue")
    auto = HITLController(store, "auto").authorize("executor.execute", {"candidate": "c1"})
    passed = (not pending.allowed and pending.verdict == "pending"
              and not altered.allowed and allowed.allowed and not reused.allowed
              and not denied.allowed and auto.allowed
              and len(list(store.read("hitl_consumed"))) == 1
              and len(list(store.read("hitl_pause"))) == 1
              and len(list(store.read("hitl_resume"))) == 1)
    return passed, {"initial": pending.verdict, "altered_payload_allowed": altered.allowed,
                    "approval_single_use": allowed.allowed and not reused.allowed,
                    "paused_auto_allowed": denied.allowed,
                    "resumed_auto_allowed": auto.allowed}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_executor_hitl.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2000:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    commands = ["python3 -m pytest -q", "python3 verifier/v5/verify.py",
                "python3 verifier/v6/verify.py", "python3 verifier/v7/verify.py"]
    passed = all(command in text for command in commands)
    return passed, {"commands_present": commands if passed else
                    [command for command in commands if command in text],
                    "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    v6 = subprocess.run([sys.executable, "verifier/v6/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v6_complete"] = v6.returncode == 0
    values["v6_exit"] = v6.returncode
    if v6.returncode:
        values["v6_stderr"] = v6.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("official_grading_evidence", check_grading),
                         ("m7_git_worktree_execution", check_executor),
                         ("x2_review_control", check_hitl),
                         ("m7_x2_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v7/verify.py", "version": "v7",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v7.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
