"""Immutable integration ports for explicitly installed external authorities.

Core binds identities and finite physical envelopes. Pricing, transport, private
outcome storage and monetary policy remain owned by the task adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, ClassVar, Protocol

from core.composition.contracts import json_copy

EXTERNAL_RUNTIME = "composed-v8-governed-external"


def _canonical(value):
    return json.dumps(json_copy(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _text(value, label):
    if type(value) is not str or not value or value != value.strip() or len(value) > 1024:
        raise ValueError(f"{label} requires bounded nonempty text")


def _hash(value, label, *, prefix=False, length=64):
    pattern = ("sha256:" if prefix else "") + "[0-9a-f]{" + str(length) + "}"
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise ValueError(f"{label} requires a canonical hash identity")


def _runtime(value):
    if value != EXTERNAL_RUNTIME:
        raise ValueError("external authority requires composed-v8-governed-external")


def external_session_id(logical_run_id, lane, slot_id, adapter_binding_sha256):
    _hash(logical_run_id, "logical run", length=32)
    _hash(adapter_binding_sha256, "adapter binding")
    if lane not in {"main", "control"} or lane == "main" and slot_id is not None:
        raise ValueError("session lane and slot are inconsistent")
    if lane == "control":
        _text(slot_id, "control slot")
    return _digest({"logical_run_id": logical_run_id, "lane": lane, "slot_id": slot_id,
                    "adapter_binding_sha256": adapter_binding_sha256})


def external_call_id(context, wire_request_sha256):
    if not isinstance(context, GovernedCallContext):
        raise ValueError("external call identity requires a validated call context")
    _hash(wire_request_sha256, "wire request")
    return _digest({"schema_version": 1, "context": context.to_dict(),
                    "wire_request_sha256": wire_request_sha256})


@dataclass(frozen=True, init=False)
class _JSONPort:
    _json: str = field(repr=False)
    FIELDS: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, **values):
        values = json_copy(values, label=type(self).__name__)
        if set(values) != self.FIELDS:
            raise ValueError(f"{type(self).__name__} requires exactly its versioned fields")
        self._validate(values)
        object.__setattr__(self, "_json", _canonical(values))

    def __getattr__(self, name):
        if name in self.FIELDS:
            return self.to_dict()[name]
        raise AttributeError(name)

    def to_dict(self):
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, value, **capabilities):
        if type(value) is not dict:
            raise ValueError(f"{cls.__name__} requires a JSON object")
        return cls(**value, **capabilities)


@dataclass(frozen=True, init=False)
class GovernedCallContext(_JSONPort):
    FIELDS = frozenset({"schema_version", "runtime_id", "logical_run_id", "currency_run_id",
        "campaign_id", "policy_sha256", "physical_plan_ref", "bridge_plan_ref", "lane", "slot_id",
        "candidate_id", "intent_id", "physical_fingerprint", "account", "operation", "phase",
        "ordinal", "adapter_binding_sha256", "session_id", "argument_sha256"})

    @staticmethod
    def _validate(value):
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("external call context requires schema version 1")
        _runtime(value["runtime_id"])
        for key in ("logical_run_id", "campaign_id"):
            _hash(value[key], key, length=32)
        for key in ("currency_run_id", "policy_sha256", "adapter_binding_sha256", "session_id", "argument_sha256"):
            _hash(value[key], key)
        for key in ("physical_plan_ref", "bridge_plan_ref", "physical_fingerprint"):
            _hash(value[key], key, prefix=True)
        for key in ("candidate_id", "intent_id"):
            _text(value[key], key)
        if type(value["ordinal"]) is not int or value["ordinal"] < 0:
            raise ValueError("external provider ordinal must be a nonnegative integer")
        operation = value["operation"]
        if operation not in {"planning", "operator", "dev", "dev_baseline", "anchor", "admission", "final"}:
            raise ValueError("external call requires a known physical operation")
        phase = operation if operation in {"planning", "operator"} else "evaluation"
        if value["phase"] != phase:
            raise ValueError("external call phase differs from its physical operation")
        account = value["account"]
        if value["lane"] == "control":
            if account != "control" or operation not in {"operator", "dev"}:
                raise ValueError("control call cannot claim a main account or operation")
        elif value["lane"] == "main":
            allowed = {"overhead"} if operation == "planning" else {"reeval"} if operation in {
                "dev_baseline", "anchor", "admission", "final"} else {"explore", "exploit", "reeval"}
            if account not in allowed:
                raise ValueError("main call account differs from physical operation")
        if value["session_id"] != external_session_id(value["logical_run_id"], value["lane"],
                                                      value["slot_id"], value["adapter_binding_sha256"]):
            raise ValueError("external session identity differs from frozen scope")


@dataclass(frozen=True, init=False)
class ExternalPlanBinding(_JSONPort):
    FIELDS = frozenset({"schema_version", "runtime_id", "logical_run_id", "physical_plan_ref",
                       "bridge_plan_ref", "authority_binding"})

    @staticmethod
    def _validate(value):
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("external plan binding requires schema version 1")
        _runtime(value["runtime_id"])
        _hash(value["logical_run_id"], "logical run", length=32)
        for key in ("physical_plan_ref", "bridge_plan_ref"):
            _hash(value[key], key, prefix=True)
        if type(value["authority_binding"]) is not dict or not value["authority_binding"]:
            raise ValueError("external plan requires an opaque authority binding object")


@dataclass(frozen=True, init=False)
class ExternalRunContext(_JSONPort):
    store: Any = field(repr=False, compare=False)
    physical_identity_lookup: Any = field(repr=False, compare=False)
    provider_sessions: Any = field(repr=False, compare=False)
    FIELDS = frozenset({"logical_run_id", "runtime_id", "workdir", "physical_plan",
        "main_provider_binding", "control_provider_bindings", "mode", "recorded_bundle"})

    def __init__(self, *, store, physical_identity_lookup, provider_sessions, **values):
        super().__init__(**values)
        if not callable(physical_identity_lookup) or type(provider_sessions) is not dict:
            raise ValueError("external run requires trusted identity lookup and provider sessions")
        if set(provider_sessions) != {"main", *values["control_provider_bindings"]} or any(
                not callable(session) for session in provider_sessions.values()):
            raise ValueError("external run sessions must match main and all frozen control slots")
        object.__setattr__(self, "store", store)
        object.__setattr__(self, "physical_identity_lookup", physical_identity_lookup)
        object.__setattr__(self, "provider_sessions", MappingProxyType(dict(provider_sessions)))

    @staticmethod
    def _validate(value):
        _runtime(value["runtime_id"])
        _hash(value["logical_run_id"], "logical run", length=32)
        _text(value["workdir"], "work directory")
        if not Path(value["workdir"]).is_absolute():
            raise ValueError("external run requires an absolute work directory")
        for key in ("physical_plan", "main_provider_binding", "control_provider_bindings"):
            if type(value[key]) is not dict or not value[key]:
                raise ValueError(f"external run requires {key} object")
        if value["mode"] == "live":
            if value["recorded_bundle"] is not None:
                raise ValueError("live external run cannot supply a recorded proof bundle")
        elif value["mode"] == "recorded":
            if type(value["recorded_bundle"]) is not dict or not value["recorded_bundle"]:
                raise ValueError("recorded external run requires a private proof bundle")
        else:
            raise ValueError("external run mode must be live or recorded")


@dataclass(frozen=True, init=False)
class ExternalCallOutcome(_JSONPort):
    FIELDS = frozenset({"call_id", "context_sha256", "wire_request_sha256", "response_sha256",
        "usage", "result", "outcome", "currency_state", "integrity_reason", "outcome_ref", "provider_state"})

    @staticmethod
    def _validate(value):
        for key in ("call_id", "context_sha256", "wire_request_sha256"):
            _hash(value[key], key)
        _hash(value["outcome_ref"], "outcome reference", prefix=True)
        if value["response_sha256"] is not None:
            _hash(value["response_sha256"], "response")
        if value["result"] is not None and type(value["result"]) is not str:
            raise ValueError("external result must be text or null")
        reason = value["integrity_reason"]
        if reason is not None and (type(reason) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason) is None):
            raise ValueError("integrity reason must be a stable category, never exception text")
        usage = value["usage"]
        if usage is not None:
            if type(usage) is not dict or "total_tokens" not in usage or type(usage["total_tokens"]) is not int or usage["total_tokens"] < 0:
                raise ValueError("known external usage requires nonnegative total tokens")
            allowed = {"total_tokens", "prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens",
                       "prompt_cache_miss_tokens", "prompt_tokens_details", "completion_tokens_details"}
            if set(usage) - allowed:
                raise ValueError("external usage contains unsupported fields")
            for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                if key in usage and (type(usage[key]) is not int or not 0 <= usage[key] <= usage["total_tokens"]):
                    raise ValueError("external usage counts must be bounded nonnegative integers")
            if {"prompt_tokens", "completion_tokens"} <= set(usage) and usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
                raise ValueError("external usage totals disagree")
            for key, count, bound in (("prompt_tokens_details", "cached_tokens", "prompt_tokens"),
                                      ("completion_tokens_details", "reasoning_tokens", "completion_tokens")):
                if key in usage:
                    details = usage[key]
                    if type(details) is not dict or set(details) - {count} or count in details and (
                            type(details[count]) is not int or not 0 <= details[count] <= usage.get(bound, usage["total_tokens"])):
                        raise ValueError("external usage detail exceeds its measured total")
        outcome, currency = value["outcome"], value["currency_state"]
        if outcome == "returned":
            if currency != "settled" or usage is None or value["result"] is None or value["response_sha256"] is None or reason is not None:
                raise ValueError("returned external outcome requires settled authoritative usage and response")
        elif outcome == "known_failed":
            if currency != "settled" or usage is None or value["response_sha256"] is None or reason is None:
                raise ValueError("known external failure requires a settled known bill and category")
        elif outcome == "known_refused":
            if currency != "not_admitted" or usage is None or usage["total_tokens"] != 0 or value["result"] is not None or value["response_sha256"] is not None or reason is None:
                raise ValueError("known refusal must prove no admission and explicit zero usage")
        elif outcome == "unknown":
            if currency != "pending":
                raise ValueError("unknown external outcome must retain pending currency authority")
        else:
            raise ValueError("unsupported external outcome state")


def validate_external_ordinal(binding, phase, ordinal):
    """Finite call counts apply even when every earlier response used zero tokens."""
    caps = binding.get("phase_call_limits") if type(binding) is dict else None
    if type(caps) is not dict or phase not in {"operator", "evaluation"} or \
            type(ordinal) is not int or ordinal < 0 or type(caps.get(phase)) is not int or ordinal >= caps[phase]:
        raise ValueError("external call ordinal exceeds its frozen phase limit")


class ExternalProviderBridge(Protocol):
    def bind_run(self, context: ExternalRunContext) -> ExternalPlanBinding: ...
    def invoke(self, context: GovernedCallContext, args: tuple, kwargs: dict) -> str: ...
    def recover(self, context: GovernedCallContext, argument_sha256: str) -> ExternalCallOutcome: ...
    def finish_control(self, slot_id: str, terminal_ref: str) -> None: ...
    def audit(self) -> dict: ...
    def replay_bundle(self) -> dict: ...
