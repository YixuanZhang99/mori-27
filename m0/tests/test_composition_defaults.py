"""Default registered modules run through canonical evidence and explicit usage."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.types import AccountingStamp
from core.composition.contracts import BuildContext, OperatorRequest, Proposal
from core.composition.defaults import (InProcessExecutor, InstructionSkill, LegacyPromptDomain,
                                       MetricAdmission, OperatorFailure, PromptOperator,
                                       composed_profile, default_registry)
from core.eval.types import EvalResult as LegacyResult, ItemResult
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.composition.provider import MeteredProvider
from core.composition.evaluation import encode_evidence, public_projection
from core.composition.strategies import GreedyPolicy, LLMCyclesPolicy
from core.llm import UsageError, take_usage
from core.loop import LoopConfig
from core.memory.types import ScopeContext
from core.state import StateApplier
from core.tasks.gsm8k import GSM8KEvaluator
from core.x1.store import AppendOnlyStore
from core.x1.checkpoint import payload_digest
from examples.toy_gepa import MockLLM, toy_evaluator


class RecordingLLM(MockLLM):
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return super().__call__(prompt)


def context(tmp_path, llm=None, evaluator=None, stamp=None):
    return BuildContext(llm or RecordingLLM(), evaluator or toy_evaluator,
                        AppendOnlyStore(tmp_path / "x1.jsonl"),
                        ScopeContext("run", "task", "domain"),
                        LoopConfig(max_generations=1), tmp_path, stamp)


def absorb_bound_evidence(modules, evidence, cycle=0):
    public = public_projection(evidence)
    proposed = asyncio.run(modules["policy"].absorb(public))
    return modules["memory"].prepare_mutations(
        proposed, public, "sha256:" + payload_digest(encode_evidence(evidence)), cycle=cycle)


def test_default_components_execute_draft_absorb_then_reflective_improvement(tmp_path):
    ctx = context(tmp_path)
    modules = default_registry().build(composed_profile(), ctx)
    policy = modules["policy"]
    state = modules["frontier"]
    observations = asyncio.run(policy.observe(state, modules["budget"].account_summary()))
    ideas = asyncio.run(policy.ideate(observations, None, 1))
    first = asyncio.run(modules["operators"][0].propose(
        OperatorRequest("arithmetic", "first", 0, strategy=ideas[0])))
    evidence = asyncio.run(modules["executor"].execute(first, EvalRequest("dev"), modules["domain"]))
    assert isinstance(evidence, EvidenceRecord)
    assert isinstance(evidence.eval_result, EvalResult)
    assert first.cost.tokens_in == 1000 and evidence.eval_result.cost.tokens_in == 0
    assert first.cost.node_count == 1 and first.cost.eval_count == 0
    assert first.measured_cost_units == ("token", "node", "eval_count")
    assert evidence.eval_result.cost.eval_count == 1
    assert evidence.eval_result.cost.node_count == 0
    assert evidence.eval_result.contract.measured_cost_units == ("token", "node", "eval_count")
    state.add(first.candidate, evidence)
    StateApplier(state, modules["memory"], ctx.store).apply_all(absorb_bound_evidence(modules, evidence))
    state.nodes["first"].status = "merged"
    assert asyncio.run(policy.select(state, {})) == ["first"]
    assert modules["memory"].entries
    second = asyncio.run(modules["operators"][1].propose(
        OperatorRequest("arithmetic", "second", 1, (first,), (evidence,))))
    next_evidence = asyncio.run(modules["executor"].execute(second, EvalRequest("dev"), modules["domain"]))
    assert modules["admission"].judge(next_evidence, evidence).admit is True
    assert second.candidate.parents == ["first"]


def test_instruction_skill_changes_actual_provider_prompt_without_mutating_request(tmp_path):
    ctx = context(tmp_path)
    request = OperatorRequest("task", "candidate", 0, context={"instruction": "Keep lineage"})
    amended = InstructionSkill("Use exact arithmetic").apply(request)
    asyncio.run(PromptOperator(ctx.llm, "draft").propose(amended))
    assert "Use exact arithmetic" in ctx.llm.prompts[0]
    assert "Keep lineage" in ctx.llm.prompts[0]
    assert request.context == {"instruction": "Keep lineage"}


def test_shared_proposing_and_gsm_solver_llm_cost_is_not_dropped_or_counted_twice(tmp_path):
    class Solver:
        def __call__(self, prompt):
            self.last_usage = {"total_tokens": 5}
            return "#### 42"
    llm = Solver()
    domain = LegacyPromptDomain(GSM8KEvaluator([{"question": "Six times seven?", "gold": 42}], llm), llm)
    proposal = asyncio.run(PromptOperator(llm, "draft").propose(OperatorRequest("solve", "candidate", 0)))
    result = asyncio.run(domain.evaluate(proposal, EvalRequest("dev")))
    assert proposal.cost.tokens_in == 5
    assert result.cost.tokens_in == 5
    assert result.metrics == {"dev/score": 1.0}
    assert llm.last_usage == {"total_tokens": 0}


def test_known_operator_failure_retains_exact_cost_and_unknown_usage_fails_closed():
    class Broken:
        def __call__(self, prompt):
            self.last_usage = {"total_tokens": 9}
            raise RuntimeError("provider charged before failure")
    with pytest.raises(OperatorFailure) as caught:
        asyncio.run(PromptOperator(Broken(), "draft").propose(OperatorRequest("x", "id", 0)))
    assert caught.value.cost.tokens_in == 9
    assert caught.value.cost.node_count == 1 and caught.value.cost.eval_count == 0
    assert caught.value.measured_cost_units == ("token", "node", "eval_count")
    class Unknown:
        def __call__(self, prompt):
            raise RuntimeError("no trustworthy usage")
    with pytest.raises(UsageError):
        asyncio.run(PromptOperator(Unknown(), "draft").propose(OperatorRequest("x", "id", 0)))


def test_known_domain_failure_returns_failure_evidence_with_exact_cost():
    class Broken:
        def __call__(self, *args):
            self.last_usage = {"total_tokens": 11}
            raise RuntimeError("evaluation failed")
    proposal = Proposal(Candidate("id"), "prompt")
    result = asyncio.run(LegacyPromptDomain(Broken(), MockLLM()).evaluate(proposal, EvalRequest("dev")))
    assert result.status is EvalStatus.FAILED_TO_RUN
    assert result.cost.tokens_in == 11 and result.cost.eval_count == 1
    assert MetricAdmission().judge(EvidenceRecord("id", result), None).admit is False


def test_legacy_result_identity_is_checked_before_canonical_projection():
    def wrong(candidate_id, head_sha, prompt):
        wrong.last_usage = {"total_tokens": 3}
        return LegacyResult("other", head_sha, [ItemResult("item", 1)], combined_score=1)
    result = asyncio.run(LegacyPromptDomain(wrong, MockLLM()).evaluate(
        Proposal(Candidate("id"), "prompt"), EvalRequest("dev")))
    assert result.status is EvalStatus.FAILED_TO_RUN
    assert result.cost.tokens_in == 3
    assert "binding mismatch" in result.text_feedback


@pytest.mark.parametrize("direction,before,after,expected", [
    ("maximize", 1.0, 2.0, True), ("minimize", 1.0, 0.0, True),
    ("maximize", 1.0, 1.0, False), ("minimize", 1.0, 2.0, False)])
def test_metric_admission_uses_configured_direction_and_strict_margin(direction, before, after, expected):
    def evidence(candidate, score):
        return EvidenceRecord(candidate, EvalResult(EvalStatus.OK, {"loss": score},
                                                    cost=CostVec(tokens_in=999)))
    gate = MetricAdmission("loss", direction)
    assert gate.judge(evidence("next", after), evidence("base", before)).admit is expected


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "1"])
def test_metric_admission_rejects_nonfinite_or_coerced_objectives(value):
    result = EvidenceRecord("id", EvalResult(EvalStatus.OK, {"dev/score": value}))
    with pytest.raises(ValueError, match="finite number"):
        MetricAdmission().judge(result, None)


@pytest.mark.parametrize("kind", ["provider", "domain", "policy", "frontier", "memory", "executor", "admission", "budget"])
def test_unknown_options_fail_preflight_before_factories_or_calls(tmp_path, kind):
    cfg = composed_profile()
    cfg[kind]["options"] = {"unknown": True}
    ctx = context(tmp_path)
    with pytest.raises(ValueError):
        default_registry().build(cfg, ctx)
    assert not ctx.store.path.exists()
    assert ctx.llm.prompts == []


def test_explicit_accounting_stamp_survives_budget_factory(tmp_path):
    stamp = AccountingStamp("offline-simulation", "toy-script-v1", "tokenizer", "price-v1", "2026-10-29")
    ctx = context(tmp_path, stamp=stamp)
    built = default_registry().build(composed_profile(), ctx)
    assert built["budget"].stamp == stamp


def test_registered_hierarchical_budget_uses_explicit_stamp_without_constructor_writes(tmp_path):
    from core.composition.budget import HierarchicalBudget
    stamp = AccountingStamp("offline-simulation", "toy-script-v1", "tokenizer", "price-v1", "2026-10-29")
    ctx = context(tmp_path, stamp=stamp)
    profile = composed_profile()
    profile["budget"] = {"name": "hierarchical", "options": {
        "limits": {"global": {"token": 100}, "direction": {"token": 50}, "candidate": {"token": 20}},
        "reservation": {"token": 10}, "fidelity_rungs": [{"fidelity": "dev"}]}}
    built = default_registry().build(profile, ctx)
    assert isinstance(built["budget"], HierarchicalBudget)
    assert built["budget"].stamp is stamp
    assert built["budget"].state()["global"]["remaining"] == {"token": 100}
    assert not ctx.store.path.exists() and ctx.llm.prompts == []


def test_provider_records_every_call_even_when_a_hook_consumes_only_last_usage():
    class Provider:
        model = "metered-model"
        supplier = "offline"
        def __init__(self):
            self.calls = 0
        def __call__(self, prompt):
            self.calls += 1
            self.last_usage = {"total_tokens": self.calls * 3}
            return prompt
    raw = Provider()
    provider = MeteredProvider(raw)
    provider("first")
    provider("second")
    assert provider.usage_total == 9
    assert take_usage(provider) == 6
    assert provider.usage_total == 9
    assert provider.model == "metered-model" and provider.supplier == "offline"
    assert provider.raw_provider is raw


def test_provider_preserves_known_failure_charge_and_blocks_unknown_usage():
    class Provider:
        def __call__(self, prompt):
            if prompt == "known":
                self.last_usage = {"total_tokens": 7}
            raise RuntimeError("fixture failure")
    provider = MeteredProvider(Provider())
    with pytest.raises(RuntimeError, match="fixture failure"):
        provider("known")
    assert provider.usage_total == 7 and take_usage(provider) == 7
    with pytest.raises(UsageError):
        provider("unknown")
    assert provider.known_usage_total == 7
    with pytest.raises(UsageError, match="unresolved"):
        _ = provider.usage_total
    with pytest.raises(UsageError, match="unresolved"):
        provider("known")
    assert provider.last_usage is None


def test_legacy_domain_exposes_content_binding_and_pure_context_preflight():
    class Solver:
        model = "initial"
        def __call__(self, prompt):
            self.last_usage = {"total_tokens": 0}
            return "#### 1"
    solver = Solver()
    evaluator = GSM8KEvaluator([{"question": "one", "gold": 1}], solver)
    domain = LegacyPromptDomain(evaluator, solver)
    assert domain.evaluator_version == evaluator.evaluator_version
    assert domain.evaluation_context == evaluator.evaluation_context
    domain.validate_context()
    solver.model = "changed"
    with pytest.raises(ValueError, match="configuration changed"):
        domain.validate_context()


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        self.last_usage = {"total_tokens": 7}
        return self.replies.pop(0)


def policy_state(frontier, cycle=0):
    return {"task": "Solve a fixed task", "cycle": cycle,
            "operators": ["draft", "reflective"],
            "frontier": json.loads(frontier.view("json"))}


def test_llm_cycle_plan_controls_parent_operator_and_actual_generation_prompt(tmp_path):
    raw = ScriptedLLM([json.dumps({"operator": "reflective", "parents": ["low"],
                                  "hypotheses": ["Correct the low candidate's arithmetic"]}),
                       "An improved candidate"])
    cfg = composed_profile()
    cfg["policy"] = {"name": "llm_cycles", "options": {"context_window": 2}}
    modules = default_registry().build(cfg, context(tmp_path, llm=raw))
    frontier, policy = modules["frontier"], modules["policy"]
    proposals, evidences = {}, {}
    for candidate_id, score in (("low", 0.1), ("high", 0.9)):
        proposals[candidate_id] = Proposal(Candidate(candidate_id), "original " + candidate_id)
        evidences[candidate_id] = EvidenceRecord(candidate_id,
            EvalResult(EvalStatus.OK, {"dev/score": score}), executor_status="scored")
        frontier.add(proposals[candidate_id].candidate, evidences[candidate_id])
    assert frontier.sample(1, "greedy") == ["high"]
    strategy = asyncio.run(policy.observe(policy_state(frontier), {}))
    parents = asyncio.run(policy.select(frontier, {}))
    assert parents == ["low"]
    hypotheses = asyncio.run(policy.ideate(strategy, proposals["low"], 1))
    request = OperatorRequest("task", "next", 1, (proposals["low"],), (evidences["low"],),
                              strategy={**strategy, "hypotheses": hypotheses})
    index = [spec["name"] for spec in cfg["operators"]].index(strategy["operator"])
    proposal = asyncio.run(modules["operators"][index].propose(request))
    assert proposal.candidate.operator == "reflective"
    assert proposal.candidate.parents == ["low"]
    assert proposal.artifact == "An improved candidate"
    assert "original low" in raw.prompts[1] and hypotheses[0] in raw.prompts[1]
    assert modules["provider"].usage_total == 14 and proposal.cost.tokens_in == 7
    restored = LLMCyclesPolicy(context(tmp_path).scope_context, modules["provider"], context_window=2)
    restored.restore_state(policy.checkpoint_state())
    assert asyncio.run(restored.select(frontier, {})) == ["low"]
    assert asyncio.run(restored.ideate({}, None, 1)) == hypotheses
    assert len(raw.prompts) == 2


@pytest.mark.parametrize("policy_name", ["greedy", "llm_cycles"])
def test_policy_compacts_only_working_context_and_restores_bounded_history(tmp_path, policy_name):
    plan = json.dumps({"operator": "draft", "parents": [], "hypotheses": ["baseline"]})
    raw = ScriptedLLM([plan] * 5)
    cfg = composed_profile()
    cfg["policy"] = {"name": policy_name, "options": {"context_window": 2}}
    modules = default_registry().build(cfg, context(tmp_path, llm=raw))
    frontier, policy = modules["frontier"], modules["policy"]
    evidence = asyncio.run(modules["executor"].execute(
        Proposal(Candidate("persisted"), "durable experience"), EvalRequest("dev"), modules["domain"]))
    frontier.add(Candidate("persisted"), evidence)
    StateApplier(frontier, modules["memory"], context(tmp_path).store).apply_all(
        absorb_bound_evidence(modules, evidence))
    before_memory = modules["memory"].checkpoint_state()
    for cycle in range(5):
        state = policy_state(frontier, cycle)
        state["task"] = "x" * 9000
        state["private"] = "must not enter working history"
        state["frontier"]["nodes"][0]["result"] = {"secret": "private evaluation"}
        asyncio.run(policy.observe(state, {}))
    checkpoint = policy.checkpoint_state()
    assert [entry["cycle"] for entry in checkpoint["history"]] == [3, 4]
    assert all(len(entry["task"]) == 4096 for entry in checkpoint["history"])
    assert "private" not in json.dumps(checkpoint)
    assert modules["memory"].checkpoint_state() == before_memory
    restored = default_registry().build(cfg, context(tmp_path, llm=raw))["policy"]
    restored.restore_state(checkpoint)
    assert restored.checkpoint_state() == checkpoint
    checkpoint["history"][0]["task"] = "external mutation"
    assert restored.checkpoint_state()["history"][0]["task"] != "external mutation"


@pytest.mark.parametrize("reply", [
    "not JSON", '{"operator":"draft","operator":"reflective","parents":[],"hypotheses":["x"]}',
    json.dumps({"operator": "draft", "parents": [], "hypotheses": ["x"], "admit": True}),
    json.dumps({"operator": "unknown", "parents": [], "hypotheses": ["x"]}),
    json.dumps({"operator": "reflective", "parents": ["missing"], "hypotheses": ["x"]}),
    json.dumps({"operator": "draft", "parents": [], "hypotheses": [1]}),
])
def test_invalid_llm_cycle_plan_fails_closed_with_known_provider_charge(tmp_path, reply):
    raw = ScriptedLLM([reply])
    cfg = composed_profile()
    cfg["policy"] = {"name": "llm_cycles"}
    modules = default_registry().build(cfg, context(tmp_path, llm=raw))
    with pytest.raises(ValueError):
        asyncio.run(modules["policy"].observe(policy_state(modules["frontier"]), {}))
    assert modules["provider"].usage_total == 7
    assert modules["frontier"].nodes == {} and not modules["memory"].entries
    assert modules["policy"].checkpoint_state()["strategy"] == {}


@pytest.mark.parametrize("window", [0, -1, True, 2.5, "2"])
def test_policy_context_window_is_validated_before_provider_use(tmp_path, window):
    raw = ScriptedLLM([])
    cfg = composed_profile()
    cfg["policy"] = {"name": "llm_cycles", "options": {"context_window": window}}
    with pytest.raises(ValueError, match="positive integer"):
        default_registry().build(cfg, context(tmp_path, llm=raw))
    assert raw.prompts == []


def test_layered_admission_factory_constructs_controller_and_rejects_unsupported_options_before_calls(tmp_path):
    from core.composition.admission import LayeredAdmissionController
    cfg = composed_profile()
    cfg["admission"] = {"name": "layered", "options": {"call_budget": 4,
        "trigger": {"min_dev_gain": 0.1}, "final_audit": {"isolation": True, "runs": 1}}}
    ctx = context(tmp_path)
    built = default_registry().build(cfg, ctx)
    assert isinstance(built["admission"], LayeredAdmissionController)
    assert built["admission"].remaining_calls == 4
    assert built["admission"].store is ctx.store
    assert not ctx.store.path.exists() and ctx.llm.prompts == []
    cfg["admission"]["options"]["selection"] = "top_k"
    with pytest.raises(ValueError, match="top_k"):
        default_registry().build(cfg, ctx)
    assert not ctx.store.path.exists() and ctx.llm.prompts == []
