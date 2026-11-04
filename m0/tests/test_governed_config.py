"""Governance opt-in rejects ambiguous schedules and incomplete physical baskets."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.contracts import AssemblyConfig, BuildContext
from core.composition.defaults import composed_profile, default_registry
from core.memory.types import ScopeContext
from core.x1.store import AppendOnlyStore


def governance_data():
    return {"schema_version": 1, "controls": {
        "after_main_cycles": [0, 2], "seed": 7,
        "provider": {"name": "fresh"}, "domain": {"name": "fresh"},
        "operator": {"name": "draft"},
        "request": {"fidelity": "dev", "split_id": "dev", "seed_set": [1]},
        "reservations": {"operator": {"token": 10, "node": 1, "eval_count": 0},
                         "evaluation": {"token": 0, "node": 0, "eval_count": 1}}}}


def governed_profile():
    data = composed_profile()
    data["budget"] = {"name": "hierarchical", "options": {
        "limits": {"global": {"token": 100, "node": 10, "eval_count": 10},
                   "direction": {"token": 100}, "candidate": {"token": 100}},
        "reservation": {"token": 10, "node": 1, "eval_count": 1},
        "fidelity_rungs": [{"fidelity": "dev", "split_id": "dev", "seed_set": [1]}]}}
    data["governance"] = governance_data()
    return data


def test_absent_governance_keeps_exact_legacy_serialization():
    data = composed_profile()
    config = AssemblyConfig.from_dict(data)
    original = json.dumps(config.to_dict(), separators=(",", ":"))
    assert '"governance"' not in original
    assert AssemblyConfig.from_dict(json.loads(original)).to_dict() == json.loads(original)
    assert getattr(config, "governance", None) is None


def test_governance_roundtrip_is_detached_and_immutable():
    from core.composition.contracts import GovernanceConfig
    data = governed_profile()
    config = AssemblyConfig.from_dict(data)
    assert isinstance(config.governance, GovernanceConfig)
    data["governance"]["controls"]["seed"] = 100
    returned = config.governance.controls
    returned["seed"] = 200
    assert config.to_dict()["governance"]["controls"]["seed"] == 7
    assert AssemblyConfig.from_dict(config.to_dict()) == config


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema_version=True),
    lambda d: d.update(extra=1),
    lambda d: d["controls"].update(extra=1),
    lambda d: d["controls"].update(after_main_cycles=[0, 0]),
    lambda d: d["controls"].update(after_main_cycles=[0, True]),
    lambda d: d["controls"].update(after_main_cycles=[1]),
    lambda d: d["controls"].update(after_main_cycles=[]),
    lambda d: d["controls"].update(seed=True),
    lambda d: d["controls"]["request"].update(resume_from="parent"),
    lambda d: d["controls"]["request"].update(fidelity="final"),
    lambda d: d["controls"]["reservations"]["operator"].update(token=True),
    lambda d: d["controls"]["reservations"]["evaluation"].pop("token"),
])
def test_invalid_governance_fails_configuration(change):
    data = governed_profile()
    change(data["governance"])
    with pytest.raises(ValueError):
        AssemblyConfig.from_dict(data)


def test_explicit_null_governance_is_not_silent_opt_out():
    data = composed_profile()
    data["governance"] = None
    with pytest.raises(ValueError, match="governance"):
        AssemblyConfig.from_dict(data)


def test_frozen_plan_binds_initial_inputs_and_returns_detached_slots():
    from core.composition.governance import ControlPlan
    cfg = AssemblyConfig.from_dict(governed_profile()).governance
    initial = {"public": ["fixed"]}
    plan = ControlPlan.freeze(cfg, task_desc="task", initial_context=initial,
                              max_generations=2, units=("token", "node", "eval_count"))
    initial["public"].append("poison")
    view = plan.to_dict()
    assert view["initial_context"] == {"public": ["fixed"]}
    assert [(s["slot_id"], s["after_main_cycles"], s["seed"]) for s in view["slots"]] == [
        ("control-0000", 0, 7), ("control-0001", 2, 8)]
    view["slots"][0]["request"]["seed_set"].append(999)
    assert plan.to_dict()["slots"][0]["request"]["seed_set"] == [1]
    different = ControlPlan.freeze(cfg, task_desc="changed", initial_context={"public": ["fixed"]},
                                   max_generations=2, units=("token", "node", "eval_count"))
    assert different.plan_ref != plan.plan_ref
    with pytest.raises(ValueError, match="schedule"):
        ControlPlan.freeze(cfg, task_desc="task", initial_context={}, max_generations=0,
                           units=("token", "node", "eval_count"))


def test_unknown_control_factory_fails_before_any_constructor(tmp_path):
    registry = default_registry()
    called = []
    registry.register("provider", "main", lambda *_: called.append(True))
    data = governed_profile()
    data["provider"] = {"name": "main"}
    context = BuildContext(None, None, AppendOnlyStore(tmp_path / "events.jsonl"),
        ScopeContext("r", "t", "d"), SimpleNamespace(max_generations=2), tmp_path)
    with pytest.raises(ValueError, match="unregistered component: provider/fresh"):
        registry.build(data, context)
    assert called == []


@pytest.mark.parametrize("limits", [[], None, "invalid", 1])
def test_malformed_governed_budget_limits_raise_configuration_error(limits):
    data = governed_profile()
    data["budget"]["options"]["limits"] = limits
    with pytest.raises(ValueError, match="limits"):
        AssemblyConfig.from_dict(data)


@pytest.mark.parametrize("phase,unit,amount", [
    ("operator", "node", 0),
    ("evaluation", "eval_count", 0),
    ("evaluation", "node", 1),
])
def test_control_reservations_cover_actual_phase_counts_before_construction(tmp_path, phase, unit, amount):
    calls = []
    registry = default_registry()
    provider_capability = {"schema_version": 1, "fresh_session": True, "state_independent": True,
        "sampling": {"method": "deterministic_fixture", "parameters": {}, "applied": True},
        "call_bound": {"kind": "hard", "units": {"token": 10}}, "external_currency": False}
    registry.register("provider", "main", lambda *_: (calls.append("main") or (lambda prompt: "fixture")))
    registry.register("provider", "fresh", lambda *_: calls.append("control"),
                      governance=provider_capability)
    registry.register("domain", "fresh", lambda *_: calls.append("domain"), governance={
        "schema_version": 1, "fresh_session": True, "state_independent": True})
    data = governed_profile()
    data["provider"] = {"name": "main"}
    data["governance"]["controls"]["reservations"][phase][unit] = amount
    context = BuildContext(None, lambda *_: None, AppendOnlyStore(tmp_path / "events.jsonl"),
        ScopeContext("r", "t", "d"), SimpleNamespace(max_generations=2), tmp_path)
    with pytest.raises(ValueError, match="control.*reservation|evaluation.*node"):
        registry.build(data, context)
    assert calls == []
