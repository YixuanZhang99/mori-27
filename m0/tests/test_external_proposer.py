"""ExternalCommandLLM protocol, failure adoption and real OpenAI worker tests."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.executor.proposal import ExternalCommandLLM, ExternalProposalError
from core.executor.types import EvalStatus
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_proposal_recovery import proposer, proposer_workspace
from test_external_recovery import ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]
PROMPT = ("[reflective improve v1]\nCURRENT PROMPT:\nbase\n\nSCORE: 0.3\n"
          "EVALUATION TRAJECTORY:\nitem_4 failed; missing hint: hint_4\n")


def context(candidate="candidate"):
    return {"cohort_id": "cohort", "candidate_id": candidate,
            "generation": 1, "operator": "improve", "intent": {}}


def test_real_call_is_persistent_and_adopted_without_another_process(tmp_path):
    root, script, count = proposer_workspace(tmp_path, "protocol")
    store = AppendOnlyStore(tmp_path / "run/x1.jsonl")
    llm = proposer(root, script, count, store, MockLLM())
    llm.set_operation_context(context())
    assert llm(PROMPT) == "base\nhint_4"
    assert llm.last_usage == {"total_tokens": 11}
    llm.clear_operation_context()

    recovered = proposer(root, script, count, store, ForbiddenLLM())
    recovered.set_operation_context(context())
    assert recovered(PROMPT) == "base\nhint_4"
    assert recovered.last_usage == {"total_tokens": 11}
    assert count.read_text().splitlines() == ["call"]
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("external_proposer_outcome"))) == 1

    with pytest.raises(RuntimeError, match="request has changed"):
        recovered("different prompt")
    assert count.read_text().splitlines() == ["call"]


@pytest.mark.parametrize("mode,status", [("malformed", EvalStatus.INVALID),
                                         ("timeout", EvalStatus.TIMEOUT)])
def test_terminal_failure_is_durable_and_not_retried(tmp_path, mode, status):
    root, script, count = proposer_workspace(tmp_path, f"failure-{mode}")
    store = AppendOnlyStore(tmp_path / f"run-{mode}/x1.jsonl")
    llm = proposer(root, script, count, store, MockLLM(), mode, time_limit=1)
    llm.set_operation_context(context())
    with pytest.raises(ExternalProposalError) as caught:
        llm(PROMPT)
    assert caught.value.status is status
    llm.clear_operation_context()

    recovered = proposer(root, script, count, store, ForbiddenLLM(), mode, time_limit=1)
    recovered.set_operation_context(context())
    with pytest.raises(ExternalProposalError) as adopted:
        recovered(PROMPT)
    assert adopted.value.status is status
    assert count.read_text().splitlines() == ["call"]
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("external_proposer_outcome"))) == 1


def test_openai_worker_real_local_http_usage_and_credential_nonpersistence(
        tmp_path, monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), payload))
            response = {"choices": [{"message": {"content": "local-openai-response"}}],
                        "usage": {"total_tokens": 13, "prompt_tokens": 8,
                                  "completion_tokens": 5}}
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("PYTHONPATH", str(PROJECT))
    store = AppendOnlyStore(tmp_path / "openai-run/x1.jsonl")
    command = [sys.executable, "-m", "core.executor.openai_proposal_worker",
               "--model", "offline-model", "--base-url",
               f"http://127.0.0.1:{server.server_port}/v1"]
    llm = ExternalCommandLLM(command, tmp_path / "openai-work", store)
    try:
        llm.set_operation_context(context("openai-candidate"))
        assert llm("offline prompt") == "local-openai-response"
        assert llm.last_usage == {"total_tokens": 13}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert len(requests) == 1
    path, authorization, payload = requests[0]
    assert path == "/v1/chat/completions" and authorization == "Bearer offline-test-key"
    assert payload["model"] == "offline-model" and payload["temperature"] == 0.0
    assert payload["messages"] == [{"role": "user", "content": "offline prompt"}]
    evidence = (tmp_path / "openai-run/x1.jsonl").read_text() + "".join(
        path.read_text() for path in (tmp_path / "openai-run/executor-processes").glob(
            "*/spec.json"))
    assert "offline-test-key" not in evidence
    record = list(store.read("executor_process_started"))[0]["payload"]
    assert record["process_kind"] == "m0_external_proposer"
    assert record["seccomp_delivery"] == "direct_prctl"
    assert record["seccomp_policy"]["policy_version"] == 2
    spec = json.loads(Path(record["spec_path"]).read_text())
    assert spec["seccomp_delivery"] == "direct_prctl"
    assert Path(spec["args"][0]).name != "bwrap"
