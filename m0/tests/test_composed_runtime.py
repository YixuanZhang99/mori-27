"""End-to-end configured execution through Framework, including failure boundaries."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.defaults import GreedyPolicy, PromptOperator, composed_profile, default_registry
from core.composition.contracts import AssemblyConfig
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.llm import UsageError
from core.loop import Framework, LoopConfig
from core.policy.types import MutationOp, StateMutation
from core.tasks.gsm8k import GSM8KEvaluator
from core.x1.checkpoint import RunCheckpoint
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "configured arithmetic prompt optimization"


class CountingLLM(MockLLM):
    def __init__(self):
        self.calls = 0
        self.prompts = []

    def __call__(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        result = super().__call__(prompt)
        if "ADD_HINT_7" in prompt and "hint_7" not in result:
            result += "\nhint_7"
        return result


class CountingEvaluator:
    evaluator_version = "det-v1"
    evaluation_context = ""

    def __init__(self, tokens=13):
        self.calls = 0
        self.tokens = tokens

    def __call__(self, candidate_id, head_sha, prompt):
        self.calls += 1
        self.last_usage = {"total_tokens": self.tokens}
        return toy_evaluator(candidate_id, head_sha, prompt)


def config(**kwargs):
    values = {"total_budget": 30_000, "reeval_floor": 0, "intent_cost": 2_000,
              "max_generations": 3, "baseline_every": 2}
    values.update(kwargs)
    return LoopConfig(**values)


def framework(path, *, profile=None, llm=None, evaluator=None, cfg=None, registry=None):
    return Framework.from_profile(
        composed_profile() if profile is None else profile,
        CountingLLM() if llm is None else llm,
        CountingEvaluator() if evaluator is None else evaluator,
        config() if cfg is None else cfg, str(path),
        component_registry=default_registry() if registry is None else registry)


def records(fw, kind):
    return [row["payload"] for row in fw.store.read(kind)]


def test_default_composition_completes_real_optimization_and_accounts_every_call(tmp_path):
    llm, evaluator = CountingLLM(), CountingEvaluator()
    fw = framework(tmp_path, llm=llm, evaluator=evaluator)
    result = fw.evolve(TASK)
    assert result["runtime"] == "composed-v2"
    assert result["cycles"] == llm.calls == evaluator.calls == 4
    assert result["best_score"] == pytest.approx(7 / 12)
    assert "hint_4" in result["best_prompt"] and "hint_6" in result["best_prompt"]
    assert len(result["accepted_candidate_ids"]) == 4
    assert sum(result["ledger"]["spent"].values()) == 4 * 1_013
    assert fw.inspect()["memory_entries"] == 4
    evidence = records(fw, "composed_evidence")
    assert [row["evidence"]["eval_result"]["status"] for row in evidence] == ["ok"] * 4
    assert [row["evidence"]["eval_result"]["fidelity"] for row in evidence] == ["dev"] * 4
    assert all(row["proposal"]["cost"]["tokens_in"] == 1000 for row in evidence)
    assert all(row["evidence"]["eval_result"]["cost"]["tokens_in"] == 13 for row in evidence)
    assert records(fw, "run_start")[0]["manifest"]["assembly"]["name"] == "composed-greedy"


def test_registered_profile_name_uses_configured_framework_entry_point(tmp_path):
    fw = framework(tmp_path, profile="composed_prompt", cfg=config(max_generations=0))
    assert fw.evolve(TASK)["runtime"] == "composed-v2"
    assert fw.inspect()["assembly"]["schema_version"] == 1


class OldestParentPolicy(GreedyPolicy):
    async def select(self, frontier, budget):
        eligible = [node for node in frontier.nodes.values()
                    if node.status == "merged" and node.eval_status == "ok"]
        eligible.sort(key=lambda node: (node.created_cycle, node.id))
        return [eligible[0].id] if eligible else []


def test_policy_configuration_changes_actual_lineage_and_optimization_result(tmp_path):
    greedy = framework(tmp_path / "greedy")
    greedy_result = greedy.evolve(TASK)
    registry = default_registry()
    registry.register("policy", "oldest", lambda ctx, opts: OldestParentPolicy(ctx.scope_context))
    profile = composed_profile()
    profile["policy"] = {"name": "oldest"}
    oldest = framework(tmp_path / "oldest", profile=profile, registry=registry)
    oldest_result = oldest.evolve(TASK)
    assert greedy_result["best_score"] == pytest.approx(7 / 12)
    assert oldest_result["best_score"] == pytest.approx(5 / 12)
    greedy_rows, oldest_rows = records(greedy, "composed_evidence"), records(oldest, "composed_evidence")
    assert greedy_rows[2]["proposal"]["candidate"]["parents"] != oldest_rows[2]["proposal"]["candidate"]["parents"]
    assert oldest_rows[2]["proposal"]["candidate"]["parents"] == [oldest_rows[0]["proposal"]["candidate"]["id"]]


def test_skill_configuration_reaches_provider_and_changes_evaluated_artifact(tmp_path):
    plain = framework(tmp_path / "plain", cfg=config(max_generations=0))
    plain_result = plain.evolve(TASK)
    profile = composed_profile()
    profile["skills"] = [{"name": "instruction", "options": {"text": "ADD_HINT_7"}}]
    llm = CountingLLM()
    skilled = framework(tmp_path / "skilled", profile=profile, llm=llm,
                        cfg=config(max_generations=0))
    skilled_result = skilled.evolve(TASK)
    assert "ADD_HINT_7" in llm.prompts[0]
    assert "hint_7" in skilled_result["best_prompt"]
    assert skilled_result["best_score"] > plain_result["best_score"]


def test_invalid_options_and_factory_construction_errors_make_no_provider_calls(tmp_path):
    for case in ("options", "factory"):
        llm, evaluator = CountingLLM(), CountingEvaluator()
        profile, registry = composed_profile(), default_registry()
        if case == "options":
            profile["admission"]["options"] = {"margin": -1}
        else:
            def broken_factory(ctx, options):
                raise ValueError("operator factory refused configuration")
            registry.register("operator", "broken", broken_factory)
            profile["operators"] = [{"name": "broken"}]
        with pytest.raises(ValueError):
            fw = framework(tmp_path / case, profile=profile, llm=llm,
                           evaluator=evaluator, registry=registry)
            fw.evolve(TASK)
        assert llm.calls == evaluator.calls == 0
        assert not (tmp_path / case / "x1.jsonl").exists()


class CanonicalCostDomain:
    evaluator_version = "canonical-v1"
    evaluation_context = "sha256:" + "a" * 64

    def validate_request(self, request):
        request.validate()

    async def evaluate(self, proposal, request):
        from core.composition.evaluation import EvaluationContract, binding_for
        return EvalResult(EvalStatus.OK, {"dev/score": 0.75},
                          cost=CostVec(tokens_in=5, tokens_out=7, eval_count=1),
                          fidelity=request.fidelity, text_feedback="canonical domain evidence",
                          contract=EvaluationContract(binding_for(proposal, request,
                              evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context), ("token", "eval_count")))


def test_native_canonical_domain_cost_is_settled_without_legacy_evaluator(tmp_path):
    registry = default_registry()
    registry.register("domain", "canonical-cost", lambda ctx, opts: CanonicalCostDomain())
    profile = composed_profile()
    profile["domain"] = {"name": "canonical-cost"}
    evaluator = CountingEvaluator()
    fw = framework(tmp_path, profile=profile, registry=registry, evaluator=evaluator,
                   cfg=config(max_generations=0))
    result = fw.evolve(TASK)
    assert result["best_score"] == 0.75
    assert evaluator.calls == 0
    assert result["ledger"]["spent"]["explore"] == 1_012
    assert records(fw, "composed_evidence")[0]["evidence"]["eval_result"]["cost"]["tokens_out"] == 7


class KnownFailureLLM(CountingLLM):
    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {"total_tokens": 7}
        raise RuntimeError("offline known-charge failure")


class UnknownUsageLLM(CountingLLM):
    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = None
        return "content with no trustworthy usage"


def test_known_failed_proposal_is_failure_evidence_with_real_cost(tmp_path):
    llm, evaluator = KnownFailureLLM(), CountingEvaluator()
    fw = framework(tmp_path, llm=llm, evaluator=evaluator, cfg=config(max_generations=0))
    result = fw.evolve(TASK)
    assert llm.calls == 1 and evaluator.calls == 0
    assert result["best_candidate_id"] is None
    assert result["ledger"]["spent"]["explore"] == 7
    evidence = records(fw, "composed_evidence")[0]["evidence"]
    assert evidence["eval_result"]["status"] == "failed_to_run"
    assert records(fw, "composed_decision")[0]["decision"]["admit"] is False
    assert {entry["entry_kind"] for entry in records(fw, "ledger")} == {"reserve", "settle", "reconcile_delta"}


def test_unknown_usage_retains_reservation_and_resume_refuses_reexecution(tmp_path):
    llm, evaluator = UnknownUsageLLM(), CountingEvaluator()
    fw = framework(tmp_path, llm=llm, evaluator=evaluator, cfg=config(max_generations=0))
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    assert llm.calls == 1 and evaluator.calls == 0
    assert [entry["entry_kind"] for entry in records(fw, "ledger")] == ["reserve"]
    assert not records(fw, "composed_decision")
    before = fw.store.path.read_bytes()
    replacement, replacement_evaluator = CountingLLM(), CountingEvaluator()
    resumed = framework(tmp_path, llm=replacement, evaluator=replacement_evaluator,
                        cfg=config(max_generations=0, resume_from_checkpoint=True))
    with pytest.raises(RuntimeError, match="unfinished composed cycle"):
        resumed.evolve(TASK)
    assert replacement.calls == replacement_evaluator.calls == 0
    assert fw.store.path.read_bytes() == before


def test_unfunded_cycle_does_not_call_any_paid_component(tmp_path):
    llm, evaluator = CountingLLM(), CountingEvaluator()
    fw = framework(tmp_path, llm=llm, evaluator=evaluator,
                   cfg=config(total_budget=1_000, intent_cost=2_000, max_generations=0))
    assert fw.evolve(TASK)["cycles"] == 0
    assert llm.calls == evaluator.calls == 0
    assert not records(fw, "composed_evidence")


@pytest.mark.parametrize("policy_name", ["greedy", "llm_cycles"])
def test_boundary_resume_matches_uninterrupted_and_replay_attempts_are_isolated(tmp_path, policy_name):
    profile = composed_profile()
    profile["policy"] = {"name": policy_name, "options": {"context_window": 2}}
    llm_type = CountingLLM if policy_name == "greedy" else PlanningLLM
    reference = framework(tmp_path / "reference", profile=profile, llm=llm_type(),
                          cfg=config(max_generations=4))
    expected = reference.evolve(TASK)
    interrupted = framework(tmp_path / "resume", profile=profile, llm=llm_type(),
                            cfg=config(max_generations=4, stop_after_generation=1))
    assert interrupted.evolve(TASK)["cycles"] == 2
    llm, evaluator = llm_type(), CountingEvaluator()
    resumed = framework(tmp_path / "resume", llm=llm, evaluator=evaluator,
                        profile=profile, cfg=config(max_generations=4, resume_from_checkpoint=True))
    actual = resumed.evolve(TASK)
    assert actual == expected
    assert evaluator.calls == 3
    assert llm.calls == (3 if policy_name == "greedy" else 6)
    initial_calls = (llm.calls, evaluator.calls)
    first = resumed.replay()
    first_dir = Path(first["replay_certificate"]["replay_workdir"])
    first_files = {str(path.relative_to(first_dir)): path.read_bytes()
                   for path in first_dir.rglob("*") if path.is_file()}
    second = resumed.replay()
    assert first["replay_certificate"]["passed"] and second["replay_certificate"]["passed"]
    assert first["replay_certificate"]["replay_workdir"] != second["replay_certificate"]["replay_workdir"]
    assert {str(path.relative_to(first_dir)): path.read_bytes()
            for path in first_dir.rglob("*") if path.is_file()} == first_files
    assert (llm.calls, evaluator.calls) == initial_calls
    assert len(records(resumed, "replay_certificate")) == 2


def test_caller_profile_changes_do_not_change_frozen_manifest_or_execution(tmp_path):
    profile = composed_profile()
    profile["skills"] = [{"name": "instruction", "options": {"text": "ADD_HINT_7"}}]
    frozen = copy.deepcopy(profile)
    fw = framework(tmp_path, profile=profile, cfg=config(max_generations=0))
    profile["skills"][0]["options"]["text"] = "CALLER_MUTATION"
    profile["policy"]["name"] = "not-registered"
    result = fw.evolve(TASK)
    manifest = records(fw, "run_start")[0]["manifest"]["assembly"]
    assert manifest == AssemblyConfig.from_dict(frozen).to_dict()
    assert "hint_7" in result["best_prompt"]


class NumericSolver:
    model = "offline-numeric-v1"
    supplier = "offline-simulation"

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {"total_tokens": 2}
        return "#### 1"


def test_bound_domain_drift_fails_before_proposer_and_solver_calls(tmp_path):
    solver, llm = NumericSolver(), CountingLLM()
    evaluator = GSM8KEvaluator([{"question": "one?", "gold": 1}], solver)
    fw = framework(tmp_path, llm=llm, evaluator=evaluator, cfg=config(max_generations=0))
    solver.model = "changed-model"
    with pytest.raises(ValueError, match="configuration changed"):
        fw.evolve(TASK)
    assert llm.calls == solver.calls == 0
    assert not fw.store.path.exists()


def test_resume_cannot_swap_bound_domain_data_under_same_component_name(tmp_path):
    first = GSM8KEvaluator([{"question": "original question", "gold": 1}], NumericSolver())
    fw = framework(tmp_path, evaluator=first,
                   cfg=config(max_generations=2, stop_after_generation=0))
    fw.evolve(TASK)
    before = fw.store.path.read_bytes()
    solver, llm = NumericSolver(), CountingLLM()
    changed = GSM8KEvaluator([{"question": "changed question", "gold": 1}], solver)
    resumed = framework(tmp_path, llm=llm, evaluator=changed,
                        cfg=config(max_generations=2, resume_from_checkpoint=True))
    with pytest.raises(ValueError, match="manifest is incompatible"):
        resumed.evolve(TASK)
    assert llm.calls == solver.calls == 0
    assert fw.store.path.read_bytes() == before


class HookLLM(CountingLLM):
    def __call__(self, prompt):
        if prompt.startswith("policy-call"):
            self.calls += 1
            self.prompts.append(prompt)
            self.last_usage = {"total_tokens": 11 if prompt.endswith("one") else 17}
            return "policy observation"
        return super().__call__(prompt)


class CallingPolicy(GreedyPolicy):
    def __init__(self, scope, provider):
        super().__init__(scope)
        self.provider = provider

    async def observe(self, state, budget):
        self.provider("policy-call one")
        self.provider("policy-call two")
        return await super().observe(state, budget)


def test_multiple_provider_calls_inside_one_policy_hook_are_all_metered(tmp_path):
    registry, profile = default_registry(), composed_profile()
    registry.register("policy", "calling", lambda ctx, opts: CallingPolicy(ctx.scope_context, ctx.llm))
    profile["policy"] = {"name": "calling"}
    llm = HookLLM()
    fw = framework(tmp_path, profile=profile, registry=registry, llm=llm,
                   cfg=config(max_generations=0))
    result = fw.evolve(TASK)
    assert llm.calls == 3
    assert result["ledger"]["spent"]["explore"] == 1000 + 13 + 11 + 17


@pytest.mark.parametrize("mutation", [MutationOp.MERGE, MutationOp.PRUNE, MutationOp.ADD_NODE,
                                      "score", "status", "eval_status"])
def test_policy_cannot_bypass_gate_or_rewrite_execution_authority(tmp_path, mutation):
    class EscapingPolicy(GreedyPolicy):
        async def absorb(self, evidence):
            if isinstance(mutation, MutationOp):
                return [StateMutation(mutation, evidence.candidate_id, {}, "forged decision")]
            value = "failed_to_run" if mutation == "eval_status" else 999
            return [StateMutation(MutationOp.UPDATE_NODE, evidence.candidate_id,
                                  {mutation: value}, "forged execution state")]
    registry, profile = default_registry(), composed_profile()
    registry.register("policy", "escape", lambda ctx, opts: EscapingPolicy(ctx.scope_context))
    profile["policy"] = {"name": "escape"}
    fw = framework(tmp_path, profile=profile, registry=registry, cfg=config(max_generations=0))
    with pytest.raises(ValueError, match="policy"):
        fw.evolve(TASK)
    assert not records(fw, "state_mutation")
    assert not records(fw, "composed_decision")
    assert records(fw, "composed_cycle_failed")[0]["known_tokens"] == 1_013
    assert [row["settled"] for row in records(fw, "ledger")
            if row["entry_kind"] == "settle"] == [1_013]


def test_policy_receives_detached_frontier_and_evidence_views(tmp_path):
    class MutatingViewsPolicy(GreedyPolicy):
        async def select(self, frontier, budget):
            chosen = await super().select(frontier, budget)
            for node in frontier.nodes.values():
                node.score = 999
                node.cost["tokens_in"] = 999
            return chosen

        async def absorb(self, evidence):
            evidence.eval_result.metrics["dev/score"] = 999
            return await super().absorb(evidence)
    registry, profile = default_registry(), composed_profile()
    registry.register("policy", "mutating-views", lambda ctx, opts: MutatingViewsPolicy(ctx.scope_context))
    profile["policy"] = {"name": "mutating-views"}
    fw = framework(tmp_path, profile=profile, registry=registry, cfg=config(max_generations=1))
    result = fw.evolve(TASK)
    assert result["best_score"] == pytest.approx(5 / 12)
    payload = RunCheckpoint.load(tmp_path / "checkpoint.json").payload
    nodes = json.loads(payload["frontier_checkpoint"])["payload"]["nodes"]
    assert all(node["score"] < 1 and node["cost"]["tokens_in"] == 13 for node in nodes)
    assert all(row["evidence"]["eval_result"]["metrics"]["dev/score"] < 1
               for row in records(fw, "composed_evidence"))


@pytest.mark.parametrize("rejection", ["execution_failure", "admission_rejection"])
def test_policy_cannot_select_pruned_parents_or_forge_eligibility_before_next_call(tmp_path, rejection):
    class SelectPrunedPolicy(GreedyPolicy):
        async def select(self, frontier, budget):
            for node in frontier.nodes.values():
                if node.status == "pruned":
                    node.status, node.eval_status, node.score = "merged", "ok", 1.0
                    return [node.id]
            return await super().select(frontier, budget)
    registry, profile = default_registry(), composed_profile()
    registry.register("policy", "select-pruned", lambda ctx, opts: SelectPrunedPolicy(ctx.scope_context))
    profile["policy"] = {"name": "select-pruned"}
    profile["admission"]["options"] = {"margin": 100}
    llm = KnownFailureLLM() if rejection == "execution_failure" else CountingLLM()
    evaluator = CountingEvaluator()
    fw = framework(tmp_path, profile=profile, registry=registry, llm=llm,
                   evaluator=evaluator, cfg=config(max_generations=2))
    with pytest.raises(ValueError, match="policy selected invalid parents"):
        fw.evolve(TASK)
    assert llm.calls == (1 if rejection == "execution_failure" else 2)
    assert evaluator.calls == (0 if rejection == "execution_failure" else 2)
    assert len(records(fw, "composed_evidence")) == llm.calls
    assert records(fw, "composed_decision")[-1]["decision"]["admit"] is False
    assert records(fw, "composed_cycle_failed")[-1]["known_tokens"] == 0


@pytest.mark.parametrize("kind", ["policy", "provider"])
def test_replay_refuses_factories_reusing_live_components_before_new_provider_calls(tmp_path, kind):
    registry, profile, shared = default_registry(), composed_profile(), {}
    def factory(ctx, options):
        if "component" not in shared:
            shared["component"] = GreedyPolicy(ctx.scope_context) if kind == "policy" else ctx.llm
        return shared["component"]
    registry.register(kind, "shared", factory)
    profile[kind] = {"name": "shared"}
    llm, evaluator = CountingLLM(), CountingEvaluator()
    fw = framework(tmp_path, profile=profile, registry=registry, llm=llm,
                   evaluator=evaluator, cfg=config(max_generations=1))
    fw.evolve(TASK)
    counts = llm.calls, evaluator.calls
    with pytest.raises(RuntimeError, match="configured replay execution failed"):
        fw.replay()
    assert (llm.calls, evaluator.calls) == counts
    assert fw.inspect()["replay_certificate"]["passed"] is False


class PlanningLLM(CountingLLM):
    def __call__(self, prompt):
        if prompt.startswith("Plan one research cycle."):
            self.calls += 1
            self.prompts.append(prompt)
            self.last_usage = {"total_tokens": 19}
            return json.dumps({"operator": "draft", "parents": [],
                               "hypotheses": ["Establish an independent baseline"]})
        return super().__call__(prompt)


def test_llm_cycles_policy_selects_actual_operator_and_persists_bounded_context(tmp_path):
    greedy = framework(tmp_path / "greedy", cfg=config(max_generations=2))
    greedy_result = greedy.evolve(TASK)
    profile = composed_profile()
    profile["policy"] = {"name": "llm_cycles", "options": {"context_window": 2}}
    llm, evaluator = PlanningLLM(), CountingEvaluator()
    planned = framework(tmp_path / "planned", profile=profile, llm=llm, evaluator=evaluator,
                        cfg=config(max_generations=2))
    result = planned.evolve(TASK)
    evidence = records(planned, "composed_evidence")
    assert [row["proposal"]["candidate"]["operator"] for row in evidence] == ["draft"] * 3
    assert all(row["proposal"]["candidate"]["parents"] == [] for row in evidence)
    assert len({row["proposal"]["artifact"] for row in evidence}) == 1
    assert result["best_score"] < greedy_result["best_score"]
    assert len(result["accepted_candidate_ids"]) == 1
    assert llm.calls == 6 and evaluator.calls == 3
    assert sum(result["ledger"]["spent"].values()) == 3 * (19 + 1_000 + 13)
    checkpoint = RunCheckpoint.load(tmp_path / "planned" / "checkpoint.json").payload
    policy_state = checkpoint["module_states"]["policy:0"]
    assert [entry["cycle"] for entry in policy_state["history"]] == [1, 2]
    assert planned.inspect()["memory_entries"] == 3
    assert planned.replay()["replay_certificate"]["passed"]
    assert llm.calls == 6 and evaluator.calls == 3


def test_operator_receives_detached_parent_proposals_and_evidence(tmp_path):
    class ParentMutator(PromptOperator):
        async def propose(self, request):
            for parent in request.parents:
                parent.candidate.parents.append("forged-previous-lineage")
            for evidence in request.evidence:
                evidence.eval_result.metrics["dev/score"] = 0.0
            return await super().propose(request)
    registry, profile = default_registry(), composed_profile()
    registry.register("operator", "parent-mutator", lambda ctx, opts:
                      ParentMutator(ctx.llm, "reflective"))
    profile["operators"][1] = {"name": "parent-mutator"}
    fw = framework(tmp_path, profile=profile, registry=registry, cfg=config(max_generations=1))
    fw.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / "checkpoint.json").payload
    first = records(fw, "composed_evidence")[0]
    candidate_id = first["proposal"]["candidate"]["id"]
    assert payload["proposals"][candidate_id]["candidate"]["parents"] == []
    assert payload["evidence"][candidate_id]["eval_result"]["metrics"]["dev/score"] > 0
