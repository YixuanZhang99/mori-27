"""v23 real local-LLM arm smoke tests; fixtures are not benchmark performance evidence."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.llm import take_usage
from tests.test_benchmark_adapters import TASK, official_fixture
from zoo.mle_bench_lite.agent_common import (
    INITIAL_GENERATOR, INITIAL_PROMPT, SOLUTION_GENERATION_MARKER,
    MeteredOpenAICompatibleLLM, extract_generator_prompt, prompt_digest,
    token_usage_summary)
from zoo.mle_bench_lite.runner import run_campaign


class LocalOpenAI:
    """Actual HTTP endpoint serving deterministic protocol-fixture completions."""

    def __init__(self):
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                fixture.requests.append(payload)
                assert self.headers.get("Authorization") == "Bearer local-smoke-secret"
                assert self.path == "/v1/chat/completions"
                text = "\n".join(message.get("content", "")
                                 for message in payload["messages"])
                if SOLUTION_GENERATION_MARKER in text:
                    content = """```python
import os
import shutil
assert 'OPENAI_API_KEY' not in os.environ
shutil.copyfile('sample_submission.csv', 'submission.csv')
```"""
                elif "[reflective improve" in text:
                    content = INITIAL_PROMPT + "\nVerify every output column before writing the file."
                elif "[draft " in text:
                    content = INITIAL_PROMPT
                else:
                    changed = INITIAL_GENERATOR.replace(
                        "Follow the task description", "Carefully follow the task description")
                    assert changed != INITIAL_GENERATOR
                    content = "```python\n" + changed + "\n```"
                body = json.dumps({
                    "id": "local-fixture", "object": "chat.completion",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                              "total_tokens": 18}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def fake_official_package(root: Path):
    package = root / "mlebench"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "registry.py").write_text("""class Registry:
    def __init__(self, data_root):
        self.data_root = data_root
    def get_competition(self, competition_id):
        return competition_id
""")
    (package / "grade.py").write_text("""from pathlib import Path

def grade_csv(path, competition):
    path = Path(path)
    valid = path.is_file() and path.read_text().startswith('id,prediction')
    return {'competition_id': competition, 'valid_submission': valid,
            'score': 0.25, 'above_median': False, 'any_medal': False,
            'gold_medal': False, 'silver_medal': False, 'bronze_medal': False}
""")


def report(_path):
    return {"competition_id": TASK, "valid_submission": True, "score": 0.25,
            "above_median": False, "any_medal": False, "gold_medal": False,
            "silver_medal": False, "bronze_medal": False}


def test_sync_meter_accumulates_between_resets_and_refuses_missing_usage(tmp_path):
    class Inner:
        model = "fixture-model"
        base_url = "http://fixture.invalid/v1"

        def __init__(self, total=18):
            self.total = total
            self.last_usage = {"total_tokens": 0}

        def __call__(self, _prompt):
            self.last_usage = {"prompt_tokens": 11, "completion_tokens": 7,
                               "total_tokens": self.total}
            return "ok"

    metered = MeteredOpenAICompatibleLLM(Inner(), tmp_path / "usage", 1_000)
    assert take_usage(metered) == 0
    metered("proposer")
    metered("solution")
    assert take_usage(metered) == 36
    assert take_usage(metered) == 0
    assert token_usage_summary(tmp_path / "usage")["total_tokens"] == 36
    missing = MeteredOpenAICompatibleLLM(Inner(total=0), tmp_path / "missing", 1_000)
    with pytest.raises(RuntimeError, match="internally inconsistent"):
        missing("call")
    assert token_usage_summary(tmp_path / "missing", require_nonempty=False)["calls"] == 0


def test_host_generator_extraction_never_executes_program():
    assert extract_generator_prompt(INITIAL_GENERATOR) == INITIAL_PROMPT.strip()
    with pytest.raises(ValueError, match="no SOLUTION_PROMPT"):
        extract_generator_prompt("raise RuntimeError('must not execute')")


def test_real_host_and_governed_clis_with_local_openai_and_isolated_execution(
        tmp_path, monkeypatch):
    official, data, manifest = official_fixture(tmp_path)
    fake_official = tmp_path / "fixture-package"
    fake_official_package(fake_official)
    service = LocalOpenAI()
    monkeypatch.setenv("OPENAI_API_KEY", "local-smoke-secret")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(fake_official), str(ROOT))))
    common = "--workspace {workspace} --task {task} --seed {seed} --iterations 1"
    common += f" --model local-fixture --api-base {service.url} --solution-timeout 10"
    try:
        result = run_campaign(
            official, data, tmp_path / "campaign",
            f"{sys.executable} -m zoo.mle_bench_lite.host_agent {common}",
            f"{sys.executable} -m zoo.mle_bench_lite.governed_agent {common}",
            "same-local-fixture-backbone", 90, seeds=(7,), task_ids=[TASK],
            grader_factory=lambda _task: report, manifest_path=manifest,
            token_budget=2_000)
    finally:
        service.close()
    assert result["agent_executions"] == 2
    assert result["officially_graded_runs"] == 2, result["failures"]
    assert result["comparison_complete"] is False
    assert result["backbone_evidence_complete"] is True
    assert result["budget"] == {"wallclock": 90, "token": 2_000}
    assert {record["actual_costs"]["token"]
            for record in result["benchmark_run_records"]} == {54}
    texts = ["\n".join(message.get("content", "") for message in request["messages"])
             for request in service.requests]
    assert any(SOLUTION_GENERATION_MARKER in text for text in texts)
    assert any("[reflective improve" in text for text in texts)
    assert any("EVOLVE-BLOCK-START" in text for text in texts)
    for arm in ("host", "governed"):
        run_dir = tmp_path / "campaign" / TASK / "seed_7" / arm
        assert (run_dir / "workspace/submission.csv").is_file()
        assert (run_dir / "workspace/data/train.csv").is_file()
        summary = json.loads((run_dir / "agent_artifacts/agent_run.json").read_text())
        assert summary["arm"] == arm
        assert summary["selected_dev_valid_submission"] is True
        assert summary["external_benchmark_score_produced"] is False
        assert summary["actual_model"] == "local-fixture"
        assert summary["token_usage"]["calls"] == 3
        assert summary["token_usage"]["total_tokens"] == 54
        assert summary["token_budget_exceeded"] is False
        measured = json.loads((run_dir / "benchmark_run.json").read_text())
        assert measured["budget"]["token"] == 2_000
        assert measured["actual_costs"]["token"] == 54
        if arm == "governed":
            assert sum(summary["details"]["token_spent"].values()) == 54
            assert summary["details"]["token_spent"]["exploit"] == 36
        else:
            assert summary["token_usage"]["by_source"]["host_evolution"]["total_tokens"] == 18
        outcomes = [json.loads(path.read_text()) for path in
                    (run_dir / "agent_artifacts/candidates").glob("*/outcome.json")]
        assert len(outcomes) >= 2
        assert all("score" not in outcome and "any_medal" not in outcome
                   for outcome in outcomes)
        assert (run_dir / "agent_artifacts/candidates" /
                prompt_digest(INITIAL_PROMPT.strip()) / "outcome.json").is_file()
        audit = (run_dir / "audit.jsonl").read_text()
        assert "official_grading_report" in audit
        assert not list((run_dir / "workspace").rglob("grade.py"))
    evidence_files = list((tmp_path / "campaign").rglob("*.json*"))
    evidence_files += list((tmp_path / "campaign").rglob("*.log"))
    for path in evidence_files:
        assert "local-smoke-secret" not in path.read_text()
