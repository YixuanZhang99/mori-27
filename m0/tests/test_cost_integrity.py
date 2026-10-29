"""Usage evidence must distinguish known zero from missing or malformed cost."""
from types import SimpleNamespace
from dataclasses import asdict
import io
import json

import pytest

from core.llm import OpenAICompatibleLLM, UsageError, reset_usage, take_usage
from core.budget.types import AccountingStamp
from core.loop import Framework, LoopConfig
from core.tasks.gsm8k import GSM8KEvaluator
from examples.toy_gepa import MockLLM, toy_evaluator


@pytest.mark.parametrize("usage", [None, {}, {"total_tokens": -1},
    {"total_tokens": True}, {"total_tokens": 1.0}, {"total_tokens": "2"},
    {"total_tokens": float("nan")}, {"total_tokens": float("inf")},
    {"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 2}])
def test_provider_usage_requires_valid_explicit_totals(usage):
    response = {"choices": [{"message": {"content": "ok"}}], "usage": usage}
    with pytest.raises(UsageError):
        OpenAICompatibleLLM.parse_response(response)


def test_zero_consumption_and_pending_meter_are_distinct():
    obj = SimpleNamespace(last_usage={"total_tokens": 0})
    assert take_usage(obj) == 0
    assert take_usage(obj) == 0
    obj.last_usage = {"total_tokens": 19}
    reset_usage(obj)
    with pytest.raises(UsageError):
        take_usage(obj)


def test_failed_request_cannot_reuse_previous_usage():
    llm = OpenAICompatibleLLM("fixture", api_key="")
    llm.last_usage = {"total_tokens": 19}
    with pytest.raises(RuntimeError, match="API_KEY"):
        llm("test")
    with pytest.raises(UsageError):
        take_usage(llm)


def test_malformed_provider_content_preserves_known_usage(monkeypatch):
    response = {"usage": {"total_tokens": 7}, "choices": []}
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode()))
    llm = OpenAICompatibleLLM("fixture", api_key="fixture")
    with pytest.raises(IndexError):
        llm("test")
    assert take_usage(llm) == 7


def test_read_only_meter_failure_is_an_unknown_cost_error():
    class ReadOnly:
        @property
        def last_usage(self):
            return {"total_tokens": 7}
    with pytest.raises(UsageError, match="consumed exactly once"):
        take_usage(ReadOnly())


@pytest.mark.parametrize("known_usage", [None, 0, 7])
def test_failed_sequential_proposal_preserves_known_charge(tmp_path, known_usage):
    class FailedProposer:
        def __call__(self, prompt):
            if known_usage is not None:
                self.last_usage = {"total_tokens": known_usage}
            raise RuntimeError("invalid provider content")
    fw = Framework(FailedProposer(), toy_evaluator,
                   LoopConfig(max_generations=0), str(tmp_path))
    with pytest.raises(UsageError if known_usage is None else RuntimeError):
        fw.evolve("failed proposal")
    settlements = [row["payload"] for row in fw.store.read("ledger")
                   if row["payload"]["entry_kind"] == "settle"]
    if known_usage is None:
        assert not settlements
    else:
        assert [row["settled"] for row in settlements] == [known_usage]
        assert list(fw.store.read("m0_sequential_proposal_failure"))
    assert not list(fw.store.read("receipt"))


def test_unknown_cost_during_batch_preparation_cannot_refund_reserves(tmp_path):
    class MissingBatchUsage(MockLLM):
        calls = 0

        def __call__(self, prompt):
            response = super().__call__(prompt)
            self.calls += 1
            if self.calls > 1:
                self.last_usage = None
            return response
    fw = Framework(MissingBatchUsage(), toy_evaluator,
                   LoopConfig(max_generations=1, batch_size=2), str(tmp_path))
    with pytest.raises(UsageError):
        fw.evolve("unknown prepare usage")
    rows = [row["payload"] for row in fw.store.read("ledger")]
    assert len([row for row in rows if row["entry_kind"] == "reserve"]) == 3
    assert len([row for row in rows if row["entry_kind"] == "settle"]) == 1
    assert not any(row["entry_kind"] == "reserve_released" for row in rows)


def test_accounting_metadata_is_explicit_and_frozen_across_resume_and_replay(tmp_path):
    stamp = AccountingStamp("declared-supplier", "declared-model", "declared-tokenizer",
                            "declared-price-table", "2026-10-29")
    cfg = LoopConfig(max_generations=1, stop_after_generation=0)
    fw = Framework(MeteredProposer({"total_tokens": 3}), MeteredEvaluator({"total_tokens": 5}),
                   cfg, str(tmp_path), accounting_stamp=stamp)
    fw.evolve("accounting stamp")
    assert all(row["payload"]["stamp"] == asdict(stamp) for row in fw.store.read("ledger"))
    resumed = Framework(MeteredProposer({"total_tokens": 3}),
                        MeteredEvaluator({"total_tokens": 5}),
                        LoopConfig(max_generations=1, resume_from_checkpoint=True),
                        str(tmp_path), accounting_stamp=stamp)
    resumed.evolve("accounting stamp")
    assert resumed.replay()["replay_certificate"]["passed"]
    with pytest.raises(ValueError, match="differs from the original"):
        Framework(MockLLM(), toy_evaluator,
                  LoopConfig(resume_from_checkpoint=True), str(tmp_path),
                  accounting_stamp=AccountingStamp("changed", "m", "t", "p", "d"))


def test_default_accounting_stamp_never_invents_mock_or_price_metadata(tmp_path):
    llm = SimpleNamespace(supplier="fixture-supplier", model="fixture-model")
    fw = Framework(llm, toy_evaluator, LoopConfig(), str(tmp_path))
    assert fw.stamp.supplier == "fixture-supplier"
    assert fw.stamp.model_version == "fixture-model"
    assert fw.stamp.tokenizer_version == fw.stamp.price_table_version == fw.stamp.date == "unavailable"


class MeteredProposer(MockLLM):
    def __init__(self, usage):
        self.usage = usage

    def __call__(self, prompt):
        response = super().__call__(prompt)
        self.last_usage = self.usage
        return response


class MeteredEvaluator:
    def __init__(self, usage):
        self.usage = usage

    def __call__(self, candidate_id, head_sha, prompt):
        self.last_usage = self.usage
        return toy_evaluator(candidate_id, head_sha, prompt)


@pytest.mark.parametrize("proposal_usage,eval_usage", [
    (None, {"total_tokens": 5}), ({"total_tokens": 3}, None),
    ({"total_tokens": -10}, {"total_tokens": 5}),
])
def test_unknown_or_invalid_cost_cannot_admit_or_settle(tmp_path, proposal_usage, eval_usage):
    fw = Framework(MeteredProposer(proposal_usage), MeteredEvaluator(eval_usage),
                   LoopConfig(max_generations=0), str(tmp_path))
    with pytest.raises(UsageError):
        fw.evolve("untrustworthy metering")
    ledger = [row["payload"] for row in fw.store.read("ledger")]
    assert any(row["entry_kind"] == "reserve" for row in ledger)
    assert not any(row["entry_kind"] == "settle" for row in ledger)
    assert not list(fw.store.read("receipt"))


@pytest.mark.parametrize("batch_size", [1, 2])
def test_explicit_zero_is_never_replaced_with_intent_estimate(tmp_path, batch_size):
    fw = Framework(MeteredProposer({"total_tokens": 0}),
                   MeteredEvaluator({"total_tokens": 0}),
                   LoopConfig(max_generations=1, batch_size=batch_size), str(tmp_path))
    result = fw.evolve("known zero")
    settlements = [row["payload"] for row in fw.store.read("ledger")
                   if row["payload"]["entry_kind"] == "settle"]
    assert len(settlements) == 1 + batch_size
    assert all(row["settled"] == 0 for row in settlements)
    assert result["governance_audit"]["passed"]


@pytest.mark.parametrize("known_failure", [True, False])
def test_gsm8k_preserves_partial_cost_only_if_failed_call_is_metered(known_failure):
    class Solver:
        calls = 0

        def __call__(self, prompt):
            self.calls += 1
            if self.calls == 2:
                if known_failure:
                    self.last_usage = {"total_tokens": 7}
                raise RuntimeError("provider failed")
            self.last_usage = {"total_tokens": 5}
            return "#### 1"

    evaluator = GSM8KEvaluator([{"question": "one", "gold": 1}] * 2, Solver())
    with pytest.raises(RuntimeError if known_failure else UsageError):
        evaluator("candidate", "head", "prompt")
    if known_failure:
        assert take_usage(evaluator) == 12
    else:
        with pytest.raises(UsageError):
            take_usage(evaluator)
