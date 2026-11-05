"""Resident controls through the public Framework entry point."""
from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from core.composition.defaults import composed_profile, default_registry
from core.loop import Framework, LoopConfig
from test_composed_budget import Domain, Provider, TASK, options


CAPABILITY = {
    "schema_version": 1,
    "sampling": {"method": "deterministic_fixture", "parameters": {}, "applied": True},
    "fresh_session": True, "state_independent": True,
    "call_bound": {"kind": "hard", "units": {"token": 5}},
    "external_currency": False,
}


class FreshProvider(Provider):
    def governance_binding(self):
        return copy.deepcopy(CAPABILITY)


def governed(path, *, schedule=(0, 2, 3), generations=2, stop=None, resume=False,
             main_tokens=10000, provider_factory=None, domain_factory=None, control_operator_factory=None):
    registry = default_registry()
    sessions, domains = [], []

    def provider(ctx, opts):
        result = (provider_factory or FreshProvider)()
        sessions.append(result)
        return result

    def domain(ctx, opts):
        result = (domain_factory or Domain)()
        domains.append(result)
        return result

    registry.register("provider", "independent-fixture", provider, governance=CAPABILITY)
    registry.register("domain", "independent-fixture", domain,
        governance={"schema_version": 1, "fresh_session": True, "state_independent": True})
    if control_operator_factory:
        registry.register("operator", "multi-call", control_operator_factory,
            governance={"schema_version": 1, "parentless": True})
    profile = composed_profile()
    profile["domain"] = {"name": "native"}
    budget = options()
    budget["limits"]["global"]["token"] = main_tokens
    profile["budget"] = {"name": "hierarchical", "options": budget}
    profile["governance"] = {"schema_version": 1, "controls": {
        "after_main_cycles": list(schedule), "seed": 1,
        "provider": {"name": "independent-fixture"},
        "domain": {"name": "independent-fixture"},
        "operator": {"name": "multi-call" if control_operator_factory else "draft"},
        "request": {"fidelity": "dev", "split_id": "dev", "seed_set": None},
        "reservations": {"operator": {"token": 5, "node": 1, "eval_count": 0},
                         "evaluation": {"token": 7, "node": 0, "eval_count": 1}}}}
    config = LoopConfig(max_generations=generations, total_budget=100000, intent_cost=2000,
        reeval_floor=0, baseline_every=2, stop_after_generation=stop,
        resume_from_checkpoint=resume)
    main, main_domain = FreshProvider(), Domain()
    fw = Framework.from_profile(profile, main, main_domain, config, str(path),
                                component_registry=registry)
    return fw, sessions, domains, main, main_domain


def test_resident_controls_are_scheduled_but_never_enter_main_search(tmp_path):
    fw, providers, domains, main, main_domain = governed(tmp_path)
    result = fw.evolve(TASK)
    assert result["runtime"] == "composed-v7-governed"
    assert main.calls == len(main_domain.calls) == 3
    assert [p.calls for p in providers] == [1, 1, 1]
    assert len({p.prompts[0] for p in providers}) == 1
    assert all(len(d.calls) == 1 for d in domains)
    assert len(fw._composed.proposals) == 3
    report = fw.inspect()["governance"]
    assert report["planned"] == report["completed"] == 3
    assert report["failed"] == report["unresolved"] == 0
    assert report["budget"]["accounts"]["control"] == {"token": 36, "node": 3, "eval_count": 3}
    assert report["budget"]["reconciled"] is True
    events = [r["payload"] for r in fw.store.read("governed_control_terminal")]
    assert [r["main_cycles"] for r in events] == [0, 2, 3]
    control_ids = {r["candidate_id"] for r in events}
    assert not control_ids.intersection(fw._composed.frontier.nodes)
    assert result["best_candidate_id"] not in control_ids


