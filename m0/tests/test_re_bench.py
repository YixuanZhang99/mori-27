"""RE-Bench protocol fixtures and real campaign-process tests.

Fixtures validate adapter, scoring, timeout and evidence mechanics only. They are
not an official RE-Bench execution and are never benchmark performance evidence.
"""
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tasks.adapter import Workspace
from core.tasks.benchmark import (ScoreRunRecord, SelectionCandidate,
                                  SelectionContract, SelectionReceipt,
                                  compare_scores_same_budget)
from core.x1.store import AppendOnlyStore
from zoo.re_bench.adapter import (REVISION, TASK_IDS, TASK_LIST_SHA256,
                                  REBenchAdapter, sha256)
from zoo.re_bench.runner import preflight, run_campaign

TASK = "ai_rd_small_scaling_law"
ASSETS = Path(__file__).resolve().parents[1] / "zoo/re_bench/assets"


def official_fixture(root: Path, score_on_usage_limits=True):
    """Create a synthetic locked snapshot, without protected official solutions."""
    official = root / "official"
    official.mkdir()
    packaged_suite = ASSETS / "suite_manifest.yaml"
    (official / "suite_manifest.yaml").write_bytes(packaged_suite.read_bytes())
    task_dir = official / TASK
    task_dir.mkdir()
    (task_dir / "README.md").write_text("Synthetic public task description.\n")
    (task_dir / "manifest.yaml").write_text(yaml.safe_dump({
        "tasks": {"main": {"scoring": {
            "visible_to_agent": False,
            "score_on_usage_limits": score_on_usage_limits}}}}, sort_keys=False))
    (task_dir / f"{TASK}.py").write_text(
        "class TaskFamily:\n"
        "    @staticmethod\n"
        "    def get_tasks():\n"
        "        return {'main': {'fixture': True}}\n"
        "    @staticmethod\n"
        "    def aggregate_scores(task, score_log):\n"
        "        assert task == {'fixture': True}\n"
        "        return sum(float(row['score']) for row in score_log) / len(score_log)\n")
    (task_dir / "build_steps.json").write_text("[]\n")
    (task_dir / "requirements.txt").write_text("")
    files = {"suite_manifest.yaml": TASK_LIST_SHA256}
    for path in sorted(task_dir.iterdir()):
        files[f"{TASK}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = root / "snapshot.json"
    manifest.write_text(json.dumps({"revision": REVISION, "files": files}))
    return official, manifest


def score_agent(root: Path, mode="score") -> Path:
    path = root / f"agent_{mode}.py"
    if mode == "score":
        body = """import json, os
from pathlib import Path
score = 0.75 if os.environ['RE_ARM'] == 'governed' else 0.5
Path(os.environ['RE_SCORE_LOG']).write_text(json.dumps([
    {'score': score, 'seed': int(os.environ['RE_SEED'])}]))
"""
    elif mode == "missing":
        body = "print('real agent exited without a score log')\n"
    elif mode == "timeout":
        body = """import json, os, subprocess, sys, time
from pathlib import Path
Path(os.environ['RE_SCORE_LOG']).write_text(json.dumps([{'score': 0.5}]))
marker = Path.cwd() / 'orphan-survived'
child = "import time; from pathlib import Path; time.sleep(0.8); Path(" + repr(str(marker)) + ").write_text('bad')"
subprocess.Popen([sys.executable, '-c', child])
time.sleep(30)
"""
    else:
        raise ValueError(mode)
    path.write_text(body)
    return path


def numeric_run(task, seed, arm, score=1.0, direction="maximize", budget=None,
                actual=None, measured=True, timed_out=False):
    selection = SelectionContract("single_run", "fixture-official-v1", "not_applicable")
    candidate_id = f"{arm}:{task}:{seed}:final"
    receipt = SelectionReceipt(selection, (SelectionCandidate(
        candidate_id, f"audit://{arm}/{task}/{seed}"),), candidate_id)
    return ScoreRunRecord(
        benchmark="numeric-fixture", task_list_sha256="locked", task_id=task,
        seed=seed, arm=arm, backbone="same-model",
        budget=budget or {"wallclock": 10, "token": 100},
        actual_costs=actual or {"wallclock": 8, "token": 80}, score=score,
        metric_direction=direction, timed_out=timed_out,
        evidence_refs=(f"audit://{arm}/{task}/{seed}",), measured=measured,
        selection=selection, selection_receipt=receipt)


def test_locked_suite_workspace_visibility_provenance_and_tamper_refusal(tmp_path):
    official, manifest = official_fixture(tmp_path)
    suite = yaml.safe_load((ASSETS / "suite_manifest.yaml").read_text())
    locked = json.loads((ASSETS / "snapshot_manifest.json").read_text())
    assert tuple(suite["task_families"]) == TASK_IDS
    assert len(TASK_IDS) == 7 and len(locked["files"]) == 36
    assert sha256(ASSETS / "suite_manifest.yaml") == TASK_LIST_SHA256
    adapter = REBenchAdapter(TASK, official, manifest)
    assert adapter.task_ids() == list(TASK_IDS)
    assert adapter.provenance().revision == REVISION
    assert adapter.provenance().notes["maintenance"].startswith("upstream marks")
    assert adapter.eval_contract().visibility == "audit"
    assert adapter.initial_artifact().sha256 == sha256(official / TASK / "README.md")
    evidence = AppendOnlyStore(tmp_path / "setup.jsonl")
    workspace = tmp_path / "workspace"
    adapter.setup(Workspace(workspace, evidence))
    assert {path.name for path in workspace.iterdir()} == {
        "description.md", "task.json", ".git"}
    assert not list(workspace.rglob("score_log.json"))
    assert not list(workspace.rglob("official_solution.zip"))
    setup = list(evidence.read("benchmark_workspace_setup"))[-1]["payload"]
    assert setup["solution_files_exposed"] is False
    (official / TASK / f"{TASK}.py").write_text("# tampered\n")
    with pytest.raises(ValueError, match="modified"):
        adapter.verify_protected()


def test_official_aggregate_audit_only_report_and_measured_record(tmp_path):
    official, manifest = official_fixture(tmp_path)
    adapter = REBenchAdapter(TASK, official, manifest)
    score_log = tmp_path / "score_log.json"
    score_log.write_text(json.dumps([{"score": 0.25}, {"score": 0.75}]))
    audit = AppendOnlyStore(tmp_path / "audit.jsonl")
    report = adapter.grade_score_log(score_log, audit)
    assert report["score"] == 0.5 and report["official_aggregate_scores"] is True
    assert adapter.public_report(report, "dev") == {
        "task_id": TASK, "scoring_recorded": True}
    assert adapter.public_report(report, "audit")["audit/score"] == 0.5
    with pytest.raises(ValueError, match="visibility"):
        adapter.public_report(report, "admission")
    stored = list(audit.read("official_scoring_report"))
    assert len(stored) == 1 and stored[0]["payload"]["score"] == 0.5
    measured = adapter.measured_run_record(
        report, 3, "governed", "same-model", {"wallclock": 10},
        {"wallclock": 9}, ("audit://official-scoring-report",))
    measured.validate_measured()
    assert measured.measured is True and measured.score == 0.5


@pytest.mark.parametrize("contents", ["[]", "[1]", "{}"])
def test_empty_or_malformed_score_logs_are_rejected(tmp_path, contents):
    official, manifest = official_fixture(tmp_path)
    adapter = REBenchAdapter(TASK, official, manifest)
    path = tmp_path / "bad.json"
    path.write_text(contents)
    with pytest.raises(ValueError, match="non-empty object list"):
        adapter.grade_score_log(path, AppendOnlyStore(tmp_path / "audit.jsonl"))


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), True, "0.5"])
def test_non_numeric_or_nonfinite_official_scores_fail_after_audit(tmp_path, bad_score):
    official, manifest = official_fixture(tmp_path)
    adapter = REBenchAdapter(TASK, official, manifest)
    path = tmp_path / "score.json"
    path.write_text('[{"score": 1}]')
    audit = AppendOnlyStore(tmp_path / "audit.jsonl")
    with pytest.raises(ValueError, match="not finite"):
        adapter.grade_score_log(path, audit, aggregator=lambda _log: bad_score)
    report = list(audit.read("official_scoring_report"))[-1]["payload"]
    assert report["score"] is None and report["invalid_score"] == str(bad_score)


