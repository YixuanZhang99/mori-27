"""Configured M7 constructs once through the public Framework entry point."""
import json
from dataclasses import asdict

import pytest

from core.composition.defaults import composed_profile, default_registry
from core.composition.strategies import GreedyPolicy
from core.loop import Framework, LoopConfig
from test_composed_budget import Domain, Provider, TASK, options, physical_operations


class ConstructorProvider(Provider):
    def __init__(self, *, changed_hypothesis=False, forbidden=False):
        super().__init__()
        self.changed_hypothesis, self.forbidden = changed_hypothesis, forbidden

    def __call__(self, prompt):
        assert not self.forbidden, "recorded replay generated again"
        super().__call__(prompt)
        request = json.loads(prompt)
        return json.dumps({"artifact": request["role"]["name"] + ":" + str(self.generation_index),
            "hypothesis": "Use a different hypothesis" if self.changed_hypothesis else request["hypothesis"]})


class ForbiddenDomain(Domain):
    async def evaluate(self, *args):
        raise AssertionError("recorded replay evaluated again")


def profile(*, role="general", frozen=True, projection=None):
    value = composed_profile()
    value.update(schema_version=2, domain={"name": "native"},
        budget={"name": "hierarchical", "options": options()},
        execution={"schema_version": 1,
            "spec": {"role": role, "hypothesis_frozen": frozen,
                     "context_projection": ["memory", "grounding"] if projection is None else projection},
            "constructor": {"name": "prompt", "options": {}}})
    return value


def build(path, *, assembly=None, provider=None, domain=None, generations=1,
          stop=None, resume=False, registry=None):
    cfg = LoopConfig(max_generations=generations, total_budget=100000, intent_cost=2000,
        reeval_floor=0, baseline_every=2, stop_after_generation=stop, resume_from_checkpoint=resume)
    return Framework.from_profile(assembly or profile(), provider or ConstructorProvider(), domain or Domain(),
        cfg, str(path), component_registry=registry or default_registry())


def records(fw, kind):
    return [row["payload"] for row in fw.store.read(kind)]


def test_typed_legacy_configuration_rejects_unparsed_execution():
    from dataclasses import replace
    from core.composition.contracts import AssemblyConfig

    original = AssemblyConfig.from_dict(composed_profile())
    with pytest.raises(ValueError, match="schema 1 cannot enable"):
        replace(original, execution=profile()["execution"],
                budget=AssemblyConfig.from_dict(profile()).budget)


def test_public_v9_role_directs_real_generation_and_charges_one_node_per_build(tmp_path):
    provider = ConstructorProvider()
    fw = build(tmp_path, assembly=profile(role="coder"), provider=provider)
    result = fw.evolve(TASK)
    assert result["runtime"] == "composed-v9-m7"
    assert provider.calls == 2
    assert all(json.loads(prompt)["role"]["name"] == "coder" for prompt in provider.prompts)
    assert [v["construction_result"]["artifact"] for v in records(fw, "materialization_completed")] == ["coder:1", "coder:2"]
    operations = physical_operations(fw)
    assert sum(o["actual"]["node"] for o in operations) == 2
    assert sum(o["actual"]["eval_count"] for o in operations) == 2
    assert sum(o["actual"]["token"] for o in operations) == 24


def test_all_held_out_evaluations_reuse_the_one_materialized_artifact(tmp_path):
    assembly = profile()
    assembly["admission"] = {"name": "layered", "options": {}}
    provider, domain = ConstructorProvider(), Domain()
    fw = build(tmp_path, assembly=assembly, provider=provider, domain=domain, generations=0)
    fw.evolve(TASK)
    assert provider.calls == len(records(fw, "materialization_completed")) == 1
    assert {call["request"]["split_id"] for call in domain.calls} == {"dev", "admission", "final_audit"}
    assert {call["artifact"] for call in domain.calls} == {"general:1"}


def test_free_hypothesis_is_the_scored_and_checkpointed_hypothesis(tmp_path):
    fw = build(tmp_path, assembly=profile(frozen=False),
        provider=ConstructorProvider(changed_hypothesis=True), generations=0)
    fw.evolve(TASK)
    node = next(iter(fw._composed.frontier.nodes.values()))
    assert node.hypothesis == "Use a different hypothesis"
    outcome = records(fw, "materialization_completed")[0]["construction_result"]
    assert outcome["initial_hypothesis"] != outcome["effective_hypothesis"] == node.hypothesis


