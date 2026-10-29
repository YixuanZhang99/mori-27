"""Composition configuration is fully checked before any component construction."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.contracts import AssemblyConfig, BuildContext, ComponentSpec, Decision
from core.composition.registry import Registry
from core.budget.types import AccountingStamp
from core.memory.types import ScopeContext
from core.x1.store import AppendOnlyStore


def config_data():
    data = {key: {"name": key + "-test"} for key in (
        "provider", "domain", "policy", "frontier", "memory", "executor", "admission", "budget")}
    return {"schema_version": 1, "name": "composition-test", **data,
            "operators": [{"name": "draft-test"}, {"name": "improve-test"}],
            "skills": [{"name": "skill-test"}]}


def context(tmp_path):
    return BuildContext(object(), object(), AppendOnlyStore(tmp_path / "events.jsonl"),
                        ScopeContext("run", "task", "domain"), object(), tmp_path,
                        accounting_stamp=object())


def registry_and_calls():
    registry, calls = Registry(), []
    for kind in ("provider", "domain", "policy", "frontier", "memory", "executor",
                 "admission", "budget", "skill"):
        def factory(ctx, options, kind=kind):
            calls.append((kind, ctx, options))
            if kind == "provider":
                return ProviderSentinel()
            return {"kind": kind}
        registry.register(kind, kind + "-test", factory)
    for name in ("draft-test", "improve-test"):
        def factory(ctx, options, name=name):
            calls.append((name, ctx, options))
            return {"kind": name}
        registry.register("operator", name, factory)
    return registry, calls


class ProviderSentinel:
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {"total_tokens": 0}
        return prompt


def test_complete_build_links_provider_and_domain_without_mutating_original_context(tmp_path):
    config = AssemblyConfig.from_dict(config_data())
    original = context(tmp_path)
    registry, calls = registry_and_calls()
    modules = registry.build(config, original)
    assert calls[0][0] == "provider" and calls[0][1] is original
    assert isinstance(modules["provider"].raw_provider, ProviderSentinel)
    assert calls[1][0] == "domain"
    assert calls[1][1].llm is modules["provider"]
    assert calls[1][1].evaluator is original.evaluator
    assert all(ctx.llm is modules["provider"] and ctx.evaluator is modules["domain"]
               for _, ctx, _ in calls[2:])
    assert all(ctx.accounting_stamp is original.accounting_stamp for _, ctx, _ in calls)
    assert original.llm is not modules["provider"] and original.evaluator is not modules["domain"]
    assert [operator["kind"] for operator in modules["operators"]] == ["draft-test", "improve-test"]
    assert modules["skills"] == ({"kind": "skill"},)
    assert not original.store.path.exists()


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 1.0), ("schema_version", 2),
    ("name", ""), ("name", " spaced "), ("mode", "production"),
    ("mode", None), ("operators", []), ("operators", "draft"),
    ("operators", [{"name": "draft-test"}, {"name": "draft-test"}]),
    ("operators", ["draft"]), ("skills", None),
    ("provider", "provider-test"), ("knowledge", {"name": "knowledge-test"}),
    ("knowledge", False),
])
def test_invalid_configuration_is_rejected_before_any_factory(tmp_path, field, value):
    data = config_data()
    data[field] = value
    registry, calls = registry_and_calls()
    ctx = context(tmp_path)
    with pytest.raises(ValueError):
        registry.build(data, ctx)
    assert calls == [] and not ctx.store.path.exists()


def test_missing_and_unknown_fields_are_not_silently_ignored():
    missing = config_data()
    del missing["budget"]
    with pytest.raises(ValueError, match="missing fields: budget"):
        AssemblyConfig.from_dict(missing)
    unknown = config_data()
    unknown["budegt"] = {"name": "budget-test"}
    with pytest.raises(ValueError, match="unknown assembly fields: budegt"):
        AssemblyConfig.from_dict(unknown)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), object(), {1: "key"}, (1, 2)])
def test_non_json_options_fail_before_any_factory(tmp_path, invalid):
    data = config_data()
    data["skills"][0]["options"] = {"value": invalid}
    registry, calls = registry_and_calls()
    with pytest.raises(ValueError, match="finite JSON"):
        registry.build(data, context(tmp_path))
    assert calls == []


def test_last_unknown_component_is_resolved_before_first_factory(tmp_path):
    data = config_data()
    data["skills"].append({"name": "not-registered"})
    registry, calls = registry_and_calls()
    with pytest.raises(ValueError, match="unregistered component: skill/not-registered"):
        registry.build(data, context(tmp_path))
    assert calls == []


def test_all_option_validators_run_before_any_factory(tmp_path):
    data = config_data()
    data["skills"] = [{"name": "validated-skill", "options": {"count": 0}}]
    registry, calls = registry_and_calls()
    def validate(options):
        if set(options) != {"count"} or type(options["count"]) is not int or options["count"] < 1:
            raise ValueError("count must be a positive integer")
    registry.register("skill", "validated-skill", lambda *_: calls.append("unexpected"),
                      validate_options=validate)
    with pytest.raises(ValueError, match="positive integer"):
        registry.build(data, context(tmp_path))
    assert calls == []


def test_unvalidated_options_fail_closed_before_construction(tmp_path):
    data = config_data()
    data["budget"]["options"] = {"ceiling": 1_000}
    registry, calls = registry_and_calls()
    with pytest.raises(ValueError, match="explicit validator"):
        registry.build(data, context(tmp_path))
    assert calls == []


@pytest.mark.parametrize("validator", [lambda options: False,
                                      lambda options: options.update(count=True)])
def test_invalid_validator_result_or_type_mutation_is_rejected_before_factories(tmp_path, validator):
    data = config_data()
    data["skills"] = [{"name": "bad-validator", "options": {"count": 1}}]
    registry, calls = registry_and_calls()
    registry.register("skill", "bad-validator", lambda *_: object(), validate_options=validator)
    with pytest.raises(ValueError, match="option validator"):
        registry.build(data, context(tmp_path))
    assert calls == []


def test_registry_cannot_overwrite_existing_factory():
    registry = Registry()
    registry.register("policy", "same", lambda *_: "first")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("policy", "same", lambda *_: "second")


@pytest.mark.parametrize("metadata", [{"model": "different-model"},
                                     {"supplier": "different-supplier"}])
def test_provider_stamp_mismatch_fails_before_domain_construction_or_provider_calls(tmp_path, metadata):
    data = config_data()
    data["provider"] = {"name": "different"}
    provider = ProviderSentinel()
    for key, value in metadata.items():
        setattr(provider, key, value)
    registry, calls = registry_and_calls()
    registry.register("provider", "different", lambda *_: provider)
    original = context(tmp_path)
    bound = BuildContext(original.llm, original.evaluator, original.store,
                         original.scope_context, original.loop_config, original.workdir,
                         AccountingStamp("expected-supplier", "expected-model", "t", "p", "d"))
    with pytest.raises(ValueError, match="differs from accounting_stamp"):
        registry.build(data, bound)
    assert calls == [] and provider.calls == 0
    assert not original.store.path.exists()


def test_provider_factory_cannot_return_noncallable_before_other_construction(tmp_path):
    data = config_data()
    data["provider"] = {"name": "not-callable"}
    registry, calls = registry_and_calls()
    registry.register("provider", "not-callable", lambda *_: object())
    with pytest.raises(ValueError, match="callable provider"):
        registry.build(data, context(tmp_path))
    assert calls == []


@pytest.mark.parametrize("kind,name,factory,validator", [
    ("unknown", "test", lambda *_: None, None),
    ("policy", "", lambda *_: None, None),
    ("policy", "test", None, None),
    ("policy", "test", lambda *_: None, "not-callable"),
])
def test_invalid_registration_is_rejected(kind, name, factory, validator):
    with pytest.raises(ValueError):
        Registry().register(kind, name, factory, validate_options=validator)


def test_schema_roundtrip_is_detached_from_callers_and_factories(tmp_path):
    data = config_data()
    data["skills"] = [{"name": "nested", "options": {"notes": ["original"]}}]
    config = AssemblyConfig.from_dict(data)
    data["skills"][0]["options"]["notes"].append("caller change")
    snapshot = config.to_dict()
    assert snapshot["skills"][0]["options"]["notes"] == ["original"]
    snapshot["skills"][0]["options"]["notes"].append("returned change")
    registry, _ = registry_and_calls()
    def factory(ctx, options):
        options["notes"].append("factory change")
        return options
    registry.register("skill", "nested", factory, validate_options=lambda options: None)
    first = registry.build(config, context(tmp_path))
    second = registry.build(config, context(tmp_path))
    assert first["skills"] == second["skills"] == ({"notes": ["original", "factory change"]},)
    assert config.to_dict()["skills"][0]["options"]["notes"] == ["original"]
    assert AssemblyConfig.from_dict(config.to_dict()) == config


def test_mutated_config_options_are_revalidated_before_build(tmp_path):
    config = AssemblyConfig.from_dict(config_data())
    config.budget.options["ceiling"] = float("nan")
    registry, calls = registry_and_calls()
    with pytest.raises(ValueError, match="finite JSON"):
        registry.build(config, context(tmp_path))
    assert calls == []


def test_only_component_spec_name_and_options_are_accepted():
    with pytest.raises(ValueError, match="optional options only"):
        ComponentSpec.from_dict({"name": "some", "module": "arbitrary.python.module"})


def test_optional_skills_and_mode_have_explicit_safe_defaults():
    data = config_data()
    del data["skills"]
    config = AssemblyConfig.from_dict(data)
    assert config.skills == () and config.mode == "benchmark" and config.knowledge is None


@pytest.mark.parametrize("admit,reason", [(1, "numeric"), (False, ""), (True, None)])
def test_decision_requires_a_boolean_and_a_reason(admit, reason):
    with pytest.raises(ValueError, match="boolean admit"):
        Decision(admit, reason)