def test_numeric_maximize_comparison_and_append_only_evidence(tmp_path):
    tasks = {"task-a", "task-b"}
    host = [numeric_run(task, seed, "host", score=seed)
            for task in tasks for seed in (1, 2, 3)]
    governed = [numeric_run(task, seed, "governed", score=seed + 0.5)
                for task in tasks for seed in (1, 2, 3)]
    store = AppendOnlyStore(tmp_path / "comparison.jsonl")
    result = compare_scores_same_budget(host, governed, 0.25,
                                        expected_task_ids=tasks, store=store)
    assert result.paired_runs == 6 and result.task_count == 2
    assert result.host_mean_score == 2 and result.governed_mean_score == 2.5
    assert result.score_delta == 0.5 and result.paired_delta_sem == 0
    assert result.verdict == "governed_above_noise"
    assert result.actual_cost_totals["host"] == {"token": 480, "wallclock": 48}
    assert len(list(store.read("same_budget_score_comparison"))) == 1


def test_numeric_minimize_direction_and_noise_floor():
    host = [numeric_run("task", seed, "host", score=3, direction="minimize")
            for seed in (1, 2, 3)]
    governed = [numeric_run("task", seed, "governed", score=2, direction="minimize")
                for seed in (1, 2, 3)]
    result = compare_scores_same_budget(host, governed, 1.0, min_seeds=3)
    assert result.host_mean_score == 3 and result.governed_mean_score == 2
    assert result.score_delta == 1 and result.verdict == "within_noise_floor"


