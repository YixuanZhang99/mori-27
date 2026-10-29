"""Explicit component registration and side-effect-free configuration preflight."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Callable

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


class Registry:
    """Trusted factories selected only by names registered in the calling process.

    Validators are pure preflight functions. Factories receive detached options
    and must construct components rather than invoke models or run experiments.
    All names and options are checked before the first factory is invoked.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _Registration] = {}

    def register(self, kind: str, name: str, factory: Factory, *,
                 validate_options: OptionValidator | None = None) -> None:
        if type(kind) is not str or kind not in KINDS:
            raise ValueError(f"unknown component kind: {kind}")
        ComponentSpec(name)
        key = (kind, name)
        if key in self._entries:
            raise ValueError(f"component already registered: {kind}/{name}")
        if not callable(factory) or (validate_options is not None and not callable(validate_options)):
            raise ValueError("component factory and option validator must be callable")
        self._entries[key] = _Registration(factory, validate_options or _no_options)

    def preflight(self, config: AssemblyConfig | dict[str, Any]) -> AssemblyConfig:
        if isinstance(config, AssemblyConfig):
            snapshot = AssemblyConfig.from_dict(config.to_dict())
        else:
            snapshot = AssemblyConfig.from_dict(config)
        for kind, spec in self._specs(snapshot):
            registration = self._entries.get((kind, spec.name))
            if registration is None:
                raise ValueError(f"unregistered component: {kind}/{spec.name}")
            options = json_copy(spec.options)
            result = registration.validate_options(options)
            if result is not None:
                raise ValueError(f"option validator must return None: {kind}/{spec.name}")
            if json.dumps(json_copy(options), sort_keys=True) != json.dumps(spec.options, sort_keys=True):
                raise ValueError(f"option validator mutated configuration: {kind}/{spec.name}")
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

    def build(self, config: AssemblyConfig | dict[str, Any],
              context: BuildContext) -> dict[str, Any]:
        if not isinstance(context, BuildContext):
            raise ValueError("assembly requires a BuildContext")
        snapshot = self.preflight(config)
        components: dict[str, Any] = {"operators": [], "skills": []}
        active_context = context
        for kind, spec in self._specs(snapshot):
            registration = self._entries[(kind, spec.name)]
            component = registration.factory(active_context, json_copy(spec.options))
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
                active_context = replace(active_context, evaluator=component)
            if kind == "operator":
                components["operators"].append(component)
            elif kind == "skill":
                components["skills"].append(component)
            else:
                components[kind] = component
        components["operators"] = tuple(components["operators"])
        components["skills"] = tuple(components["skills"])
        return components