def test_frozen_hypothesis_failure_keeps_cost_without_fabricating_evaluation(tmp_path):
    domain = Domain()
    fw = build(tmp_path, provider=ConstructorProvider(changed_hypothesis=True), domain=domain, generations=0)
    fw.evolve(TASK)
    assert domain.calls == [] and records(fw, "materialization_completed") == []
    operations = physical_operations(fw)
    assert sum(o["actual"]["token"] for o in operations) == 5
    assert sum(o["actual"]["node"] for o in operations) == 1
    assert sum(o["actual"]["eval_count"] for o in operations) == 0
    assert next(iter(fw._composed.frontier.nodes.values())).eval_status == "failed_to_run"


def test_excluded_grounding_cannot_enter_through_echo_policy_or_static_skill(tmp_path):
    class Echo(GreedyPolicy):
        async def observe(self, state, budget):
            self.observed = json.dumps(state, sort_keys=True)
            return await super().observe(state, budget)

        async def ideate(self, context, parent, k):
            return [{"hypothesis": self.observed + json.dumps(context, sort_keys=True)}]

    registry = default_registry()
    registry.register("policy", "echo", lambda ctx, opts: Echo(ctx.scope_context))
    source = tmp_path / "source.txt"
    source.write_text("EXCLUDED_GROUNDING_SENTINEL")
    assembly = profile(projection=[])
    assembly.update(mode="research", policy={"name": "echo"},
        knowledge={"name": "local_files", "options": {"ground_files": [{"path": str(source)}], "audit_files": []}},
        skills=[{"name": "instruction", "options": {"text": "Preserve this static instruction"}}])
    provider = ConstructorProvider()
    fw = build(tmp_path / "run", assembly=assembly, provider=provider, registry=registry)
    fw.evolve(TASK)
    assert "EXCLUDED_GROUNDING_SENTINEL" in json.dumps(records(fw, "composed_context"))
    assert "EXCLUDED_GROUNDING_SENTINEL" not in json.dumps(provider.prompts)
    assert all("Preserve this static instruction" in prompt for prompt in provider.prompts)


def test_pause_resume_reuses_saved_artifacts_and_replay_makes_zero_live_calls(tmp_path):
    first = build(tmp_path, generations=2, stop=0)
    first.evolve(TASK)
    raw = ConstructorProvider()
    resumed = build(tmp_path, provider=raw, generations=2, resume=True)
    resumed.evolve(TASK)
    assert raw.calls == 2 and len(records(resumed, "materialization_completed")) == 3
    replay = resumed.replay(adapter_factory=lambda path, store: (
        ConstructorProvider(forbidden=True), ForbiddenDomain()))
    assert replay["replay_certificate"]["passed"]
    assert replay["replay_certificate"]["mode"] == "recorded_outcomes"


@pytest.mark.parametrize("defect", ["role", "projection", "schema", "budget"])
def test_invalid_execution_contract_fails_before_model_use(tmp_path, defect):
    assembly = profile()
    if defect == "role":
        assembly["execution"]["spec"]["role"] = "unregistered-role"
    elif defect == "projection":
        assembly["execution"]["spec"]["context_projection"] = ["summary"]
    elif defect == "schema":
        assembly["schema_version"] = 1
    else:
        assembly["budget"] = {"name": "tokens"}
    raw = ConstructorProvider()
    with pytest.raises(ValueError):
        build(tmp_path, assembly=assembly, provider=raw).evolve(TASK)
    assert raw.calls == 0


def test_population_uses_declarative_crossover_and_replays_the_same_artifacts(tmp_path):
    from test_composed_population import assembly as population_assembly, Domain as PopulationDomain
    assembly = population_assembly()
    assembly.update(schema_version=2, execution=profile()["execution"])
    raw = ConstructorProvider()
    fw = build(tmp_path, assembly=assembly, provider=raw, domain=PopulationDomain(), generations=3)
    fw.evolve(TASK)
    requests = [json.loads(prompt) for prompt in raw.prompts]
    assert [request["recipe"]["kind"] for request in requests] == ["draft", "draft", "crossover", "crossover"]
    assert all(len(request["recipe"]["parent_artifacts"]) == 2 for request in requests[2:])
    assert fw.replay()["replay_certificate"]["passed"]