def test_numeric_comparison_rejects_unfair_incomplete_or_unmeasured_runs():
    host = [numeric_run("task", seed, "host") for seed in (1, 2, 3)]
    governed = [numeric_run("task", seed, "governed") for seed in (1, 2, 3)]
    unfair = list(governed)
    unfair[0] = replace(unfair[0], budget={"wallclock": 20, "token": 100},
                        actual_costs={"wallclock": 8, "token": 80})
    with pytest.raises(ValueError, match="budget mismatch"):
        compare_scores_same_budget(host, unfair, 0)
    with pytest.raises(ValueError, match="task-seed sets"):
        compare_scores_same_budget(host, governed[:-1], 0)
    with pytest.raises(ValueError, match="locked benchmark task list"):
        compare_scores_same_budget(host, governed, 0, expected_task_ids={"other"})
    unmeasured = list(governed)
    unmeasured[0] = replace(unmeasured[0], measured=False)
    with pytest.raises(ValueError, match="measured runs"):
        compare_scores_same_budget(host, unmeasured, 0)
    no_evidence = list(governed)
    no_evidence[0] = replace(no_evidence[0], evidence_refs=())
    with pytest.raises(ValueError, match="evidence refs"):
        compare_scores_same_budget(host, no_evidence, 0)
    overspent = list(governed)
    overspent[0] = replace(overspent[0], actual_costs={"wallclock": 8, "token": 101})
    with pytest.raises(ValueError, match="exceeds the declared budget"):
        compare_scores_same_budget(host, overspent, 0)
    timed_overspend = list(governed)
    timed_overspend[0] = replace(timed_overspend[0], timed_out=True,
                                 actual_costs={"wallclock": 8, "token": 101})
    with pytest.raises(ValueError, match="exceeds the declared budget"):
        compare_scores_same_budget(host, timed_overspend, 0)


def test_numeric_comparison_requires_same_seed_sets_and_finite_scores():
    host = ([numeric_run("a", seed, "host") for seed in (1, 2, 3)] +
            [numeric_run("b", seed, "host") for seed in (4, 5, 6)])
    governed = ([numeric_run("a", seed, "governed") for seed in (1, 2, 3)] +
                [numeric_run("b", seed, "governed") for seed in (4, 5, 6)])
    with pytest.raises(ValueError, match="same seed set"):
        compare_scores_same_budget(host, governed, 0)
    host = [numeric_run("task", seed, "host") for seed in (1, 2, 3)]
    governed = [numeric_run("task", seed, "governed") for seed in (1, 2, 3)]
    governed[0] = replace(governed[0], score=math.inf)
    with pytest.raises(ValueError, match="finite"):
        compare_scores_same_budget(host, governed, 0)


def test_timed_out_wallclock_is_preserved_but_other_overspend_is_not_excused():
    record = numeric_run("task", 1, "host", budget={"wallclock": 1, "token": 5},
                         actual={"wallclock": 1.2, "token": 5}, timed_out=True)
    record.validate_measured()
    assert record.actual_costs["wallclock"] == 1.2
    with pytest.raises(ValueError, match="exceeds"):
        replace(record, actual_costs={"wallclock": 1.2, "token": 6}).validate_measured()
    with pytest.raises(ValueError, match="exceeds"):
        replace(record, timed_out=False).validate_measured()


def test_real_agents_partial_matrix_and_credentials_never_create_comparison(tmp_path, monkeypatch):
    official, manifest = official_fixture(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "re-bench-test-secret-never-persist")
    agent = score_agent(tmp_path)
    command = f"{sys.executable} {agent}"
    result = run_campaign(official, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 5, seeds=(7,), task_ids=[TASK],
                          aggregator_factory=lambda _task: None, manifest_path=manifest)
    assert result["agent_executions"] == 2
    assert result["officially_scored_runs"] == 2
    assert result["comparison_complete"] is False
    assert "7 tasks" in result["comparison_error"]
    for arm in ("host", "governed"):
        run_dir = tmp_path / "campaign" / TASK / "seed_7" / arm
        record = json.loads((run_dir / "benchmark_run.json").read_text())
        assert record["measured"] is True
        assert record["score"] == (0.75 if arm == "governed" else 0.5)
        assert not list((run_dir / "workspace").rglob("score_log.json"))
    for path in (tmp_path / "campaign").rglob("*.json*"):
        assert "re-bench-test-secret-never-persist" not in path.read_text()


