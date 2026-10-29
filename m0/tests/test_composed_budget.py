"""Physical limits, real fidelity requests and recovery through Framework."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.composition.contracts import Proposal
from core.composition.defaults import (GreedyPolicy, OperatorFailure, PromptOperator,
                                       composed_profile, default_registry)
from core.composition.evaluation import EvaluationContract, PrivateEvaluationData, binding_for
from core.executor.types import Candidate, CostVec, EvalResult, EvalStatus
from core.llm import UsageError
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import RunCheckpoint

TASK = "account for each configured physical operation"
MANAGED = ("token", "node", "eval_count")


class Provider:
    model = "physical-fixture-v1"
    supplier = "offline-simulation"

    def __init__(self, tokens=5, unknown=False):
        self.tokens, self.unknown = tokens, unknown
        self.calls, self.prompts = 0, []
        self.generation_index = 0

    def __call__(self, prompt):
        self.calls += 1
        self.generation_index += 1
        self.prompts.append(prompt)
        self.last_usage = None if self.unknown else {"total_tokens": self.tokens}
        return "candidate artifact " + str(self.generation_index)

    def checkpoint_state(self):
        return {"generation_index": self.generation_index}

    def restore_state(self, state):
        self.generation_index = state["generation_index"]


class Domain:
    evaluator_version = "physical-domain-v1"
    evaluation_context = "sha256:" + "b" * 64
    contexts = {"dev": evaluation_context, "admission": "sha256:" + "c" * 64,
                "final_audit": "sha256:" + "d" * 64}
    measured_cost_units = MANAGED

    def __init__(self, *, missing_coverage=False, invalid_identity=False, failed_baseline=False,
                 mutate_seeds=False, constant=False, extras=False, producer_wall=False):
        self.calls = []
        self.missing_coverage, self.invalid_identity = missing_coverage, invalid_identity
        self.failed_baseline, self.mutate_seeds, self.constant = failed_baseline, mutate_seeds, constant
        self.extras, self.producer_wall = extras, producer_wall
        self.measured_cost_units = MANAGED + (("gpu_hours", "usd") if extras else ()) \
            + (("wallclock",) if producer_wall else ())

    def validate_request(self, request):
        request.validate()
        if request.split_id not in self.contexts or request.fidelity not in {
                "dev", "shallow", "full", "highest", "admission", "final_audit"}:
            raise ValueError("unsupported offline request")

    def evaluation_context_for(self, request):
        return self.contexts[request.split_id]

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        if self.mutate_seeds and request.seed_set is not None:
            request.seed_set.append(99)
        self.calls.append({"candidate_id": proposal.candidate.id, "cycle": proposal.candidate.created_cycle,
                           "request": copy.deepcopy(asdict(request)), "artifact": proposal.artifact})
        cycle = proposal.candidate.created_cycle
        if request.split_id == "dev":
            score = {"shallow": 0.8, "full": 0.1, "highest": 0.05}.get(request.fidelity, 0.3) + cycle * 0.02
            if self.constant:
                score = 0.3
        else:
            score = 0.4 + cycle * 0.1 if request.split_id == "admission" else 0.01
        status = EvalStatus.FAILED_TO_RUN if self.failed_baseline and request.fidelity == "full" \
            and request.split_id == "dev" and cycle == 0 else EvalStatus.OK
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context_for(request))
        if self.invalid_identity:
            binding = replace(binding, candidate_id="foreign")
        coverage = ("eval_count",) if self.missing_coverage else self.measured_cost_units
        return EvalResult(status, {"dev/score": score} if status is EvalStatus.OK else {},
            CostVec(tokens_in=7, eval_count=1, gpu_hours=0.5 if self.extras else 0,
                    usd=0.03 if self.extras else 0, wall_seconds=0.125 if self.producer_wall else 0),
            fidelity=request.fidelity, text_feedback="public development feedback",
            contract=EvaluationContract(binding, coverage, private=PrivateEvaluationData(data={"secret": "held out"})))


def options(*, units=None):
    units = {"token": 10, "node": 0, "eval_count": 1} if units is None else units
    ceilings = {unit: {"token": 10_000, "node": 20, "eval_count": 100,
                       "gpu_hours": 20.0, "usd": 10.0, "wallclock": 100.0}[unit] for unit in units}
    planning = {unit: 0 for unit in units}
    planning.update({"token": 2} if "token" in units else {})
    operator = dict(units)
    if "node" in operator:
        operator["node"] = 1
    if "eval_count" in operator:
        operator["eval_count"] = 0
    if "wallclock" in planning:
        planning["wallclock"] = 10.0
    return {"limits": {level: dict(ceilings) for level in ("global", "direction", "candidate")},
            "reservation": dict(units), "operation_reservations": {"planning": planning, "operator": operator},
            "fidelity_rungs": [{"fidelity": "dev", "split_id": "dev"}]}


def build(path, *, budget=None, llm=None, domain=None, layered=False, admission=None,
          generations=2, stop=None, resume=False, registry=None, policy=None, operators=None,
          domain_name="native"):
    profile = composed_profile()
    profile["domain"] = {"name": domain_name}
    profile["budget"] = {"name": "hierarchical", "options": budget or options()}
    if layered:
        profile["admission"] = {"name": "layered", "options": admission or {}}
    if policy:
        profile["policy"] = {"name": policy}
    if operators:
        profile["operators"] = [{"name": name} for name in operators]
    config = LoopConfig(max_generations=generations, total_budget=100_000, intent_cost=2_000,
                        reeval_floor=0, baseline_every=2, stop_after_generation=stop,
                        resume_from_checkpoint=resume)
    return Framework.from_profile(profile, llm or Provider(), domain or Domain(), config, str(path),
                                  component_registry=registry or default_registry())


def rows(fw, kind):
    return [row["payload"] for row in fw.store.read(kind)]


def physical_operations(fw):
    result = {}
    for row in rows(fw, "hierarchical_budget"):
        data = row["data"]
        if row["event"] == "reserve":
            result[data["intent"]["intent_id"]] = {"intent": data["intent"]}
        elif row["event"] == "settle":
            result[data["intent_id"]]["actual"] = data["actual_costs"]
    return list(result.values())


def test_framework_accounts_each_physical_charge_once_across_three_views_and_replays(tmp_path):
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, llm=provider, domain=domain)
    result = fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert result["cycles"] == provider.calls == len(domain.calls) == 3
    assert state["global"]["used"] == {"token": 36, "node": 3, "eval_count": 3}
    assert sum(scope["used"]["node"] for scope in state["directions"].values()) == 3
    assert sum(scope["used"]["token"] for scope in state["candidates"].values()) == 36
    assert all(value == 0 for value in state["global"]["reserved"].values())
    assert not state["open_intents"]
    assert fw.replay()["replay_certificate"]["passed"]


@pytest.mark.parametrize("level", ["global", "direction", "candidate"])
def test_each_layer_can_atomically_refuse_node_budget_before_provider_or_domain_call(tmp_path, level):
    cfg = options(); cfg["limits"][level]["node"] = 0
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, budget=cfg, llm=provider, domain=domain, generations=0)
    result = fw.evolve(TASK)
    assert provider.calls == 0 and domain.calls == [] and result["cycles"] == 0
    state = fw._composed.budget.state()
    assert state["global"]["used"] == {"token": 0, "node": 0, "eval_count": 0}
    assert not state["open_intents"] and all(amount == 0 for amount in state["global"]["reserved"].values())


def test_exhausted_direction_is_hidden_only_in_selection_view_and_greedy_can_start_new_direction(tmp_path):
    cfg = options()
    cfg["limits"]["direction"]["eval_count"] = 1
    cfg["limits"]["candidate"]["node"] = 1
    fw = build(tmp_path, budget=cfg, generations=2)
    result = fw.evolve(TASK)
    assert result["cycles"] == 3
    evidence = rows(fw, "composed_evidence")
    assert [item["proposal"]["candidate"]["parents"] for item in evidence] == [[], [], []]
    assert all(node.status == "merged" for node in fw._composed.frontier.nodes.values())
    productive = [scope for scope in fw._composed.budget.state()["directions"].values() if scope["used"]["eval_count"]]
    assert len(productive) == 3 and all(scope["used"]["eval_count"] == 1 for scope in productive)


def test_provider_overrun_is_charged_truthfully_and_blocks_the_next_evaluator_call(tmp_path):
    provider, domain = Provider(tokens=15), Domain()
    fw = build(tmp_path, llm=provider, domain=domain)
    result = fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert provider.calls == 1 and domain.calls == []
    assert state["global"]["used"] == {"token": 15, "node": 1, "eval_count": 0}
    assert "overrun" in result["stop_reason"] and not state["open_intents"]


@pytest.mark.parametrize("failure", ["provider", "domain"])
def test_unknown_usage_keeps_whole_basket_open_and_resume_never_repeats_paid_work(tmp_path, failure):
    provider = Provider(unknown=failure == "provider")
    domain = Domain(missing_coverage=failure == "domain")
    fw = build(tmp_path, llm=provider, domain=domain, generations=0)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert len(state["open_intents"]) == 1 and state["global"]["reserved"]["token"] == 10
    assert provider.calls == 1 and len(domain.calls) == (failure == "domain")
    assert state["global"]["used"]["token"] == (5 if failure == "domain" else 0)
    fresh_provider, fresh_domain = Provider(), Domain()
    resumed = build(tmp_path, llm=fresh_provider, domain=fresh_domain, generations=0, resume=True)
    with pytest.raises((ValueError, RuntimeError), match="unfinished|budget|durable"):
        resumed.evolve(TASK)
    assert fresh_provider.calls == 0 and fresh_domain.calls == []


def test_planning_usage_error_is_unresolved_even_if_provider_counter_did_not_increase(tmp_path):
    class UnknownPlanning(GreedyPolicy):
        async def observe(self, state, budget):
            raise UsageError("planning operation did not produce trustworthy usage")
    registry = default_registry()
    registry.register("policy", "unknown-planning", lambda ctx, opts: UnknownPlanning(ctx.scope_context))
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, registry=registry, policy="unknown-planning", llm=provider, domain=domain)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert provider.calls == 0 and domain.calls == []
    assert state["global"]["used"]["token"] == 0 and state["global"]["reserved"]["token"] == 2
    assert len(state["open_intents"]) == 1
    assert any(row["event"] == "unresolved" for row in rows(fw, "hierarchical_budget"))


def test_known_domain_identity_error_is_charged_before_evidence_is_rejected(tmp_path):
    domain = Domain(invalid_identity=True)
    fw = build(tmp_path, domain=domain, generations=0)
    with pytest.raises(ValueError, match="binding"):
        fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert state["global"]["used"] == {"token": 12, "node": 1, "eval_count": 1}
    assert not state["open_intents"] and not rows(fw, "composed_decision")


@pytest.mark.parametrize("cap,final_state", [(4, "not_run"), (5, "complete")])
def test_admission_and_final_share_global_budget_but_keep_independent_query_caps(tmp_path, cap, final_state):
    cfg = options(); cfg["limits"]["global"]["eval_count"] = cap
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, budget=cfg, llm=provider, domain=domain, layered=True, generations=1)
    result = fw.evolve(TASK)
    assert result["reporting"]["gate_calls"] == 2
    assert result["reporting"]["final_audit"]["state"] == final_state
    assert len(domain.calls) == cap
    assert fw._composed.budget.state()["global"]["used"] == {
        "token": provider.calls * 5 + cap * 7, "node": 2, "eval_count": cap}
    assert all(row["intent"]["operation"] in {"planning", "operator", "dev", "admission", "final"}
               for row in physical_operations(fw))


def test_unfunded_gate_does_not_spend_m9_query_cap(tmp_path):
    cfg = options(); cfg["limits"]["global"]["eval_count"] = 1
    domain = Domain()
    fw = build(tmp_path, budget=cfg, domain=domain, layered=True, generations=0)
    result = fw.evolve(TASK)
    assert [call["request"]["split_id"] for call in domain.calls] == ["dev"]
    assert result["reporting"]["gate_calls"] == 0
    assert result["reporting"]["final_audit"]["state"] == "no_selection"


def rung_options():
    cfg = options()
    cfg["fidelity_rungs"] = [{"fidelity": "shallow", "split_id": "dev", "seed_set": [11]},
                             {"fidelity": "full", "split_id": "dev", "seed_set": [11, 29]}]
    return cfg


def test_new_rung_pays_for_matching_incumbent_baseline_and_updates_public_frontier_evidence(tmp_path):
    domain, provider = Domain(), Provider()
    fw = build(tmp_path, budget=rung_options(), domain=domain, llm=provider, layered=True, generations=1)
    result = fw.evolve(TASK)
    dev_calls = [call for call in domain.calls if call["request"]["split_id"] == "dev"]
    assert [(call["cycle"], call["request"]["fidelity"], call["request"]["seed_set"]) for call in dev_calls] == [
        (0, "shallow", [11]), (1, "full", [11, 29]), (0, "full", [11, 29])]
    assert result["reporting"]["development_basis"]["fidelity"] == "full"
    assert len(result["accepted_candidate_ids"]) == 2
    assert fw._composed.budget.state()["global"]["used"]["eval_count"] == 6
    baselines = rows(fw, "composed_dev_baseline")
    assert len(baselines) == 1 and baselines[0]["request"] == dev_calls[1]["request"]
    identifier = baselines[0]["evidence"]["evidence"]["candidate_id"]
    node = fw._composed.frontier.nodes[identifier]
    assert node.score == pytest.approx(0.1) and node.score_split["dev/score"] == pytest.approx(0.1)
    assert node.result["metrics"]["dev/score"] == pytest.approx(0.1) and node.attempt == 2
    assert any(operation["intent"]["operation"] == "dev_baseline" and operation["actual"]["eval_count"] == 1
               for operation in physical_operations(fw))
    assert '"fidelity": "full"' in provider.prompts[1]
    assert fw.replay()["replay_certificate"]["passed"]


def test_failed_incumbent_baseline_is_charged_and_never_used_as_a_fake_comparison(tmp_path):
    domain = Domain(failed_baseline=True)
    fw = build(tmp_path, budget=rung_options(), domain=domain, layered=True, generations=1)
    with pytest.raises(ValueError, match="baseline did not succeed"):
        fw.evolve(TASK)
    assert fw._composed.budget.state()["global"]["used"] == {"token": 38, "node": 2, "eval_count": 4}
    assert not fw._composed.budget.state()["open_intents"]
    assert fw._composed.layered.development_basis["fidelity"] == "shallow"
    assert len(rows(fw, "composed_decision")) == 1


def test_depth_rung_uses_actual_parent_depth_instead_of_generation_number(tmp_path):
    class Oldest(GreedyPolicy):
        async def select(self, frontier, budget):
            eligible = [node for node in frontier.nodes.values() if node.status == "merged"]
            eligible.sort(key=lambda node: (node.created_cycle, node.id))
            return [eligible[0].id] if eligible else []
    registry = default_registry()
    registry.register("policy", "oldest", lambda ctx, opts: Oldest(ctx.scope_context))
    cfg = rung_options(); cfg["rung_by"] = "depth"
    cfg["fidelity_rungs"].append({"fidelity": "highest", "split_id": "dev", "seed_set": [11, 29, 47]})
    domain = Domain()
    fw = build(tmp_path, budget=cfg, domain=domain, registry=registry, policy="oldest", generations=3)
    result = fw.evolve(TASK)
    assert result["cycles"] == 4
    evaluated_candidates = rows(fw, "composed_evidence")
    assert [row["evidence"]["eval_result"]["fidelity"] for row in evaluated_candidates] == ["shallow", "full", "full", "full"]
    assert max(node.depth for node in fw._composed.frontier.nodes.values()) == 1


def test_request_mutation_cannot_forge_binding_or_rewrite_the_reserved_request(tmp_path):
    domain = Domain(mutate_seeds=True)
    fw = build(tmp_path, budget=rung_options(), domain=domain, generations=0)
    with pytest.raises(ValueError, match="binding"):
        fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert state["global"]["used"] == {"token": 12, "node": 1, "eval_count": 1}
    assert not state["open_intents"] and not rows(fw, "composed_decision")
    calls = [operation for operation in physical_operations(fw) if operation["intent"]["operation"] == "dev"]
    assert calls[0]["intent"]["request"]["seed_set"] == [11]


def test_checkpoint_restores_physical_views_requests_and_final_state_without_repaying(tmp_path):
    cfg = rung_options()
    first = build(tmp_path, budget=cfg, layered=True, generations=2, stop=1)
    first.evolve(TASK)
    resumed_domain = Domain()
    resumed = build(tmp_path, budget=cfg, domain=resumed_domain, layered=True, generations=2, resume=True)
    result = resumed.evolve(TASK)
    assert [call["request"]["split_id"] for call in resumed_domain.calls] == ["dev", "admission", "final_audit"]
    completed_provider, completed_domain = Provider(), Domain()
    completed = build(tmp_path, budget=cfg, llm=completed_provider, domain=completed_domain,
                      layered=True, generations=2, resume=True)
    assert completed.evolve(TASK) == result
    assert completed_provider.calls == 0 and completed_domain.calls == []
    assert completed.replay()["replay_certificate"]["passed"]


class PhysicalOperator:
    measured_cost_units = MANAGED + ("gpu_hours", "usd")

    def __init__(self, *, node=1, coverage=None, snapshots=None, fail=False):
        self.node = node
        self.coverage = self.measured_cost_units if coverage is None else coverage
        self.snapshots, self.fail = snapshots, fail

    async def propose(self, request):
        if self.snapshots is not None:
            self.snapshots.append(copy.deepcopy(request.context["budget"]))
        cost = CostVec(node_count=self.node, gpu_hours=0.25 if "gpu_hours" in self.coverage else 0,
                       usd=0.02 if "usd" in self.coverage else 0, tokens_in=3 if self.fail else 0)
        if self.fail:
            raise OperatorFailure(cost, "known failed candidate attempt", measured_cost_units=self.coverage)
        candidate = Candidate(request.candidate_id, [item.candidate.id for item in request.parents],
            operator="physical", created_cycle=request.cycle, context_pack_ref=request.context["context_pack_ref"])
        return Proposal(candidate, "physical artifact", cost, self.coverage)


def physical_registry(factory):
    registry = default_registry()
    registry.register("operator", "physical", factory)
    return registry


def test_operator_budget_context_contains_its_own_started_reservation(tmp_path):
    snapshots = []
    registry = physical_registry(lambda ctx, opts: PhysicalOperator(coverage=MANAGED, snapshots=snapshots))
    fw = build(tmp_path, registry=registry, operators=["physical"], generations=0)
    fw.evolve(TASK)
    state = snapshots[0]["state"]
    assert state["global"]["reserved"] == {"token": 10, "node": 1, "eval_count": 0}
    assert len(state["open_intents"]) == 1


def test_explicit_gpu_and_currency_measurements_remain_separate_and_require_every_adapter(tmp_path):
    cfg = options(units={"token": 10, "node": 0, "eval_count": 1, "gpu_hours": 1.0, "usd": 0.1})
    registry = physical_registry(lambda ctx, opts: PhysicalOperator())
    domain = Domain(extras=True)
    fw = build(tmp_path, budget=cfg, registry=registry, operators=["physical"], domain=domain, generations=0)
    fw.evolve(TASK)
    assert fw._composed.budget.state()["global"]["used"] == {
        "token": 7, "node": 1, "eval_count": 1, "gpu_hours": 0.75, "usd": 0.05}
    for missing in ("operator", "domain", "planning"):
        provider, evaluator = Provider(), Domain(extras=missing != "domain")
        target = build(tmp_path / missing, budget=cfg, registry=registry, llm=provider,
            domain=evaluator, operators=None if missing == "operator" else ["physical"],
            policy="llm_cycles" if missing == "planning" else None, generations=0)
        with pytest.raises(ValueError, match="coverage"):
            target.evolve(TASK)
        assert provider.calls == 0 and evaluator.calls == []


@pytest.mark.parametrize("declare_wall", [False, True])
def test_wallclock_uses_runtime_boundary_or_real_producer_measurement_without_relabeling_contract(tmp_path, monkeypatch, declare_wall):
    from core.composition import hierarchical_runtime
    tick = iter(index * 0.25 for index in range(1000))
    monkeypatch.setattr(hierarchical_runtime, "time", SimpleNamespace(monotonic=lambda: next(tick)))
    cfg = options(units={"token": 10, "node": 0, "eval_count": 1, "wallclock": 10.0})
    fw = build(tmp_path, budget=cfg, domain=Domain(producer_wall=declare_wall), generations=0)
    fw.evolve(TASK)
    measured = [operation for operation in physical_operations(fw) if operation["intent"]["operation"] == "dev"][0]
    assert measured["actual"]["wallclock"] == (0.125 if declare_wall else 0.25)
    returned = rows(fw, "composed_evidence")[0]["evidence"]["eval_result"]
    assert ("wallclock" in returned["contract"]["measured_cost_units"]) is declare_wall
    assert returned["cost"]["wall_seconds"] == (0.125 if declare_wall else 0)


@pytest.mark.parametrize("declare_node", [False, True])
def test_actual_candidate_attempt_cannot_be_free_when_custom_operator_reports_node_zero(tmp_path, declare_node):
    coverage = MANAGED if declare_node else ("token", "eval_count")
    registry = physical_registry(lambda ctx, opts: PhysicalOperator(node=0, coverage=coverage))
    domain = Domain()
    fw = build(tmp_path, registry=registry, operators=["physical"], domain=domain, generations=0)
    if declare_node:
        with pytest.raises((ValueError, UsageError), match="node|candidate"):
            fw.evolve(TASK)
        assert domain.calls == []
    else:
        fw.evolve(TASK)
        assert len(domain.calls) == 1
    state = fw._composed.budget.state()
    assert state["global"]["used"]["node"] == 1 and not state["open_intents"]


def test_known_failed_custom_operator_still_counts_one_attempt_and_does_not_call_domain(tmp_path):
    registry = physical_registry(lambda ctx, opts: PhysicalOperator(node=0, coverage=("token", "eval_count"), fail=True))
    domain = Domain()
    fw = build(tmp_path, registry=registry, operators=["physical"], domain=domain, generations=0)
    result = fw.evolve(TASK)
    assert result["best_candidate_id"] is None and domain.calls == []
    assert fw._composed.budget.state()["global"]["used"] == {"token": 3, "node": 1, "eval_count": 0}


def test_low_sample_patience_stops_only_after_enough_actual_development_results(tmp_path):
    cfg = options()
    cfg["convergence"] = {"min_samples": 3, "patience": 2, "min_improvement": 0.0,
                          "metric": "dev/score", "direction": "maximize"}
    domain, provider = Domain(constant=True), Provider()
    fw = build(tmp_path, budget=cfg, domain=domain, llm=provider, generations=8)
    result = fw.evolve(TASK)
    assert provider.calls == len(domain.calls) == result["cycles"] == 3
    assert "observed_dev_patience" in result["stop_reason"]


@pytest.mark.parametrize("hide", ["last_call_only", "swallowed_unknown"])
def test_custom_operator_cannot_hide_shared_provider_usage_and_reach_domain(tmp_path, hide):
    class HidingOperator:
        measured_cost_units = MANAGED

        def __init__(self, provider):
            self.provider = provider

        async def propose(self, request):
            if hide == "last_call_only":
                self.provider("first operation call")
                self.provider("second operation call")
                reported = 5
            else:
                try:
                    self.provider("operation with unknown usage")
                except UsageError:
                    pass
                reported = 0
            candidate = Candidate(request.candidate_id, [parent.candidate.id for parent in request.parents],
                created_cycle=request.cycle, context_pack_ref=request.context["context_pack_ref"])
            return Proposal(candidate, "artifact", CostVec(tokens_in=reported, node_count=1), MANAGED)
    registry = default_registry()
    registry.register("operator", "hiding", lambda ctx, opts: HidingOperator(ctx.llm))
    provider, domain = Provider(unknown=hide == "swallowed_unknown"), Domain()
    fw = build(tmp_path, registry=registry, operators=["hiding"], llm=provider, domain=domain, generations=0)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert provider.calls == (2 if hide == "last_call_only" else 1) and domain.calls == []
    assert state["global"]["used"]["token"] == 0 and state["global"]["reserved"]["token"] == 10
    assert len(state["open_intents"]) == 1


@pytest.mark.parametrize("hide", ["last_call_only", "swallowed_unknown"])
def test_custom_domain_cannot_hide_shared_provider_usage_or_settle_a_false_zero(tmp_path, hide):
    class SometimesUnknown(Provider):
        def __call__(self, prompt):
            result = super().__call__(prompt)
            if prompt == "domain unknown":
                self.last_usage = None
            return result
    class HidingDomain(Domain):
        def __init__(self, provider):
            super().__init__()
            self.provider = provider

        async def evaluate(self, proposal, request):
            if hide == "last_call_only":
                self.provider("domain first")
                self.provider("domain second")
            else:
                try:
                    self.provider("domain unknown")
                except UsageError:
                    pass
            # Seven reported tokens cannot cover two observed five-token calls;
            # no numeric report can certify a swallowed unknown provider charge.
            return await super().evaluate(proposal, request)
    registry = default_registry()
    registry.register("domain", "hiding-domain", lambda ctx, opts: HidingDomain(ctx.llm))
    provider = SometimesUnknown()
    fw = build(tmp_path, registry=registry, domain_name="hiding-domain", llm=provider, generations=0)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    state = fw._composed.budget.state()
    assert provider.calls == (3 if hide == "last_call_only" else 2)
    assert len(fw._composed.parts["domain"].calls) == 1
    assert state["global"]["used"] == {"token": 5, "node": 1, "eval_count": 0}
    assert state["global"]["reserved"]["token"] == 10 and len(state["open_intents"]) == 1
    assert not rows(fw, "composed_decision")


def test_allocated_request_limits_seeds_and_resume_state_drive_actual_native_result(tmp_path):
    saved = tmp_path / "saved_training_state.txt"
    saved.write_text("0.25")
    class ParameterDomain(Domain):
        def __init__(self):
            super().__init__()
            self.evaluation_context = "sha256:" + hashlib.sha256(saved.read_bytes()).hexdigest()
            self.contexts = {**self.contexts, "dev": self.evaluation_context}

        def validate_request(self, request):
            super().validate_request(request)
            if request.resume_from is not None and request.resume_from != str(saved):
                raise ValueError("unsupported saved artifact")
            if "sha256:" + hashlib.sha256(saved.read_bytes()).hexdigest() != self.evaluation_context:
                raise ValueError("saved evaluation state changed")

        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            initial = float(Path(request.resume_from).read_text())
            score = initial + request.budget_token / 100 + request.time_limit / 100 + sum(request.seed_set) / 100
            return replace(result, metrics={"dev/score": score})
    cfg = options()
    cfg["fidelity_rungs"] = [{"fidelity": "full", "split_id": "dev", "time_limit": 3,
                              "budget_token": 9, "seed_set": [2, 4], "resume_from": str(saved)}]
    domain = ParameterDomain()
    fw = build(tmp_path / "run", budget=cfg, domain=domain, generations=0)
    result = fw.evolve(TASK)
    assert result["best_score"] == pytest.approx(0.43)
    assert domain.calls[0]["request"] == cfg["fidelity_rungs"][0]
    evaluated = [operation for operation in physical_operations(fw) if operation["intent"]["operation"] == "dev"]
    assert evaluated[0]["intent"]["request"] == cfg["fidelity_rungs"][0]


def test_unsupported_later_rung_is_rejected_before_any_paid_call(tmp_path):
    class ShallowOnly(Domain):
        def validate_request(self, request):
            super().validate_request(request)
            if request.fidelity == "full":
                raise ValueError("unsupported full rung")
    provider, domain = Provider(), ShallowOnly()
    fw = build(tmp_path, budget=rung_options(), llm=provider, domain=domain)
    with pytest.raises(ValueError, match="unsupported full"):
        fw.evolve(TASK)
    assert provider.calls == 0 and domain.calls == [] and not fw.store.path.exists()


@pytest.mark.parametrize("reported_count,charged_count", [(0, 1), (2, 2)])
def test_actual_evaluation_invocation_cannot_be_free_and_batch_counts_are_not_clamped(tmp_path, reported_count, charged_count):
    class CountDomain(Domain):
        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            return replace(result, cost=replace(result.cost, eval_count=reported_count))
    cfg = options()
    cfg["limits"]["global"]["eval_count"] = 1
    domain = CountDomain()
    fw = build(tmp_path, budget=cfg, domain=domain, layered=True, generations=3)
    if reported_count == 0:
        with pytest.raises((ValueError, UsageError), match="eval|invocation"):
            fw.evolve(TASK)
    else:
        result = fw.evolve(TASK)
        assert "overrun" in result["stop_reason"]
    state = fw._composed.budget.state()
    assert len(domain.calls) == 1
    assert state["global"]["used"] == {"token": 12, "node": 1, "eval_count": charged_count}
    assert not state["open_intents"] and not rows(fw, "composed_decision")
    assert fw._composed.layered.gate_calls == 0