def test_explicit_hypothesis_constrains_default_ideation_and_rejects_a_conflicting_policy(tmp_path):
    assembly = profile()
    assembly["execution"]["spec"]["hypothesis"] = "Cache the repeated computation"
    raw = ConstructorProvider()
    fw = build(tmp_path / "good", assembly=assembly, provider=raw, generations=0)
    fw.evolve(TASK)
    assert json.loads(raw.prompts[0])["hypothesis"] == "Cache the repeated computation"

    class Conflicting(GreedyPolicy):
        async def ideate(self, *args):
            return [{"hypothesis": "Change an unrelated parameter"}]
    registry = default_registry()
    registry.register("policy", "conflicting", lambda ctx, opts: Conflicting(ctx.scope_context))
    assembly["policy"] = {"name": "conflicting"}
    other = ConstructorProvider()
    fw = build(tmp_path / "bad", assembly=assembly, provider=other, registry=registry, generations=0)
    with pytest.raises(ValueError, match="hypothesis"):
        fw.evolve(TASK)
    assert other.calls == 0 and fw._composed.budget.state()["open_intents"] == []


def test_construction_integrity_failure_stops_after_settling_the_real_bill(tmp_path):
    from core.composition.construction_recipes import DEFAULT_ROLES
    from core.composition.construction import ConstructionPlan, PromptMaterializer, _json

    class WrongPlan(PromptMaterializer):
        async def construct(self, plan, provider):
            value = plan.to_dict()
            value["spec"]["role"] = "coder"
            value["role"] = asdict(DEFAULT_ROLES["coder"])
            return await super().construct(ConstructionPlan(_json(value)), provider)

    registry = default_registry()
    registry.register("constructor", "wrong-plan", lambda ctx, opts: WrongPlan(DEFAULT_ROLES),
        execution={"schema_version": 1, "roles": {key: asdict(role) for key, role in DEFAULT_ROLES.items()}})
    assembly = profile()
    assembly["execution"]["constructor"] = {"name": "wrong-plan"}
    raw, domain = ConstructorProvider(), Domain()
    fw = build(tmp_path, assembly=assembly, provider=raw, domain=domain, registry=registry, generations=0)
    with pytest.raises(ValueError, match="integrity"):
        fw.evolve(TASK)
    assert raw.calls == 1 and domain.calls == []
    assert fw._composed.budget.state()["global"]["used"] == {"token": 5, "node": 1, "eval_count": 0}
    assert fw._composed.budget.state()["open_intents"] == []


def test_registered_custom_role_changes_the_actual_constructor_input(tmp_path):
    from core.composition.construction import PromptMaterializer, RoleDefinition
    role = RoleDefinition("specialist", "custom-2", "Produce a concise invariant analysis")
    registry = default_registry()
    registry.register("constructor", "specialized", lambda ctx, opts: PromptMaterializer({role.name: role}),
        execution={"schema_version": 1, "roles": {role.name: asdict(role)}})
    assembly = profile(role="specialist")
    assembly["execution"]["constructor"] = {"name": "specialized"}
    raw = ConstructorProvider()
    fw = build(tmp_path, assembly=assembly, provider=raw, registry=registry, generations=0)
    fw.evolve(TASK)
    assert json.loads(raw.prompts[0])["role"] == {"name": "specialist", "version": "custom-2",
        "instructions": "Produce a concise invariant analysis"}


def test_constructor_factory_has_no_live_provider_domain_or_main_journal(tmp_path):
    from core.composition.construction_recipes import DEFAULT_ROLES
    from core.composition.construction import PromptMaterializer
    observed = []
    def factory(ctx, opts):
        observed.append((ctx.llm, ctx.evaluator, list(ctx.store.read())))
        return PromptMaterializer(DEFAULT_ROLES)
    registry = default_registry()
    registry.register("constructor", "scoped", factory,
        execution={"schema_version": 1, "roles": {key: asdict(role) for key, role in DEFAULT_ROLES.items()}})
    assembly = profile()
    assembly["execution"]["constructor"] = {"name": "scoped"}
    build(tmp_path, assembly=assembly, registry=registry, stop=0).evolve(TASK)
    build(tmp_path, assembly=assembly, registry=registry, resume=True).evolve(TASK)
    assert observed == [(None, None, []), (None, None, [])]