def test_missing_score_log_is_failure_not_zero_score_measurement(tmp_path):
    official, manifest = official_fixture(tmp_path)
    agent = score_agent(tmp_path, "missing")
    command = f"{sys.executable} {agent}"
    result = run_campaign(official, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 5, seeds=(1,), task_ids=[TASK],
                          aggregator_factory=lambda _task: None, manifest_path=manifest)
    assert result["agent_executions"] == 2 and result["officially_scored_runs"] == 0
    assert result["comparison"] is None and len(result["failures"]) == 2
    assert all("score log is missing" in failure["error"] for failure in result["failures"])
    assert not list((tmp_path / "campaign").rglob("benchmark_run.json"))


def test_real_timeout_kills_process_group_and_usage_limit_policy_controls_scoring(tmp_path):
    agent = score_agent(tmp_path, "timeout")
    command = f"{sys.executable} {agent}"
    for permitted, expected_records in ((False, 0), (True, 2)):
        case = tmp_path / str(permitted)
        case.mkdir()
        official, manifest = official_fixture(case, score_on_usage_limits=permitted)
        started = time.monotonic()
        result = run_campaign(official, case / "campaign", command, command,
                              "offline-fixture-backbone", 0.4, seeds=(1,), task_ids=[TASK],
                              aggregator_factory=lambda _task: None, manifest_path=manifest)
        assert time.monotonic() - started < 5
        assert result["officially_scored_runs"] == expected_records
        for arm in ("host", "governed"):
            run_dir = case / "campaign" / TASK / "seed_1" / arm
            summary = json.loads((run_dir / "run.json").read_text())
            assert summary["timed_out"] is True and summary["agent_returncode"] == -9
            assert summary["actual_costs"]["wallclock"] >= 0.4
            if permitted:
                assert summary["status"] == "officially_scored"
                record = json.loads((run_dir / "benchmark_run.json").read_text())
                assert record["timed_out"] is True
                assert record["actual_costs"]["wallclock"] > record["budget"]["wallclock"]
            else:
                assert "does not permit scoring" in summary["error"]
        time.sleep(0.9)
        assert not list((case / "campaign").rglob("orphan-survived"))


def test_complete_real_matrix_invokes_strict_numeric_comparison(tmp_path, monkeypatch):
    official, manifest = official_fixture(tmp_path)
    agent = score_agent(tmp_path)
    command = f"{sys.executable} {agent}"
    monkeypatch.setattr(REBenchAdapter, "task_ids", staticmethod(lambda: [TASK]))
    result = run_campaign(official, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 5, seeds=(1, 2, 3), task_ids=[TASK],
                          noise_floor=0.1, aggregator_factory=lambda _task: None,
                          manifest_path=manifest)
    assert result["comparison_complete"] is True
    assert result["comparison"]["paired_runs"] == 3
    assert result["comparison"]["score_delta"] == 0.25
    assert result["comparison"]["verdict"] == "governed_above_noise"
    assert (tmp_path / "campaign/comparison.jsonl").is_file()


def test_production_preflight_requires_viv_and_official_scoring_package(tmp_path, monkeypatch):
    official, manifest = official_fixture(tmp_path)
    monkeypatch.setattr("zoo.re_bench.runner.shutil.which", lambda _name: None)
    output = tmp_path / "must-not-exist"
    with pytest.raises(RuntimeError, match="viv CLI"):
        run_campaign(official, output, "unused", "unused", "fixture", 1,
                     task_ids=[TASK], manifest_path=manifest)
    assert not output.exists()
    monkeypatch.setattr("zoo.re_bench.runner.shutil.which", lambda _name: "/usr/bin/viv")
    monkeypatch.setattr("zoo.re_bench.runner.importlib.util.find_spec", lambda _name: None)
    with pytest.raises(RuntimeError, match="task_protected_scoring"):
        preflight(official, [TASK], manifest_path=manifest)


def test_nonempty_campaign_evidence_directory_is_never_overwritten(tmp_path):
    official, manifest = official_fixture(tmp_path)
    output = tmp_path / "campaign"
    output.mkdir()
    sentinel = output / "keep.json"
    sentinel.write_text('{"original": true}')
    with pytest.raises(FileExistsError, match="must be empty"):
        run_campaign(official, output, "unused", "unused", "fixture", 1,
                     task_ids=[TASK], aggregator_factory=lambda _task: None,
                     manifest_path=manifest)
    assert sentinel.read_text() == '{"original": true}'
