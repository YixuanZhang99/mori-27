"""Factory declarations and lane views prevent accidental cross-lane state reuse."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.contracts import AssemblyConfig, BuildContext
from core.composition.defaults import default_registry
from core.memory.types import ScopeContext
from core.x1.store import AppendOnlyStore
from test_governed_config import governed_profile


PROVIDER_BINDING = {"schema_version": 1, "fresh_session": True, "state_independent": True,
    "sampling": {"method": "deterministic_fixture", "parameters": {}, "applied": True},
    "call_bound": {"kind": "hard", "units": {"token": 10}}, "external_currency": False}
DOMAIN_BINDING = {"schema_version": 1, "fresh_session": True, "state_independent": True}


class FreshProvider:
    def __init__(self, binding=None):
        self.calls = 0
        self.binding = binding or PROVIDER_BINDING

    def __deepcopy__(self, memo):
        raise AssertionError("live provider must never be copied")

    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {"total_tokens": 1}
        return "proposal"

    def governance_binding(self):
        return self.binding


class FreshDomain:
    evaluator_version = "fixture-v1"
    evaluation_context = "sha256:" + "1" * 64

    def __init__(self):
        self.calls = 0

    def validate_request(self, request):
        request.validate()

    async def evaluate(self, proposal, request):
        self.calls += 1


def setup(tmp_path, *, provider_factory=None, provider_binding=None):
    registry = default_registry()
    contexts = []
    def provider(ctx, opts):
        contexts.append(("provider", ctx))
        return provider_factory(ctx, opts) if provider_factory else FreshProvider()
    def domain(ctx, opts):
        contexts.append(("domain", ctx))
        return FreshDomain()
    registry.register("provider", "fresh", provider, governance=provider_binding or PROVIDER_BINDING)
    registry.register("domain", "fresh", domain, governance=DOMAIN_BINDING)
    ctx = BuildContext(FreshProvider(), FreshDomain(), AppendOnlyStore(tmp_path / "events.jsonl"),
        ScopeContext("run", "task", "domain"), SimpleNamespace(max_generations=2), tmp_path)
    config = AssemblyConfig.from_dict(governed_profile())
    return registry, contexts, ctx, config


def slots(config):
    from core.composition.governance import ControlPlan
    return ControlPlan.freeze(config.governance, task_desc="task", initial_context={},
        max_generations=2, units=("token", "node", "eval_count")).to_dict()["slots"]


def test_control_factories_receive_fresh_dependencies_and_frozen_metadata(tmp_path):
    registry, contexts, ctx, config = setup(tmp_path)
    first, second = [registry.build_control(config, ctx, slot) for slot in slots(config)]
    assert contexts[0][1].llm is None and contexts[0][1].evaluator is None
    assert contexts[1][1].llm is first["provider"] and contexts[1][1].evaluator is None
    assert first["provider"].raw_provider is not second["provider"].raw_provider
    assert first["domain"] is not second["domain"]
    assert first["operator"] is not second["operator"]
    assert first["executor"] is not second["executor"]
    assert contexts[0][1].invocation_scope == {"lane": "control", "slot_id": "control-0000", "seed": 7}
    first["provider"]("prompt")
    assert second["provider"].raw_provider.calls == 0
    assert first["governance_binding"] == PROVIDER_BINDING


def test_live_main_provider_reuse_is_rejected_before_calls(tmp_path):
    registry, _, ctx, config = setup(tmp_path)
    second_registry, _, _, _ = setup(tmp_path, provider_factory=lambda *_: ctx.llm)
    with pytest.raises(ValueError, match="reused"):
        second_registry.build_control(config, ctx, slots(config)[0])
    assert ctx.llm.calls == 0


def test_provider_reuse_between_control_slots_is_rejected_before_second_call(tmp_path):
    shared = FreshProvider()
    registry, _, ctx, config = setup(tmp_path, provider_factory=lambda *_: shared)
    registry.build_control(config, ctx, slots(config)[0])
    with pytest.raises(ValueError, match="reused"):
        registry.build_control(config, ctx, slots(config)[1])
    assert shared.calls == 0


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(external_currency=True),
    lambda b: b["sampling"].update(applied=False),
    lambda b: b["sampling"].update(method="temperature_only"),
    lambda b: b["call_bound"].update(kind="estimate"),
    lambda b: b["call_bound"]["units"].update(token=11),
])
def test_unsupported_capability_is_rejected_before_factory(tmp_path, mutate):
    import copy
    binding = copy.deepcopy(PROVIDER_BINDING)
    mutate(binding)
    constructed = []
    registry, _, ctx, config = setup(tmp_path,
        provider_factory=lambda *_: constructed.append(True), provider_binding=binding)
    with pytest.raises(ValueError):
        registry.build_control(config, ctx, slots(config)[0])
    assert constructed == []


def test_runtime_binding_must_match_preflight_declaration(tmp_path):
    import copy
    changed = copy.deepcopy(PROVIDER_BINDING)
    changed["sampling"]["parameters"] = {"temperature": 0.9}
    registry, _, ctx, config = setup(tmp_path, provider_factory=lambda *_: FreshProvider(changed))
    with pytest.raises(ValueError, match="binding.*declara"):
        registry.build_control(config, ctx, slots(config)[0])


def test_opaque_factory_and_nonparentless_operator_fail_before_constructors(tmp_path):
    registry, contexts, ctx, config = setup(tmp_path)
    registry.register("provider", "opaque", lambda *_: FreshProvider())
    data = config.to_dict()
    data["governance"]["controls"]["provider"] = {"name": "opaque"}
    with pytest.raises(ValueError, match="explicit.*governance"):
        registry.build_control(data, ctx, slots(config)[0])
    assert contexts == []
    data = config.to_dict()
    data["governance"]["controls"]["operator"] = {"name": "reflective"}
    with pytest.raises(ValueError, match="parentless"):
        registry.build_control(data, ctx, slots(config)[0])
    assert contexts == []


def test_lane_views_filter_all_reads_and_reject_explicit_authority_access(tmp_path):
    from core.composition.governance import LaneStoreView
    root = AppendOnlyStore(tmp_path / "events.jsonl")
    root.append("composed_control_outcome", {"secret": "control"})
    root.append("hierarchical_budget", {"secret": "budget"})
    root.append("composed_evaluation", {"secret": "main"})
    main = LaneStoreView(root, lane="main", component="memory")
    first = LaneStoreView(root, lane="control", slot_id="control-0000", component="provider")
    second = LaneStoreView(root, lane="control", slot_id="control-0001", component="provider")
    main.append("memory_evidence", {"content": "main learned"})
    first.append("session_note", {"content": "control one"})
    assert list(main.read()) == [{"kind": "memory_evidence", "payload": {"content": "main learned"}}]
    assert list(first.read()) == [{"kind": "session_note", "payload": {"content": "control one"}}]
    assert list(second.read()) == []
    for view in (main, first, second):
        for forbidden in ("hierarchical_budget", "composed_control_outcome", "composed_evaluation"):
            with pytest.raises(PermissionError):
                list(view.read(forbidden))
            with pytest.raises(PermissionError):
                view.append(forbidden, {})
        assert not hasattr(view, "path")
    assert len(list(root.read())) == 5


def test_factory_cannot_mutate_frozen_slot_metadata_for_later_components(tmp_path):
    def mutate(ctx, opts):
        ctx.invocation_scope["seed"] = 999
        return FreshProvider()
    registry, contexts, ctx, config = setup(tmp_path, provider_factory=mutate)
    with pytest.raises(ValueError, match="mutated.*scope"):
        registry.build_control(config, ctx, slots(config)[0])
    assert len(contexts) == 1


def test_factory_cannot_mutate_governance_for_later_components(tmp_path):
    def mutate(ctx, opts):
        ctx.governance["controls"]["seed"] = 999
        return FreshProvider()
    registry, contexts, ctx, config = setup(tmp_path, provider_factory=mutate)
    with pytest.raises(ValueError, match="mutated.*governance"):
        registry.build_control(config, ctx, slots(config)[0])
    assert len(contexts) == 1


def test_lane_identity_cannot_be_reassigned_after_construction(tmp_path):
    from core.composition.governance import LaneStoreView
    root = AppendOnlyStore(tmp_path / "events.jsonl")
    view = LaneStoreView(root, lane="main", component="memory")
    with pytest.raises(AttributeError):
        view.lane = "control"


def test_mutated_slot_fails_before_any_constructor(tmp_path):
    registry, contexts, ctx, config = setup(tmp_path)
    slot = slots(config)[0]
    slot["request"]["seed_set"] = [99]
    with pytest.raises(ValueError, match="frozen"):
        registry.build_control(config, ctx, slot)
    assert contexts == []


def test_nested_meter_wrappers_cannot_hide_reused_main_provider(tmp_path):
    from core.composition.provider import MeteredProvider
    registry, _, ctx, config = setup(tmp_path)
    wrapped = MeteredProvider(MeteredProvider(ctx.llm))
    registry, _, _, _ = setup(tmp_path, provider_factory=lambda *_: wrapped)
    with pytest.raises(ValueError, match="reused"):
        registry.build_control(config, ctx, slots(config)[0])


@pytest.mark.parametrize("units", [{"node": 1}, {"token": 10, "usd": 0.1},
                                    {"token": 10, "gpu_hours": 0.1}])
def test_provider_binding_cannot_claim_units_without_a_provider_meter(units):
    import copy
    from core.composition.governance import validate_factory_governance
    binding = copy.deepcopy(PROVIDER_BINDING)
    binding["call_bound"]["units"] = units
    provider = FreshProvider(binding)
    with pytest.raises(ValueError, match="token.*bound|bound.*token"):
        validate_factory_governance("provider", provider.governance_binding())
    assert provider.calls == 0