def test_explicit_pause_keeps_future_controls_pending_and_resume_runs_once(tmp_path):
    fw, providers, _, _, _ = governed(tmp_path, stop=0)
    fw.evolve(TASK)
    assert [p.calls for p in providers] == [1, 0, 0]
    assert fw.inspect()["governance"]["pending"] == 2
    resumed, fresh, _, main, _ = governed(tmp_path, resume=True)
    resumed.evolve(TASK)
    assert [p.calls for p in fresh] == [0, 1, 1]
    assert main.calls == 2
    assert resumed.inspect()["governance"]["completed"] == 3


def test_main_exhaustion_drains_protected_controls(tmp_path):
    fw, providers, _, main, _ = governed(tmp_path, main_tokens=38)
    fw.evolve(TASK)
    assert main.calls == 0
    assert [p.calls for p in providers] == [1, 1, 1]
    assert fw.inspect()["governance"]["completed"] == 3


def test_inspection_recomputes_control_evidence_instead_of_cached_success(tmp_path):
    fw, _, _, _, _ = governed(tmp_path)
    fw.evolve(TASK)
    fw.store.append("governed_control_terminal", {"slot_id": "foreign"})
    with pytest.raises(ValueError, match="control|governed"):
        fw.inspect()


def test_known_control_failure_stays_in_sample_and_keeps_its_charge(tmp_path):
    class Failing(FreshProvider):
        def __call__(self, prompt):
            super().__call__(prompt)
            raise RuntimeError("fixture failure")

    fw, providers, domains, _, _ = governed(tmp_path, provider_factory=Failing)
    fw.evolve(TASK)
    report = fw.inspect()["governance"]
    assert report["planned"] == report["failed"] == 3
    assert report["completed"] == report["unresolved"] == 0
    assert [p.calls for p in providers] == [1, 1, 1]
    assert [len(d.calls) for d in domains] == [0, 0, 0]
    assert report["budget"]["accounts"]["control"]["token"] == 15


def test_replay_uses_recorded_outcomes_without_any_new_calls(tmp_path):
    fw, providers, domains, main, main_domain = governed(tmp_path)
    result = fw.evolve(TASK)
    before = [p.calls for p in providers], main.calls, len(main_domain.calls)
    certificate = fw.replay()["replay_certificate"]
    assert certificate["passed"] is True
    assert certificate["mode"] == "recorded_outcomes"
    assert certificate["external_calls"] == 0
    assert before == ([p.calls for p in providers[:3]], main.calls, len(main_domain.calls))
    assert all(p.calls == 0 for p in providers[3:])


def test_main_without_a_bound_is_rejected_before_all_calls(tmp_path):
    fw, providers, _, main, _ = governed(tmp_path)
    main.governance_binding = None
    with pytest.raises(ValueError, match="main.*governance|main.*bound"):
        fw.evolve(TASK)
    assert main.calls == 0
    assert not providers or all(p.calls == 0 for p in providers)


def test_each_provider_ordinal_must_fit_the_same_control_envelope(tmp_path):
    from core.composition.contracts import OperatorBudgetExhausted
    from core.executor.types import CostVec
    from core.llm import ProviderBudgetExhausted, take_usage

    class Multi:
        def __init__(self, provider):
            self.provider = provider

        async def propose(self, request):
            self.provider(request.task_desc)
            used = take_usage(self.provider)
            try:
                self.provider(request.task_desc)
            except ProviderBudgetExhausted:
                used += take_usage(self.provider)
                raise OperatorBudgetExhausted(CostVec(tokens_in=used, node_count=1), "bounded stop",
                    measured_cost_units=("token", "node", "eval_count"))
            raise AssertionError("second bounded call was dispatched")

    fw, providers, _, _, _ = governed(tmp_path,
        control_operator_factory=lambda ctx, opts: Multi(ctx.llm))
    fw.evolve(TASK)
    assert [p.calls for p in providers] == [1, 1, 1]
    report = fw.inspect()["governance"]
    assert report["failed"] == 3
    assert report["budget"]["accounts"]["control"]["token"] == 15


