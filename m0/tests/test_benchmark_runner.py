"""v22 campaign-runner tests; fixtures are not MLE-Bench performance evidence."""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_benchmark_adapters import TASK, official_fixture
from zoo.mle_bench_lite.agent_common import token_usage_summary
from zoo.mle_bench_lite.runner import _required_token_cost, run_campaign


def agent_script(root: Path, mode="copy") -> Path:
    path = root / "agent.py"
    if mode == "copy":
        body = "import shutil; shutil.copyfile('sample_submission.csv', 'submission.csv')"
    elif mode == "sleep":
        body = "import time; time.sleep(30)"
    else:
        body = "print('agent ran without output')"
    path.write_text(body + "\n")
    return path


def report(_path):
    return {"competition_id": TASK, "valid_submission": True, "score": 0.25,
            "above_median": False, "any_medal": False, "gold_medal": False,
            "silver_medal": False, "bronze_medal": False}


def test_real_agent_commands_and_official_evidence_but_partial_matrix_never_compares(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    agent = agent_script(tmp_path)
    command = f"{sys.executable} {agent}"
    report_data = run_campaign(official, data, tmp_path / "campaign", command, command,
                               "offline-fixture-backbone", 5, seeds=(7,), task_ids=[TASK],
                               grader_factory=lambda _task: report, manifest_path=manifest)
    assert report_data["agent_executions"] == 2
    assert report_data["officially_graded_runs"] == 2
    assert report_data["comparison_complete"] is False
    assert "22 tasks" in report_data["comparison_error"]
    for arm in ("host", "governed"):
        run_dir = tmp_path / "campaign" / TASK / "seed_7" / arm
        assert (run_dir / "workspace/submission.csv").is_file()
        assert (run_dir / "workspace/data/train.csv").is_file()
        assert (run_dir / "workspace/data/test.csv").is_file()
        assert not list((run_dir / "workspace").rglob("grade.py"))
        assert not list((run_dir / "workspace").rglob("leaderboard.csv"))
        assert json.loads((run_dir / "benchmark_run.json").read_text())["measured"] is True
        assert len((run_dir / "audit.jsonl").read_text().splitlines()) == 2


def test_missing_submission_is_real_failure_not_zero_score_measurement(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    agent = agent_script(tmp_path, "empty")
    command = f"{sys.executable} {agent}"
    result = run_campaign(official, data, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 5, seeds=(1,), task_ids=[TASK],
                          grader_factory=lambda _task: report, manifest_path=manifest)
    assert result["agent_executions"] == 2
    assert result["officially_graded_runs"] == 0
    assert result["comparison"] is None and len(result["failures"]) == 2
    assert {failure["error"] for failure in result["failures"]} == {"no_submission"}
    assert not list((tmp_path / "campaign").rglob("benchmark_run.json"))


def test_declared_token_budget_refuses_missing_usage_evidence(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    agent = agent_script(tmp_path)
    command = f"{sys.executable} {agent}"
    result = run_campaign(official, data, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 5, seeds=(1,), task_ids=[TASK],
                          grader_factory=lambda _task: report, manifest_path=manifest,
                          token_budget=1_000)
    assert result["agent_executions"] == 2
    assert result["officially_graded_runs"] == 0
    assert result["backbone_evidence_complete"] is False
    assert not list((tmp_path / "campaign").rglob("benchmark_run.json"))
    assert {failure["error"] for failure in result["failures"]} == {
        "ValueError: token usage evidence is missing: agent_run.json"}


def test_token_receipt_tamper_and_overspend_fail_closed(tmp_path):
    run_dir = tmp_path / "run"
    usage_dir = run_dir / "agent_artifacts/token_usage"
    usage_dir.mkdir(parents=True)
    receipt_path = usage_dir / "receipt-1.json"
    receipt = {"usage_id": "receipt-1", "source": "fixture", "model": "same-model",
               "pid": 123, "prompt_tokens": 11, "completion_tokens": 7,
               "total_tokens": 18}
    receipt_path.write_text(json.dumps(receipt))
    usage = token_usage_summary(usage_dir)
    summary_path = run_dir / "agent_artifacts/agent_run.json"
    summary_path.write_text(json.dumps({
        "actual_model": "same-model", "token_budget": 1_000, "token_usage": usage}))
    cost, model, _ = _required_token_cost(run_dir, 1_000)
    assert cost == 18 and model == "same-model"
    receipt_path.write_text(json.dumps({**receipt, "total_tokens": 19}))
    with pytest.raises(ValueError, match="does not match independent receipts"):
        _required_token_cost(run_dir, 1_000)
    receipt_path.write_text(json.dumps(receipt))
    summary_path.write_text(json.dumps({
        "actual_model": "same-model", "token_budget": 10, "token_usage": usage}))
    with pytest.raises(ValueError, match="token budget exceeded"):
        _required_token_cost(run_dir, 10)


def test_real_timeout_kills_agent_process_group_and_preserves_incomplete_status(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    agent = agent_script(tmp_path, "sleep")
    command = f"{sys.executable} {agent}"
    started = time.monotonic()
    result = run_campaign(official, data, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 0.2, seeds=(1,), task_ids=[TASK],
                          grader_factory=lambda _task: report, manifest_path=manifest)
    assert time.monotonic() - started < 5
    assert result["officially_graded_runs"] == 0
    for arm in ("host", "governed"):
        summary = json.loads((tmp_path / "campaign" / TASK / "seed_1" / arm / "run.json").read_text())
        assert summary["timed_out"] is True and summary["agent_returncode"] == -9
        assert summary["status"] == "no_submission" and summary["measured"] is False


def test_preflight_failure_happens_before_any_campaign_artifact(tmp_path):
    official, data, manifest = official_fixture(tmp_path)
    sample = data / TASK / "prepared/public/sample_submission.csv"
    sample.unlink()
    output = tmp_path / "must-not-exist"
    with pytest.raises(FileNotFoundError, match="prepared public data"):
        run_campaign(official, data, output, "unused", "unused", "fixture", 1,
                     task_ids=[TASK], grader_factory=lambda _task: report, manifest_path=manifest)
    assert not output.exists()


def test_complete_measured_matrix_invokes_strict_comparison(tmp_path, monkeypatch):
    official, data, manifest = official_fixture(tmp_path)
    agent = agent_script(tmp_path)
    command = f"{sys.executable} {agent}"
    from zoo.mle_bench_lite.adapter import MLEBenchLiteAdapter
    monkeypatch.setattr(MLEBenchLiteAdapter, "task_ids", staticmethod(lambda: [TASK]))
    result = run_campaign(official, data, tmp_path / "campaign", command, command,
                          "offline-fixture-backbone", 5, seeds=(1, 2, 3), task_ids=[TASK],
                          noise_floor=0.1, grader_factory=lambda _task: report, manifest_path=manifest)
    assert result["comparison_complete"] is True
    assert result["comparison"]["paired_runs"] == 3
    assert result["comparison"]["verdict"] == "within_noise_floor"
    assert (tmp_path / "campaign/comparison.jsonl").is_file()


def test_runner_never_serializes_inherited_api_credentials(tmp_path, monkeypatch):
    official, data, manifest = official_fixture(tmp_path)
    agent = agent_script(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret-never-persist")
    command = f"{sys.executable} {agent}"
    run_campaign(official, data, tmp_path / "campaign", command, command,
                 "offline-fixture-backbone", 5, seeds=(1,), task_ids=[TASK],
                 grader_factory=lambda _task: report, manifest_path=manifest)
    for path in (tmp_path / "campaign").rglob("*.json*"):
        assert "test-only-secret-never-persist" not in path.read_text()
