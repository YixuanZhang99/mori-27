"""Portable MLE CLI metering contract; no Linux sandbox or provider calls."""
from types import SimpleNamespace

import pytest

from core.llm import UsageError, reset_usage, take_usage
from core.x1.store import AppendOnlyStore
from zoo.mle_bench_lite import governed_agent
from zoo.mle_bench_lite.agent_common import MeteredOpenAICompatibleLLM, token_usage_summary


class Provider:
    model = "meter-fixture"
    supplier = "fixture-provider"
    base_url = "http://fixture.invalid/v1"

    def __init__(self, unknown=False):
        self.prompts = []
        self.unknown = unknown

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.unknown:
            self.last_usage = None
        else:
            amount = 23 if prompt == "solution generation" else 17
            self.last_usage = {"total_tokens": amount, "prompt_tokens": amount - 2,
                               "completion_tokens": 2}
        return "candidate strategy"


def test_seed_is_explicit_zero_then_provider_usage_and_metadata_are_proxied(tmp_path):
    provider = Provider()
    metered = MeteredOpenAICompatibleLLM(provider, tmp_path / "usage", 6000)
    llm = governed_agent.GenesisAnchoredLLM(metered, "seed strategy")
    reset_usage(llm)
    assert llm("[draft seed]") == "seed strategy"
    assert take_usage(llm) == 0 and provider.prompts == []
    reset_usage(llm)
    assert llm("[draft next]") == "candidate strategy"
    assert take_usage(llm) == 17 and len(provider.prompts) == 1
    assert llm.model == "meter-fixture" and llm.supplier == "fixture-provider"


@pytest.mark.parametrize("usage", [None, {}, {"total_tokens": 0}, {"total_tokens": 7}])
def test_meter_records_known_cost_even_when_provider_content_fails(tmp_path, usage):
    class FailingProvider(Provider):
        def __call__(self, prompt):
            if usage is not None:
                self.last_usage = usage
            raise IndexError("malformed content")

    provider = FailingProvider()
    provider.last_usage = {"total_tokens": 99}
    usage_dir = tmp_path / "usage"
    metered = MeteredOpenAICompatibleLLM(provider, usage_dir, 6000)
    known = isinstance(usage, dict) and "total_tokens" in usage
    with pytest.raises(IndexError if known else RuntimeError):
        metered("call")
    summary = token_usage_summary(usage_dir, require_nonempty=False)
    if known:
        assert take_usage(metered) == usage["total_tokens"]
        assert summary["calls"] == 1 and summary["total_tokens"] == usage["total_tokens"]
        assert summary["component_usage_complete"] is False
    else:
        with pytest.raises(UsageError):
            take_usage(metered)
        assert summary["calls"] == 0


@pytest.mark.parametrize("reset_first", [False, True])
def test_budget_intercept_preserves_known_prior_cost_and_has_no_new_charge(tmp_path, reset_first):
    provider = Provider()
    metered = MeteredOpenAICompatibleLLM(provider, tmp_path / "usage", 17)
    metered("one call")
    if reset_first:
        assert take_usage(metered) == 17
        reset_usage(metered)
    with pytest.raises(RuntimeError, match="before LLM call"):
        metered("must not invoke")
    assert len(provider.prompts) == 1
    assert take_usage(metered) == (0 if reset_first else 17)


@pytest.mark.parametrize("unknown", [False, True])
def test_governed_cli_counts_shared_evaluator_model_once_and_blocks_unknown(
        tmp_path, monkeypatch, unknown):
    provider = Provider(unknown)
    metered = MeteredOpenAICompatibleLLM(provider, tmp_path / "usage", 6000)
    summaries = []

    def evaluate_prompt(candidate_id, prompt):
        # This is AgentRuntime's shared provider call, with local grading only.
        try:
            metered("solution generation")
        except (UsageError, RuntimeError):
            # AgentRuntime returns failed evaluation feedback while its meter
            # stays unknown. Framework must still refuse to settle it as zero.
            pass
        return {"valid_submission": True, "text_feedback": "valid",
                "evaluator_version": "fixture-v1"}

    def finalize(prompt, arm, summary):
        summaries.append(summary)
        return {"arm": arm}

    runtime = SimpleNamespace(llm=metered, artifacts=tmp_path / "artifacts",
                              task_id="fixture", seed=1, evaluate_prompt=evaluate_prompt,
                              finalize=finalize)
    monkeypatch.setattr(governed_agent, "runtime_from_args", lambda args: runtime)
    args = ["--workspace", str(tmp_path), "--iterations", "1", "--token-budget", "6000"]
    if unknown:
        with pytest.raises(UsageError):
            governed_agent.main(args)
        assert not summaries
    else:
        assert governed_agent.main(args) == 0
        assert sum(summaries[0]["token_spent"].values()) == 23 + 17 + 23
        assert len(provider.prompts) == 3
    rows = [row["payload"] for row in AppendOnlyStore(
        runtime.artifacts / "governed" / "x1.jsonl").read("ledger")]
    settlements = [row for row in rows if row["entry_kind"] == "settle"]
    assert [row["settled"] for row in settlements] == ([] if unknown else [23, 40])