def test_actual_call_bound_breach_retains_charge_and_stops_both_lanes(tmp_path):
    from core.llm import UsageError
    class Breach(FreshProvider):
        def __init__(self):
            super().__init__(tokens=6)
    fw, providers, _, main, _ = governed(tmp_path, provider_factory=Breach)
    with pytest.raises(UsageError, match="bound|capacity"):
        fw.evolve(TASK)
    assert [p.calls for p in providers] == [1, 0, 0]
    assert main.calls == 0
    report = fw.inspect()["governance"]
    assert report["budget"]["accounts"]["control"]["token"] == 6
    assert report["budget"]["protection_valid"] is False


def test_changed_sampling_binding_is_charged_then_stops_both_lanes(tmp_path):
    from core.llm import UsageError
    class Drifting(FreshProvider):
        def governance_binding(self):
            binding = super().governance_binding()
            if self.calls:
                binding["sampling"]["parameters"] = {"changed": True}
            return binding
    fw, providers, _, main, _ = governed(tmp_path, provider_factory=Drifting)
    with pytest.raises(UsageError, match="governance|binding"):
        fw.evolve(TASK)
    assert main.calls == 0 and [p.calls for p in providers] == [1, 0, 0]
    report = fw.inspect()["governance"]
    assert report["budget"]["accounts"]["control"]["token"] == 5
    assert report["violations"]


def test_main_call_bound_breach_is_not_hidden_by_a_larger_operation_reservation(tmp_path):
    from core.llm import UsageError
    fw, providers, _, main, domain = governed(tmp_path)
    main.tokens = 6
    with pytest.raises(UsageError, match="bound"):
        fw.evolve(TASK)
    assert main.calls == 1 and len(domain.calls) == 0
    assert [p.calls for p in providers] == [1, 0, 0]
    report = fw.inspect()["governance"]
    assert report["budget"]["accounts"]["explore"]["token"] == 6
    assert report["violations"]


def test_invocation_bindings_include_adapter_session_and_monotonic_ordinals(tmp_path):
    fw, _, _, _, _ = governed(tmp_path)
    fw.evolve(TASK)
    calls = [r["payload"] for r in fw.store.read("composed_provider_started")]
    assert calls and all("invocation" in call for call in calls)
    assert all(call["invocation"]["ordinal"] == 0 for call in calls)
    assert all(call["invocation"]["run_id"] == fw._composed._logical_run_id for call in calls)
    assert all(call["invocation"]["adapter_binding_sha256"] for call in calls)


def test_pause_resume_then_replay_preserves_frontier_event_scope(tmp_path):
    fw, _, _, _, _ = governed(tmp_path, stop=0)
    fw.evolve(TASK)
    resumed, _, _, _, _ = governed(tmp_path, resume=True)
    resumed.evolve(TASK)
    assert resumed.replay()["replay_certificate"]["passed"] is True


def test_adopting_native_evidence_restores_declared_domain_state(tmp_path, monkeypatch):
    from dataclasses import replace
    from core.composition.recovery import ContinuationStore

    class Stateful(Domain):
        def __init__(self):
            super().__init__()
            self.count = 0
        def checkpoint_state(self):
            return {"count": self.count}
        def restore_state(self, state):
            self.count = state["count"]
        async def evaluate(self, proposal, request):
            self.count += 1
            result = await super().evaluate(proposal, request)
            return replace(result, metrics={"dev/score": float(self.count)})

    class Crash(BaseException):
        pass
    original = ContinuationStore._write
    def crash(store, record):
        original(store, record)
        if record["kind"] == "governed_evaluation_completed" and record["payload"]["identity"]["lane"] == "main":
            raise Crash()
    fw, _, _, _, _ = governed(tmp_path)
    fw._composed.evaluator = Stateful()
    monkeypatch.setattr(ContinuationStore, "_write", crash)
    with pytest.raises(Crash):
        fw.evolve(TASK)
    monkeypatch.setattr(ContinuationStore, "_write", original)
    resumed, _, _, _, _ = governed(tmp_path, resume=True)
    resumed._composed.evaluator = Stateful()
    result = resumed.evolve(TASK)
    assert result["best_score"] == 3.0
    assert resumed._composed.evaluator.count == 3
