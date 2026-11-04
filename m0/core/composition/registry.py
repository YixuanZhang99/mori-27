"""Explicit component registration and side-effect-free configuration preflight."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, replace
from typing import Any, Callable
from pathlib import Path

from core.composition.contracts import AssemblyConfig, BuildContext, ComponentSpec, json_copy
from core.composition.provider import MeteredProvider

Factory = Callable[[BuildContext, dict[str, Any]], Any]
OptionValidator = Callable[[dict[str, Any]], None]
KINDS = frozenset({"provider", "domain", "policy", "operator", "frontier", "memory",
                   "executor", "admission", "budget", "skill", "knowledge"})


def _no_options(options: dict[str, Any]) -> None:
    if options:
        raise ValueError("component does not accept options without an explicit validator")


@dataclass(frozen=True)
class _Registration:
    factory: Factory
    validate_options: OptionValidator
    governance: dict[str, Any] | None = None


class Registry:
    """Trusted factories selected only by names registered in the calling process.

    Validators are pure preflight functions. Factories receive detached options
    and must construct components rather than invoke models or run experiments.
    All names and options are checked before the first factory is invoked.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _Registration] = {}
        self._session_objects: dict[str, list[Any]] = {}
        self._external_bridges: dict[str, Any] = {}
        self._external_bridge_instances: list[Any] = []

    def install_external_bridge(self, name, factory):
        """Install a trusted zero-argument factory without constructing its authority."""
        ComponentSpec(name)
        if not callable(factory):
            raise ValueError("external bridge registration requires a callable factory")
        if name in self._external_bridges:
            raise ValueError("external bridge is already installed")
        self._external_bridges[name] = factory

    @property
    def external_bridge_names(self):
        return tuple(sorted(self._external_bridges))

    def external_bridge_name(self, config):
        """Resolve the versioned control bridge before choosing runtime/checkpoint identity."""
        snapshot = self.preflight(config)
        if snapshot.governance is None:
            return None
        spec = snapshot.governance.controls["provider"]
        declaration = self._entries[("provider", spec["name"])].governance
        if declaration["schema_version"] == 1:
            return None
        return declaration["external_currency"]["bridge"]

    def external_bridge(self, name):
        if name not in self._external_bridges:
            raise ValueError("external bridge is not explicitly installed")
        bridge = self._external_bridges[name]()
        methods = ("bind_run", "invoke", "recover", "finish_control", "audit", "replay_bundle")
        if any(not callable(getattr(bridge, method, None)) for method in methods):
            raise ValueError("external bridge must implement the complete versioned integration port")
        if any(bridge is previous for previous in self._external_bridge_instances):
            raise ValueError("external bridge factory reused an existing run authority instance")
        self._external_bridge_instances.append(bridge)
        return bridge

    def register(self, kind: str, name: str, factory: Factory, *,
                 validate_options: OptionValidator | None = None,
                 governance: dict[str, Any] | None = None) -> None:
        if type(kind) is not str or kind not in KINDS:
            raise ValueError(f"unknown component kind: {kind}")
        ComponentSpec(name)
        key = (kind, name)
        if key in self._entries:
            raise ValueError(f"component already registered: {kind}/{name}")
        if not callable(factory) or (validate_options is not None and not callable(validate_options)):
            raise ValueError("component factory and option validator must be callable")
        self._entries[key] = _Registration(factory, validate_options or _no_options,
            json_copy(governance, label="factory governance") if governance is not None else None)

    def preflight(self, config: AssemblyConfig | dict[str, Any]) -> AssemblyConfig:
        if isinstance(config, AssemblyConfig):
            snapshot = AssemblyConfig.from_dict(config.to_dict())
        else:
            snapshot = AssemblyConfig.from_dict(config)
        for kind, spec in (*self._specs(snapshot), *self._control_specs(snapshot)):
            registration = self._entries.get((kind, spec.name))
            if registration is None:
                raise ValueError(f"unregistered component: {kind}/{spec.name}")
            options = json_copy(spec.options)
            result = registration.validate_options(options)
            if result is not None:
                raise ValueError(f"option validator must return None: {kind}/{spec.name}")
            if json.dumps(json_copy(options), sort_keys=True) != json.dumps(spec.options, sort_keys=True):
                raise ValueError(f"option validator mutated configuration: {kind}/{spec.name}")
        if snapshot.governance is not None:
            self._preflight_governance(snapshot)
        return snapshot

    @staticmethod
    def _specs(config: AssemblyConfig):
        for kind in ("provider", "domain", "policy", "frontier", "memory", "executor",
                     "admission", "budget"):
            yield kind, getattr(config, kind)
        for spec in config.operators:
            yield "operator", spec
        for spec in config.skills:
            yield "skill", spec
        if config.knowledge is not None:
            yield "knowledge", config.knowledge

    @staticmethod
    def _control_specs(config):
        if config.governance is not None:
            controls = config.governance.controls
            for kind in ("provider", "domain", "operator"):
                yield kind, ComponentSpec.from_dict(controls[kind])

    def _preflight_governance(self, config):
        from core.composition.governance import validate_factory_governance
        controls = config.governance.controls
        for kind, spec in self._control_specs(config):
            declared = self._entries[(kind, spec.name)].governance
            validate_factory_governance(kind, declared,
                reservation=controls["reservations"]["operator"] if kind == "provider" else None,
                phase_reservations=controls["reservations"] if kind == "provider" else None,
                external_bridges=self.external_bridge_names)

    @staticmethod
    def _construct(registration, context, options):
        if context.governance is None:
            return registration.factory(context, options)
        frozen_scope = json_copy(context.invocation_scope)
        frozen_governance = json_copy(context.governance)
        context = replace(context, invocation_scope=json_copy(frozen_scope),
                          governance=json_copy(frozen_governance))
        component = registration.factory(context, options)
        if json.dumps(json_copy(context.invocation_scope), sort_keys=True) != json.dumps(frozen_scope, sort_keys=True):
            raise ValueError("component factory mutated frozen invocation scope")
        if json.dumps(json_copy(context.governance), sort_keys=True) != json.dumps(frozen_governance, sort_keys=True):
            raise ValueError("component factory mutated frozen governance")
        return component

    @staticmethod
    def _raw_identities(component):
        # Unwrap only declared adapter links; never deepcopy or traverse arbitrary
        # application state. Hidden shared state remains the trusted factory's duty.
        raw = component
        while isinstance(raw, MeteredProvider):
            raw = raw.raw_provider
        result = [raw]
        evaluator = getattr(raw, "evaluator", None)
        if evaluator is not None and evaluator is not raw:
            result.append(evaluator)
        return result

    def _remember_session(self, context, components, *, control=False):
        key = context.scope_context.run_id
        known = self._session_objects.setdefault(key, [])
        current = []
        forbidden = [*known, *self._raw_identities(context.llm),
                     *self._raw_identities(context.evaluator)] if control else []
        for kind in ("provider", "domain", "operator", "executor"):
            if kind not in components:
                continue
            for value in self._raw_identities(components[kind]):
                if value is not None and control and any(value is previous for previous in forbidden):
                    raise ValueError(f"control {kind} reused a main or prior control session")
                if value is not None:
                    current.append(value)
        known.extend(current)

    def build_control(self, config: AssemblyConfig | dict[str, Any],
                      context: BuildContext, slot: dict[str, Any]) -> dict[str, Any]:
        """Construct a declared independent draw without exposing live main state."""
        from core.composition.governance import LaneStoreView, validate_factory_governance
        from core.executor.types import EvalRequest
        if not isinstance(context, BuildContext):
            raise ValueError("control assembly requires a BuildContext")
        snapshot = self.preflight(config)
        if snapshot.governance is None:
            raise ValueError("control construction requires governance")
        controls = snapshot.governance.controls
        slot = json_copy(slot, label="control slot")
        fields = {"slot_id", "after_main_cycles", "seed", "provider", "domain", "operator",
                  "request", "reservations"}
        if type(slot) is not dict or set(slot) != fields:
            raise ValueError("control slot must contain exactly its frozen plan fields")
        try:
            index = controls["after_main_cycles"].index(slot["after_main_cycles"])
        except ValueError as error:
            raise ValueError("control slot schedule differs from frozen governance") from error
        expected = {"slot_id": f"control-{index:04d}",
                    "after_main_cycles": controls["after_main_cycles"][index],
                    "seed": controls["seed"] + index,
                    **{name: controls[name] for name in (
                        "provider", "domain", "operator", "request", "reservations")}}
        if json.dumps(slot, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError("control slot differs from frozen governance")
        maximum = getattr(context.loop_config, "max_generations", None)
        if type(maximum) is not int or controls["after_main_cycles"][-1] > maximum + 1:
            raise ValueError("control schedule exceeds max_generations + 1")
        scope = {"lane": "control", "slot_id": slot["slot_id"], "seed": slot["seed"]}
        active = replace(context, llm=None, evaluator=None, mode=snapshot.mode,
            governance=snapshot.governance.to_dict(), invocation_scope=scope,
            workdir=Path(context.workdir) / "controls" / slot["slot_id"])
        parts = {}
        for kind, spec in (*self._control_specs(snapshot), ("executor", snapshot.executor)):
            options = json_copy(spec.options)
            if kind == "executor" and spec.name == "git_worktree" and "run_root" in options:
                options["run_root"] = str(Path(options["run_root"]) / "controls" / slot["slot_id"])
            factory_context = active if kind == "executor" else replace(active,
                store=LaneStoreView(context.store, lane="control", slot_id=slot["slot_id"], component=kind))
            component = self._construct(self._entries[(kind, spec.name)], factory_context, options)
            if kind == "provider":
                if not callable(component):
                    raise ValueError("control provider factory must return a callable provider")
                if not isinstance(component, MeteredProvider):
                    component = MeteredProvider(component)
                binding_method = getattr(component, "governance_binding", None)
                if not callable(binding_method):
                    raise ValueError("control provider requires governance_binding()")
                binding = validate_factory_governance("provider", binding_method(),
                    reservation=controls["reservations"]["operator"],
                    phase_reservations=controls["reservations"], external_bridges=self.external_bridge_names)
                declared = self._entries[(kind, spec.name)].governance
                if json.dumps(binding, sort_keys=True) != json.dumps(declared, sort_keys=True):
                    raise ValueError("provider binding differs from preflight declaration")
                parts["governance_binding"] = binding
                active = replace(active, llm=component)
            elif kind == "domain":
                if not callable(getattr(component, "validate_request", None)) or not callable(
                        getattr(component, "evaluate", None)):
                    raise ValueError("control domain must implement evaluate and validate_request")
                component.validate_request(EvalRequest(**slot["request"]))
                active = replace(active, evaluator=component)
            parts[kind] = component
        self._remember_session(context, parts, control=True)
        parts["invocation_scope"] = json_copy(scope)
        return parts

    def build(self, config: AssemblyConfig | dict[str, Any],
              context: BuildContext) -> dict[str, Any]:
        if not isinstance(context, BuildContext):
            raise ValueError("assembly requires a BuildContext")
        snapshot = self.preflight(config)
        components: dict[str, Any] = {"operators": [], "skills": []}
        active_context = context if context.mode == snapshot.mode else replace(context, mode=snapshot.mode)
        governed = snapshot.governance is not None
        if governed:
            maximum = getattr(context.loop_config, "max_generations", None)
            if type(maximum) is not int or snapshot.governance.controls["after_main_cycles"][-1] > maximum + 1:
                raise ValueError("control schedule exceeds max_generations + 1")
            active_context = replace(active_context, governance=snapshot.governance.to_dict(),
                                     invocation_scope={"lane": "main"})
        for kind, spec in self._specs(snapshot):
            registration = self._entries[(kind, spec.name)]
            factory_context = active_context
            if governed and kind not in {"budget", "executor"}:
                from core.composition.governance import LaneStoreView
                factory_context = replace(active_context, store=LaneStoreView(context.store,
                    lane="main", component=kind))
            component = self._construct(registration, factory_context, json_copy(spec.options))
            if kind == "provider":
                if not callable(component):
                    raise ValueError("provider factory must return a callable provider")
                if not isinstance(component, MeteredProvider):
                    component = MeteredProvider(component)
                stamp = active_context.accounting_stamp
                for attribute, field in (("model", "model_version"), ("supplier", "supplier")):
                    actual = getattr(component, attribute, "unavailable")
                    declared = getattr(stamp, field, "unavailable")
                    if (isinstance(actual, str) and actual.strip() and actual != "unavailable"
                            and isinstance(declared, str) and declared.strip()
                            and declared != "unavailable" and actual != declared):
                        raise ValueError(f"configured provider {attribute} differs from accounting_stamp")
                active_context = replace(active_context, llm=component)
            elif kind == "domain":
                identity = {"name": spec.name, "version": getattr(component, "evaluator_version", None),
                            "evaluation_context": getattr(component, "evaluation_context", "")}
                domain_id = "sha256:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                active_context = replace(active_context, evaluator=component,
                    scope_context=replace(active_context.scope_context, domain_id=domain_id))
            if kind == "operator":
                components["operators"].append(component)
            elif kind == "skill":
                components["skills"].append(component)
            else:
                components[kind] = component
        components["operators"] = tuple(components["operators"])
        components["skills"] = tuple(components["skills"])
        if governed:
            self._remember_session(context, components)
            self._session_objects[context.scope_context.run_id].extend(components["operators"])
        return components