@pytest.mark.parametrize("cut", ["composed_provider_completed", "materialization_completed", "governed_evaluation_completed"])
def test_public_resume_adopts_original_construction_and_evaluation(tmp_path, monkeypatch, cut):
    from core.composition.recovery import ContinuationStore
    from test_materialization_recovery import Crash
    original = ContinuationStore._write
    def interrupted(self, row):
        original(self, row)
        if row["kind"] == cut:
            raise Crash(cut)
    monkeypatch.setattr(ContinuationStore, "_write", interrupted)
    first, raw = None, ConstructorProvider()
    first = build(tmp_path, provider=raw, generations=0)
    with pytest.raises(Crash):
        first.evolve(TASK)
    monkeypatch.setattr(ContinuationStore, "_write", original)
    other = ConstructorProvider(forbidden=True)
    restored = build(tmp_path, provider=other, generations=0, resume=True,
                     domain=ForbiddenDomain() if cut == "governed_evaluation_completed" else Domain())
    restored.evolve(TASK)
    assert raw.calls == 1 and other.calls == 0
    assert len(records(restored, "materialization_completed")) == 1
    assert sum(o["actual"]["token"] for o in physical_operations(restored)) == 12
    assert restored.replay(adapter_factory=lambda p, s: (ConstructorProvider(forbidden=True), ForbiddenDomain()))[
        "replay_certificate"]["passed"]


def test_unknown_build_usage_stays_reserved_and_never_reissues_a_model_call(tmp_path):
    from core.llm import UsageError
    class Unknown(ConstructorProvider):
        def __call__(self, prompt):
            output = super().__call__(prompt)
            self.last_usage = None
            return output
    raw = Unknown()
    first = build(tmp_path, provider=raw, generations=0)
    with pytest.raises(UsageError):
        first.evolve(TASK)
    assert first._composed.budget.state()["global"]["reserved"] == {"token": 10, "node": 1, "eval_count": 0}
    other = ConstructorProvider(forbidden=True)
    original = (tmp_path / "x1.jsonl").read_bytes()
    resumed = build(tmp_path, provider=other, generations=0, resume=True)
    with pytest.raises((UsageError, ValueError), match="completion|continuation"):
        resumed.evolve(TASK)
    assert raw.calls == 1 and other.calls == 0
    assert (tmp_path / "x1.jsonl").read_bytes() == original
    assert resumed._composed.budget.state()["global"]["reserved"] == {"token": 10, "node": 1, "eval_count": 0}


def test_changed_fidelity_baseline_uses_the_incumbents_original_artifact(tmp_path):
    assembly = profile()
    assembly["budget"]["options"]["fidelity_rungs"] = [
        {"fidelity": "shallow", "split_id": "dev", "seed_set": [11]},
        {"fidelity": "full", "split_id": "dev", "seed_set": [11, 29]}]
    raw, domain = ConstructorProvider(), Domain()
    fw = build(tmp_path, assembly=assembly, provider=raw, domain=domain)
    fw.evolve(TASK)
    assert raw.calls == 2
    assert [(call["cycle"], call["artifact"], call["request"]["fidelity"]) for call in domain.calls] == [
        (0, "general:1", "shallow"), (1, "general:2", "full"), (0, "general:1", "full")]


def test_proxy_calibration_and_held_out_splits_share_original_materializations(tmp_path):
    from test_composed_proxy import profile as proxy_profile, Domain as ProxyDomain
    assembly = proxy_profile()
    assembly.update(schema_version=2, execution=profile()["execution"])
    raw, domain = ConstructorProvider(), ProxyDomain()
    fw = build(tmp_path, assembly=assembly, provider=raw, domain=domain, generations=3)
    fw.evolve(TASK)
    artifacts = {m["construction_result"]["candidate"]["id"]: m["construction_result"]["artifact"]
                 for m in records(fw, "materialization_completed")}
    assert raw.calls == len(artifacts) == 4
    assert {call["request"]["split_id"] for call in domain.calls} == {"dev", "calibration", "admission", "final_audit"}
    for evidence in records(fw, "composed_physical_evidence"):
        bound = evidence["evidence"]["evidence"]["eval_result"]["contract"]["binding"]
        import hashlib
        assert bound["artifact_sha256"] == hashlib.sha256(artifacts[bound["candidate_id"]].encode()).hexdigest()


