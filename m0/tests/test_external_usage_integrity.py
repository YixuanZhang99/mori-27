"""Portable validation of durable external cost evidence, without a subprocess."""
import json

import pytest

from core.executor.external import ExternalCommandEvaluator, ExternalEvaluatorError
from core.executor.proposal import ExternalCommandLLM, ExternalProposalError
from core.llm import UsageError, take_usage
from core.x1.store import AppendOnlyStore


def adapter(tmp_path, kind):
    store = AppendOnlyStore(tmp_path / "journal.jsonl")
    if kind == "proposal":
        external = ExternalCommandLLM(["adapter"], tmp_path, store, seccomp=False)
    else:
        external = ExternalCommandEvaluator(["adapter"], tmp_path, store, sandbox=False)
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    request.write_text("{}")
    record = {"request_path": str(request), "response_path": str(response),
              "execution_id": "execution", "execution_ref": "cohort",
              "operation_id": "candidate", "candidate_id": "candidate", "head_sha": "head"}
    return external, record, response, store


def complete(external, record, completed):
    method = getattr(external, "_complete_process", None) or external._complete
    return method(record, completed)


@pytest.mark.parametrize("kind", ["proposal", "evaluation"])
@pytest.mark.parametrize("timeout,returncode", [(False, 0), (False, 3), (True, -9)])
@pytest.mark.parametrize("usage", [None, {}, {"total_tokens": -1},
                                   {"total_tokens": True}, {"total_tokens": "5"}])
def test_failed_external_call_cannot_turn_unknown_usage_into_zero(
        tmp_path, kind, timeout, returncode, usage):
    external, record, response, store = adapter(tmp_path, kind)
    external.last_usage = {"total_tokens": 99}  # Previous invocation must not leak.
    response.write_text(json.dumps({"schema_version": 1, "token_usage": usage}))
    with pytest.raises((ExternalProposalError, ExternalEvaluatorError)):
        complete(external, record, {"timeout": timeout, "returncode": returncode,
                                    "stdout": "", "stderr": "failure"})
    assert external.last_usage is None
    with pytest.raises(UsageError):
        take_usage(external)
    event = "external_proposer_outcome" if kind == "proposal" else "external_evaluator_outcome"
    assert list(store.read(event))[0]["payload"]["token_usage"] is None


@pytest.mark.parametrize("kind", ["proposal", "evaluation"])
@pytest.mark.parametrize("tokens", [0, 17])
@pytest.mark.parametrize("returncode", [0, 3])
def test_invalid_content_keeps_explicit_failure_usage(tmp_path, kind, tokens, returncode):
    external, record, response, store = adapter(tmp_path, kind)
    response.write_text(json.dumps({"schema_version": 1,
                                    "token_usage": {"total_tokens": tokens}}))
    with pytest.raises((ExternalProposalError, ExternalEvaluatorError)):
        complete(external, record, {"timeout": False, "returncode": returncode,
                                    "stdout": "", "stderr": "failure"})
    assert take_usage(external) == tokens
    event = "external_proposer_outcome" if kind == "proposal" else "external_evaluator_outcome"
    outcome = list(store.read(event))[0]["payload"]
    assert outcome["token_usage"] == {"total_tokens": tokens}
    if kind == "proposal":
        with pytest.raises(ExternalProposalError):
            external._return_outcome(outcome, outcome["request_sha256"])
        assert take_usage(external) == tokens
    else:
        assert external.outcome(record)["token_usage"] == {"total_tokens": tokens}


@pytest.mark.parametrize("kind", ["proposal", "evaluation"])
def test_successful_external_result_accepts_explicit_zero_usage(tmp_path, kind):
    external, record, response, _ = adapter(tmp_path, kind)
    envelope = {"schema_version": 1, "token_usage": {"total_tokens": 0}}
    if kind == "proposal":
        envelope["content"] = "proposal"
    else:
        envelope["result"] = {
            "candidate_id": "candidate", "head_sha": "head",
            "items": [{"item_id": "item", "verdict": 1}], "combined_score": 1,
            "public": {}, "private": {}, "text_feedback": "ok",
            "reliability": {"n_trials": 1, "ci95": None, "noise_floor": None},
            "evaluator_version": "v1"}
    response.write_text(json.dumps(envelope))
    complete(external, record, {"timeout": False, "returncode": 0, "stdout": "", "stderr": ""})
    assert take_usage(external) == 0


def test_durable_unknown_proposal_outcome_stays_unknown_on_adoption(tmp_path):
    external, record, _, _ = adapter(tmp_path, "proposal")
    payload = external._persist(record, "failed_to_run", "adapter disappeared")
    with pytest.raises(ExternalProposalError):
        external._return_outcome(payload, payload["request_sha256"])
    with pytest.raises(UsageError):
        take_usage(external)
