"""M7 worktree execution and X2 control-plane behavior (offline, real git/processes)."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import (Candidate, EvalRequest, EvalStatus, ExecutorSpec,
                           GitWorktree, GitWorktreeExecutor)
from core.hitl import HITLController
from core.tasks.adapter import EvalContract, FidelityLevel
from core.x1.store import AppendOnlyStore


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def execution_fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "user.name", "Offline Tests")
    (repo / "solution.py").write_text("VALUE = 0\n")
    (repo / "eval.py").write_text('''import json, pathlib, sys, time
root = pathlib.Path(__file__).parent
candidate = json.loads((root / "candidate.json").read_text())
mode = candidate["id"]
if mode == "timeout":
    time.sleep(5)
elif mode == "crash":
    raise RuntimeError("environment failed")
elif mode == "tamper":
    (root / "eval.py").write_text("# candidate tampering\\n")
if mode != "missing":
    (root / "submission.csv").write_text("id,prediction\\n1,1\\n")
    (root / "metrics.json").write_text(json.dumps({"dev/score": 0.75}))
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    contract = EvalContract(
        metric_direction="maximize", eval_cmd=f"{sys.executable} {{cwd}}/eval.py",
        fidelity_levels=(FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        required_outputs=("submission.csv",), protected_paths=("eval.py",))
    store = AppendOnlyStore(tmp_path / "executor-evidence.jsonl")

    def builder(candidate, root):
        (root / "candidate.json").write_text(json.dumps({"id": candidate.id}))
        (root / "solution.py").write_text(f"VALUE = {candidate.created_cycle}\n")

    executor = GitWorktreeExecutor(contract, builder, store)
    workspace = GitWorktree(repo, tmp_path / "worktrees")
    return repo, workspace, executor, store


def execute(executor, workspace, candidate_id, time_limit=10, hypothesis="h",
            spec_hypothesis=None):
    candidate = Candidate(candidate_id, hypothesis=hypothesis, operator="improve")
    return asyncio.run(executor.execute(
        ExecutorSpec(hypothesis=hypothesis if spec_hypothesis is None else spec_hypothesis),
        candidate, workspace, EvalRequest("dev", time_limit=time_limit, seed_set=[7])))


def test_executor_success_commits_artifact_and_checks_protection(execution_fixture):
    repo, workspace, executor, store = execution_fixture
    evidence = execute(executor, workspace, "ok")
    assert evidence.executor_status == "scored"
    assert evidence.eval_result.status is EvalStatus.OK
    assert evidence.eval_result.metrics == {"dev/score": 0.75}
    assert evidence.branch_ref != git(repo, "rev-parse", "HEAD")
    git(repo, "cat-file", "-e", f"{evidence.branch_ref}^{{commit}}")
    assert git(repo, "show", f"{evidence.branch_ref}:submission.csv").startswith("id,prediction")
    assert not list(workspace.run_root.iterdir())
    checks = [r["payload"]["stage"] for r in store.read("executor_protected_check")]
    assert checks == ["startup", "pre_merge"]
    records = list(store.read("executor_evidence"))
    assert len(records) == 1 and records[0]["payload"]["evidence"]["eval_result"]["status"] == "ok"


def test_executor_encodes_timeout_crash_missing_output_and_tampering(execution_fixture):
    _, workspace, executor, store = execution_fixture
    timeout = execute(executor, workspace, "timeout", time_limit=1)
    crash = execute(executor, workspace, "crash")
    missing = execute(executor, workspace, "missing")
    tamper = execute(executor, workspace, "tamper")
    assert (timeout.executor_status, timeout.eval_result.status) == ("timeout", EvalStatus.TIMEOUT)
    assert (crash.executor_status, crash.eval_result.status) == (
        "failed_to_run", EvalStatus.FAILED_TO_RUN)
    assert "environment failed" in crash.result_text
    assert (missing.executor_status, missing.eval_result.status) == ("invalid", EvalStatus.INVALID)
    assert "submission.csv" in missing.result_text
    assert (tamper.executor_status, tamper.eval_result.status) == ("invalid", EvalStatus.INVALID)
    assert "protected paths modified" in tamper.result_text
    assert len(list(store.read("executor_evidence"))) == 4


def test_executor_rejects_frozen_hypothesis_mismatch_and_base_tamper(execution_fixture):
    repo, workspace, executor, store = execution_fixture
    mismatch = execute(executor, workspace, "ok", hypothesis="candidate",
                       spec_hypothesis="h")
    assert mismatch.executor_status == "failed_to_run"
    assert mismatch.branch_ref is None
    assert "frozen ExecutorSpec" in mismatch.result_text
    assert execute(executor, workspace, "ok", hypothesis="candidate").executor_status == "scored"
    (repo / "eval.py").write_text("# base tampering\n")
    base_tamper = execute(executor, workspace, "ok", hypothesis="candidate")
    assert base_tamper.executor_status == "failed_to_run"
    assert "protected paths modified" in base_tamper.result_text
    assert len(list(store.read("executor_evidence"))) == 3


def test_review_approval_is_bound_single_use_and_pause_resume_survives_restore(
        execution_fixture, tmp_path):
    _, workspace, base_executor, _ = execution_fixture
    store = AppendOnlyStore(tmp_path / "hitl.jsonl")
    control = HITLController(store, mode="review")
    executor = GitWorktreeExecutor(base_executor.contract, base_executor.builder,
                                   base_executor.evidence_store, hitl=control)
    candidate = Candidate("review-ok", hypothesis="h", operator="improve")
    request = EvalRequest("dev", time_limit=10, seed_set=[7])
    spec = ExecutorSpec(hypothesis="h")

    first = asyncio.run(executor.execute(spec, candidate, workspace, request))
    assert first.executor_status == "skipped" and first.branch_ref is None
    pending = control.pending()
    assert len(pending) == 1
    restored = HITLController(store, mode="review")
    restored.pause("operator", "maintenance")
    denied = asyncio.run(executor.execute(spec, candidate, workspace, request))
    assert denied.executor_status == "skipped" and "paused" in denied.result_text
    restored.resume("operator", "maintenance complete")
    restored.approve(pending[0]["request_id"], "reviewer", "safe offline fixture")
    second = asyncio.run(executor.execute(spec, candidate, workspace, request))
    assert second.executor_status == "scored" and second.attempt == 3
    third = asyncio.run(executor.execute(spec, candidate, workspace, request))
    assert third.executor_status == "skipped"
    assert len(list(store.read("hitl_consumed"))) == 1
    assert len(list(store.read("hitl_pause"))) == 1
    assert len(list(store.read("hitl_resume"))) == 1


def test_review_approval_cannot_authorize_different_payload(tmp_path):
    store = AppendOnlyStore(tmp_path / "binding-hitl.jsonl")
    control = HITLController(store, mode="review")
    pending = control.authorize("admission.merge", {"candidate": "c1"})
    control.approve(pending.request_id, "reviewer")
    altered = control.authorize("admission.merge", {"candidate": "c2"})
    assert not altered.allowed and altered.verdict == "pending"
    assert control.authorize("admission.merge", {"candidate": "c1"}).allowed
    with pytest.raises(ValueError, match="no longer pending"):
        control.reject(pending.request_id, "reviewer")
    with pytest.raises(ValueError, match="auto and review"):
        HITLController(store, mode="collaborative")


def test_auto_mode_still_honors_pause_and_appends_decisions(tmp_path):
    store = AppendOnlyStore(tmp_path / "auto-hitl.jsonl")
    control = HITLController(store, mode="auto")
    decision = control.authorize("admission.merge", {"candidate": "c1"})
    assert decision.allowed and decision.verdict == "approved"
    control.pause("operator", "stop")
    assert not control.authorize("admission.merge", {"candidate": "c1"}).allowed
    resumed = HITLController(store, mode="auto")
    assert resumed.paused
    resumed.resume("operator", "continue")
    assert resumed.authorize("admission.merge", {"candidate": "c1"}).allowed
    assert len(list(store.read("hitl_decision"))) == 2