def test_public_inspection_reports_and_revalidates_frozen_artifacts(tmp_path):
    raw = ConstructorProvider()
    fw = build(tmp_path, provider=raw, generations=0)
    result = fw.evolve(TASK)
    report = fw.inspect()["execution"]
    assert report["kind"] == "configured_construction_v1"
    artifact = report["main"]["artifacts"][result["best_candidate_id"]]
    assert artifact["role"] == "general" and artifact["artifact_ref"].startswith("sha256:")
    assert artifact["materialization_ref"].startswith("sha256:")
    blob = next((tmp_path / "construction-artifacts" / "main").glob("*.blob"))
    blob.write_text("corrupted artifact")
    with pytest.raises(ValueError, match="artifact"):
        fw.inspect()
    assert raw.calls == 1


def test_excluded_feedback_cannot_return_through_policy_absorption_state(tmp_path):
    from dataclasses import replace
    class RetainingPolicy(GreedyPolicy):
        async def absorb(self, evidence):
            self.absorbed = evidence.eval_result.text_feedback
            return await super().absorb(evidence)

        async def ideate(self, context, parent, k):
            return [{"hypothesis": getattr(self, "absorbed", "Build the initial candidate")}]

        def checkpoint_state(self):
            return {**super().checkpoint_state(), "absorbed": getattr(self, "absorbed", None)}

        def restore_state(self, value):
            value = dict(value)
            absorbed = value.pop("absorbed")
            super().restore_state(value)
            if absorbed is not None:
                self.absorbed = absorbed

    class FeedbackDomain(Domain):
        async def evaluate(self, proposal, request):
            return replace(await super().evaluate(proposal, request), text_feedback="ABSORBED_EXCLUDED_SENTINEL")

    registry = default_registry()
    registry.register("policy", "retaining", lambda ctx, opts: RetainingPolicy(ctx.scope_context))
    assembly = profile(projection=[])
    assembly["policy"] = {"name": "retaining"}
    build(tmp_path, assembly=assembly, domain=FeedbackDomain(), registry=registry, stop=0).evolve(TASK)
    raw = ConstructorProvider()
    resumed = build(tmp_path, assembly=assembly, domain=FeedbackDomain(), provider=raw, registry=registry, resume=True)
    resumed.evolve(TASK)
    assert "ABSORBED_EXCLUDED_SENTINEL" in json.dumps(records(resumed, "composed_context"))
    assert "ABSORBED_EXCLUDED_SENTINEL" not in json.dumps(raw.prompts)


def test_provider_backed_policy_plan_build_and_recorded_replay(tmp_path):
    class Planner(ConstructorProvider):
        def __call__(self, prompt):
            if prompt.startswith("Plan one research cycle"):
                assert not self.forbidden
                Provider.__call__(self, prompt)
                return json.dumps({"operator": "draft", "parents": [], "hypotheses": ["Plan a baseline"]})
            return super().__call__(prompt)
    assembly = profile()
    assembly["policy"] = {"name": "llm_cycles"}
    assembly["budget"]["options"]["operation_reservations"]["planning"]["token"] = 5
    raw = Planner()
    fw = build(tmp_path, assembly=assembly, provider=raw, generations=0)
    fw.evolve(TASK)
    assert raw.calls == 2 and json.loads(raw.prompts[-1])["hypothesis"] == "Plan a baseline"
    assert sum(o["actual"]["token"] for o in physical_operations(fw)) == 17
    assert fw.replay(adapter_factory=lambda p, s: (Planner(forbidden=True), ForbiddenDomain()))["replay_certificate"]["passed"]


def test_local_repairs_stop_when_the_reserved_tokens_are_consumed(tmp_path):
    class Invalid(ConstructorProvider):
        def __call__(self, prompt):
            super().__call__(prompt)
            return "invalid JSON"
    assembly = profile()
    assembly["execution"]["constructor"]["options"]["max_attempts"] = 5
    raw, domain = Invalid(), Domain()
    fw = build(tmp_path, assembly=assembly, provider=raw, domain=domain, generations=0)
    fw.evolve(TASK)
    assert raw.calls == 2 and domain.calls == []
    assert fw._composed.budget.state()["global"]["used"] == {"token": 10, "node": 1, "eval_count": 0}
