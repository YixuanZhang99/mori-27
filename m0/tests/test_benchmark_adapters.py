"""ZOO adapter protocol fixtures and measured-run comparison guards.

These tests do not execute MLE-Bench and are not benchmark performance evidence.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tasks.adapter import Workspace
from core.tasks.benchmark import (BenchmarkRunRecord, SelectionCandidate,
                                  SelectionContract, SelectionReceipt, compare_same_budget)
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite.adapter import REVISION, TASK_LIST_SHA256, MLEBenchLiteAdapter

TASK = "aerial-cactus-identification"


def official_fixture(root, descending=True):
    official = root / "official"
    data = root / "data"
    task_dir = official / "mlebench/competitions" / TASK
    task_dir.mkdir(parents=True)
    (official / "experiments/splits").mkdir(parents=True)
    packaged = Path(__file__).resolve().parents[1] / "zoo/mle_bench_lite/assets/low.txt"
    (official / "experiments/splits/low.txt").write_bytes(packaged.read_bytes())
    (task_dir / "config.yaml").write_text("id: fixture\n")
    (task_dir / "grade.py").write_text("# protected grader fixture\n")
    (task_dir / "checksums.yaml").write_text("files: {}\n")
    (task_dir / "description.md").write_text("Train a model and write submission.csv.\n")
    scores = ["0.9", "0.5", "0.1"] if descending else ["0.1", "0.5", "0.9"]
    (task_dir / "leaderboard.csv").write_text(
        "team,score\n" + "".join(f"t{i},{score}\n" for i, score in enumerate(scores)))
    sample = data / TASK / "prepared/public/sample_submission.csv"
    sample.parent.mkdir(parents=True)
    sample.write_text("id,prediction\n1,0\n")
    (sample.parent / "train.csv").write_text("id,feature,target\n1,0.5,0\n")
    (sample.parent / "test.csv").write_text("id,feature\n1,0.5\n")
    files = {}
    for name in ("config.yaml", "grade.py", "checksums.yaml", "leaderboard.csv", "description.md"):
        path = task_dir / name
        rel = f"mlebench/competitions/{TASK}/{name}"
        import hashlib
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"revision": REVISION, "files": files}))
    return official, data, manifest


def test_locked_official_lite_split_and_workspace_visibility(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    adapter = MLEBenchLiteAdapter(TASK, official, data, manifest)
    assert len(adapter.task_ids()) == 22
    assert adapter.provenance().task_list_sha256 == TASK_LIST_SHA256
    assert adapter.eval_contract().metric_direction == "maximize"
    evidence = AppendOnlyStore(tmp_path / "evidence.jsonl")
    workspace = tmp_path / "agent-workspace"
    adapter.setup(Workspace(workspace, evidence))
    assert {p.name for p in workspace.iterdir()} == {
        "description.md", "sample_submission.csv", "task.json", ".git"}
    assert not list(workspace.rglob("grade.py"))
    assert not list(workspace.rglob("leaderboard.csv"))
    assert len(list(evidence.read("benchmark_workspace_setup"))) == 1


def test_production_workspace_exposes_public_data_but_no_private_grading_files(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    private = data / TASK / "prepared/private/answers.csv"
    private.parent.mkdir(parents=True)
    private.write_text("id,answer\n1,secret\n")
    adapter = MLEBenchLiteAdapter(TASK, official, data, manifest)
    evidence = AppendOnlyStore(tmp_path / "production-evidence.jsonl")
    workspace = tmp_path / "production-workspace"
    adapter.setup(Workspace(workspace, evidence), include_data=True)
    assert (workspace / "data/train.csv").is_file()
    assert (workspace / "data/test.csv").is_file()
    assert (workspace / "data/sample_submission.csv").is_file()
    assert not list(workspace.rglob("answers.csv"))
    assert not list(workspace.rglob("grade.py"))
    assert not list(workspace.rglob("leaderboard.csv"))
    setup = list(evidence.read("benchmark_workspace_setup"))[-1]["payload"]
    assert "data/" in setup["visible_files"]


def test_metric_direction_tamper_refusal_and_report_redaction(tmp_path):
    official, data, manifest = official_fixture(tmp_path, descending=False)
    adapter = MLEBenchLiteAdapter(TASK, official, data, manifest)
    assert adapter.eval_contract().metric_direction == "minimize"
    report = {"competition_id": TASK, "valid_submission": True, "score": 0.123,
              "above_median": True, "any_medal": True, "gold_medal": False,
              "silver_medal": True, "bronze_medal": False}
    dev = adapter.public_report(report, "dev")
    admission = adapter.public_report(report, "admission")
    audit = adapter.public_report(report, "audit")
    assert dev == {"competition_id": TASK, "valid_submission": True}
    assert "score" not in admission and "audit/score" not in admission
    assert admission["admission/above_median"] is True
    assert audit["audit/score"] == 0.123 and audit["audit/any_medal"] is True
    (official / f"mlebench/competitions/{TASK}/grade.py").write_text("# tampered\n")
    with pytest.raises(ValueError, match="modified"):
        adapter.verify_protected()


def run(task, seed, arm, medal=True, valid=True, budget=None, measured=True):
    selection = SelectionContract("single_run", "fixture-final-v1", "test")
    candidate_id = f"{arm}:{task}:{seed}:final"
    receipt = SelectionReceipt(selection, (SelectionCandidate(
        candidate_id, f"external://{arm}/{task}/{seed}/grading.json"),), candidate_id)
    return BenchmarkRunRecord(
        benchmark="mle_bench_lite", task_list_sha256=TASK_LIST_SHA256,
        task_id=task, seed=seed, arm=arm, backbone="same-model",
        budget=budget or {"wallclock": 24, "eval_count": 10, "token": 40},
        actual_costs={"wallclock": 20, "eval_count": 8, "usd": 2, "token": 30},
        valid_submission=valid, any_medal=medal, above_median=medal,
        evidence_refs=(f"external://{arm}/{task}/{seed}/grading.json",), measured=measured,
        selection=selection, selection_receipt=receipt)


def test_same_budget_comparison_requires_complete_measured_paired_runs(tmp_path):
    tasks = {"task-a", "task-b"}
    host = [run(task, seed, "host", medal=(seed != 2), valid=(seed != 3))
            for task in tasks for seed in (1, 2, 3)]
    governed = [run(task, seed, "governed", medal=(seed != 3))
                for task in tasks for seed in (1, 2, 3)]
    store = AppendOnlyStore(tmp_path / "comparison.jsonl")
    report = compare_same_budget(host, governed, noise_floor=0.1,
                                 expected_task_ids=tasks, store=store)
    assert report.paired_runs == 6 and report.task_count == 2
    assert report.host_medal_rate == pytest.approx(2 / 3)
    assert report.governed_medal_rate == pytest.approx(2 / 3)
    assert report.medal_delta == 0 and report.verdict == "within_noise_floor"
    assert report.host_valid_rate == pytest.approx(2 / 3)
    assert report.actual_cost_totals["governed"] == {
        "eval_count": 48, "token": 180, "usd": 12, "wallclock": 120}
    assert len(list(store.read("same_budget_comparison"))) == 1

    unfair = [replace(record, budget={**record.budget, "wallclock": 48})
              for record in governed]
    with pytest.raises(ValueError, match="budget mismatch"):
        compare_same_budget(host, unfair, 0.1, expected_task_ids=tasks)
    with pytest.raises(ValueError, match="task-seed sets"):
        compare_same_budget(host, governed[:-1], 0.1)
    unmeasured = list(governed)
    unmeasured[0] = replace(unmeasured[0], measured=False)
    with pytest.raises(ValueError, match="externally measured"):
        compare_same_budget(host, unmeasured, 0.1)
    overspent = list(governed)
    overspent[0] = replace(overspent[0], actual_costs={
        **overspent[0].actual_costs, "wallclock": 25})
    with pytest.raises(ValueError, match="exceeds the declared budget"):
        compare_same_budget(host, overspent, 0.1)


def test_official_grading_entry_keeps_raw_report_in_audit_and_creates_measured_record(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    adapter = MLEBenchLiteAdapter(TASK, official, data, manifest)
    workspace = tmp_path / "grading-workspace"
    adapter.setup(Workspace(workspace))
    (workspace / "submission.csv").write_text("id,prediction\n1,1\n")
    audit = AppendOnlyStore(tmp_path / "audit.jsonl")
    raw = {"competition_id": TASK, "valid_submission": True, "score": 0.75,
           "above_median": True, "any_medal": False, "gold_medal": False,
           "silver_medal": False, "bronze_medal": False}
    calls = []

    def grader(path):
        calls.append(path)
        return raw

    public = adapter.grade_submission(Workspace(workspace), "dev", audit, grader=grader)
    assert public == {"competition_id": TASK, "valid_submission": True}
    assert calls == [workspace / "submission.csv"]
    records = list(audit.read("official_grading_report"))
    assert len(records) == 1 and records[0]["payload"]["report"]["score"] == 0.75
    measured = adapter.measured_run_record(
        raw, seed=1, arm="governed", backbone="model", budget={"wallclock": 24},
        actual_costs={"wallclock": 20}, evidence_refs=("audit://grading-report-1",))
    measured.validate_measured()
    assert measured.measured is True and measured.any_medal is False
