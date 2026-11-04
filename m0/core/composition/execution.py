"""Durable M7 construction and reuse of immutable native artifacts.

Physical reservation and settlement remain the invocation owner's responsibility.
This module owns artifact/result persistence, not a second accounting authority.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from core.composition.artifacts import NativeArtifactBackend
from core.composition.git_artifacts import GitArtifactBackend
from core.composition.construction import (ConstructionIntegrityError, ConstructionPlan,
    ConstructionResult, decode_construction_outcome, _json, _ref)
from core.composition.contracts import OperatorFailure, Proposal, json_copy
from core.composition.defaults import InProcessExecutor
from core.composition.evaluation import binding_for, decode_evidence
from core.composition.recovery import ContinuationStore
from core.llm import UsageError
from core.x1.checkpoint import payload_digest


def _operation(value):
    value = json_copy(value, label="candidate execution operation")
    required = {"run_id", "cycle", "phase", "intent_id", "fingerprint", "manifest_sha256", "lane", "slot_id"}
    if type(value) is not dict or set(value) != required or type(value["cycle"]) is not int \
            or value["cycle"] < 0 or value["lane"] not in {"main", "control"}:
        raise ValueError("invalid candidate execution operation")
    for key in ("run_id", "phase", "intent_id", "fingerprint", "manifest_sha256"):
        if type(value[key]) is not str or not value[key].strip():
            raise ValueError("operation requires explicit stable identities")
    if value["lane"] == "main" and value["slot_id"] is not None or value["lane"] == "control" and (
            type(value["slot_id"]) is not str or not value["slot_id"].strip()):
        raise ValueError("invalid execution lane/slot binding")
    return value


def _binding(value):
    value = json_copy(value, label="materializer binding")
    if type(value) is not dict or set(value) != {"schema_version", "kind", "recovery_model", "configuration"} \
            or type(value["schema_version"]) is not int or value["schema_version"] != 1 \
            or type(value["kind"]) is not str or not value["kind"].strip() \
            or value["recovery_model"] not in {"recorded_calls", "terminal_only"} \
            or type(value["configuration"]) is not dict:
        raise ValueError("materializer requires an explicit versioned recovery binding")
    return value


@dataclass(frozen=True)
class Materialization:
    _encoded: str

    @classmethod
    def from_dict(cls, payload):
        value = json_copy(payload, label="materialization")
        if type(value) is not dict or set(value) != {
                "schema_version", "identity", "construction_result", "outcome_ref", "artifact"} \
                or type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("unsupported materialization schema")
        identity = value["identity"]
        if type(identity) is not dict or set(identity) != {
                "schema_version", "operation", "plan_ref", "materializer", "artifact_backend"} \
                or type(identity["schema_version"]) is not int or identity["schema_version"] != 1:
            raise ValueError("invalid materialization identity")
        _operation(identity["operation"])
        if identity["operation"]["phase"] != "operator":
            raise ValueError("materialization must belong to candidate production")
        _binding(identity["materializer"])
        result = ConstructionResult.from_dict(value["construction_result"])
        outcome = {"identity": identity, "outcome": {"kind": "returned", "result": result.to_dict()}}
        if value["outcome_ref"] != _ref(outcome) or result.plan_ref != identity["plan_ref"]:
            raise ValueError("materialization does not match its construction outcome")
        backend = identity["artifact_backend"]
        if backend == {"schema_version": 1, "kind": "native_text_v1"}:
            artifact = NativeArtifactBackend._descriptor(value["artifact"])
        elif type(backend) is dict and set(backend) == {"schema_version", "kind", "base_repo", "base_commit",
                "artifact_path", "protected_paths", "protected"} and backend["schema_version"] == 1 \
                and backend["kind"] == "git_text_v1":
            artifact = GitArtifactBackend._descriptor(value["artifact"])
            if artifact["artifact_path"] != backend["artifact_path"]:
                raise ValueError("materialization Git artifact path differs")
        else:
            raise ValueError("unsupported materialization artifact backend")
        raw = result.artifact.encode("utf-8")
        if artifact["reference"] != "sha256:" + hashlib.sha256(raw).hexdigest() \
                or artifact["size_bytes"] != len(raw):
            raise ValueError("materialization descriptor differs from its constructed bytes")
        return cls(_json(value))

    def to_dict(self):
        return json.loads(self._encoded)

    @property
    def ref(self):
        return _ref(self.to_dict())

    @property
    def proposal(self):
        result = ConstructionResult.from_dict(self.to_dict()["construction_result"])
        return Proposal(result.candidate, result.artifact, result.cost, result.measured_cost_units)


class CandidateExecution:
    def __init__(self, materializer, artifact_backend, store, provider, evaluator, *, command_executor=None):
        if not isinstance(store, ContinuationStore):
            raise ValueError("candidate execution requires a continuation journal")
        if not callable(getattr(materializer, "construct", None)) or not callable(provider):
            raise ValueError("candidate execution requires a materializer and scoped provider")
        self.materializer, self.backend, self.store = materializer, artifact_backend, store
        self.provider, self.evaluator = provider, evaluator
        self.binding = _binding(materializer.manifest_binding)
        self.backend_binding = json_copy(artifact_backend.manifest_binding)
        self.command_executor = command_executor
        self.evaluation_binding = None
        if command_executor is not None:
            from core.composition.worktree import WorktreeCommandExecutor
            if not isinstance(command_executor, WorktreeCommandExecutor) or not isinstance(artifact_backend, GitArtifactBackend):
                raise ValueError("command evaluation requires original worktree protocol and Git artifacts")
            self.evaluation_binding = {"executor": json_copy(command_executor.manifest_binding),
                                       "domain": json_copy(evaluator.manifest_binding)}
        self._measurements = {}

    @contextmanager
    def _provider_scope(self, operation):
        provider = self.provider
        keys = ("invocation_binding", "invocation_ordinal", "_governed_store")
        previous = {key: provider.__dict__[key] for key in keys if key in provider.__dict__}
        existing = provider.__dict__.get("invocation_binding")
        if existing is not None:
            for key, op_key in (("run_id", "run_id"), ("intent_id", "intent_id"),
                                ("fingerprint", "fingerprint"), ("lane", "lane"), ("slot_id", "slot_id")):
                if existing.get(key) != operation[op_key]:
                    raise ValueError("provider scope differs from candidate operation")
        for key in ("durable_store", "_governed_store"):
            if key in provider.__dict__ and provider.__dict__[key] is not self.store:
                raise ValueError("provider is bound to another continuation journal")
        try:
            if existing is None:
                provider.invocation_binding = {"schema_version": 1,
                    **{key: operation[key] for key in ("run_id", "intent_id", "fingerprint", "lane", "slot_id")},
                    "adapter_binding_sha256": payload_digest({
                        "model": getattr(provider, "model", None), "supplier": getattr(provider, "supplier", None)})}
                provider.invocation_ordinal = 0
            provider._governed_store = self.store
            yield
        finally:
            # Preserve progress inside an enclosing governance meter.
            if existing is not None:
                previous["invocation_ordinal"] = provider.invocation_ordinal
            for key in keys:
                if key in previous:
                    provider.__dict__[key] = previous[key]
                else:
                    provider.__dict__.pop(key, None)

    def _identity(self, plan, operation):
        if _binding(self.materializer.manifest_binding) != self.binding \
                or json_copy(self.backend.manifest_binding) != self.backend_binding:
            raise ValueError("execution adapter binding changed")
        return {"schema_version": 1, "operation": operation, "plan_ref": plan.ref,
                "materializer": self.binding, "artifact_backend": self.backend_binding}

    def _check_materialization(self, payload, *, identity=None, plan=None):
        materialized = Materialization.from_dict(payload)
        value = materialized.to_dict()
        if identity is not None and value["identity"] != identity:
            raise ValueError("materialization differs from requested construction identity")
        if value["identity"]["artifact_backend"] != self.backend_binding:
            raise ValueError("materialization artifact backend changed")
        result = ConstructionResult.from_dict(value["construction_result"])
        terminal = self._recorded("construction_outcome", value["identity"]["operation"])
        expected_terminal = {"identity": value["identity"],
                             "outcome": {"kind": "returned", "result": result.to_dict()}}
        if terminal != expected_terminal:
            raise ValueError("materialization differs from its original construction terminal")
        if plan is not None:
            result.validate_for(plan)
        if self.backend.load(value["artifact"]) != result.artifact:
            raise ValueError("published artifact differs from measured construction")
        return materialized

    def _recorded(self, kind, operation):
        matches = [row["payload"] for row in self.store.read(kind)
                   if row["payload"]["identity"]["operation"]["intent_id"] == operation["intent_id"]]
        if len(matches) > 1:
            raise ValueError("duplicate construction terminal for operation")
        return matches[0] if matches else None

    @staticmethod
    def _publication_failure(value, identity, result):
        if type(value) is not dict or set(value) != {"identity", "reason", "integrity_failure"} \
                or value["identity"] != identity or type(value["reason"]) is not str \
                or type(value["integrity_failure"]) is not bool:
            raise ValueError("invalid materialization failure outcome")
        kind = ConstructionIntegrityError if value["integrity_failure"] else OperatorFailure
        return kind(result.cost, value["reason"], measured_cost_units=result.measured_cost_units)

    def _fail_publication(self, identity, result, reason, *, integrity=False):
        value = {"identity": identity, "reason": reason, "integrity_failure": integrity}
        self.store.append("materialization_failed", value)
        raise self._publication_failure(value, identity, result)

    async def materialize(self, plan, *, operation):
        operation = _operation(operation)
        if operation["phase"] != "operator" or not isinstance(plan, ConstructionPlan):
            raise ValueError("materialization requires a bound construction plan")
        identity = self._identity(plan, operation)
        completed = self._recorded("materialization_completed", operation)
        failed = self._recorded("materialization_failed", operation)
        if completed is not None:
            if failed is not None:
                raise ValueError("construction has conflicting materialization outcomes")
            return self._check_materialization(completed, identity=identity, plan=plan)
        terminal = self._recorded("construction_outcome", operation)
        if terminal is not None:
            result = decode_construction_outcome(terminal, identity)
            if isinstance(result, OperatorFailure):
                raise result
            if failed is not None:
                raise self._publication_failure(failed, identity, result)
        if any(row["payload"]["identity"]["operation"]["intent_id"] == operation["intent_id"]
               for row in self.store.read("construction_started")):
            raise UsageError("incomplete construction is outside the active continuation window")
        with self._provider_scope(operation):
            result = await self.store.construction_call(identity,
                lambda: self.materializer.construct(plan, self.provider), provider=self.provider,
                recoverable=self.binding["recovery_model"] == "recorded_calls")
        try:
            result.validate_for(plan)
        except ValueError:
            self._fail_publication(identity, result, "construction outcome differs from its frozen plan",
                                   integrity=True)
        row = self.store.peek()
        if row is not None:
            if row["kind"] == "materialization_completed":
                materialized = self._check_materialization(row["payload"], identity=identity, plan=plan)
                self.store.append(row["kind"], row["payload"])
                return materialized
            if row["kind"] == "materialization_failed" and row["payload"].get("identity") == identity:
                failure = self._publication_failure(row["payload"], identity, result)
                self.store.append(row["kind"], row["payload"])
                raise failure
            raise ValueError("unexpected materialization continuation")
        if not self.store.recover_external_outcomes:
            raise UsageError("recorded replay has no published materialization")
        try:
            artifact = self.backend.publish(result.artifact, operation=operation)
            if self.backend.load(artifact) != result.artifact:
                raise ValueError("artifact publication differs from construction")
            outcome = {"identity": identity, "outcome": {"kind": "returned", "result": result.to_dict()}}
            value = {"schema_version": 1, "identity": identity, "construction_result": result.to_dict(),
                     "outcome_ref": _ref(outcome), "artifact": artifact}
            materialized = Materialization.from_dict(value)
        except Exception as error:
            reason = f"artifact publication failed ({type(error).__name__})"
            self._fail_publication(identity, result, reason, integrity=isinstance(error, ValueError))
        self.store.append("materialization_completed", value)
        return materialized

    async def evaluate(self, materialization, request, *, operation):
        operation = _operation(operation)
        if operation["phase"] != request.split_id or operation["phase"] == "operator":
            raise ValueError("evaluation phase differs from the requested split")
        materialized = self._check_materialization(materialization.to_dict())
        source = materialized.to_dict()["identity"]["operation"]
        if self._recorded("materialization_completed", source) != materialized.to_dict():
            raise ValueError("evaluation requires a published materialization in its journal")
        if any(source[key] != operation[key] for key in ("run_id", "manifest_sha256", "lane", "slot_id")):
            raise ValueError("evaluation cannot cross materialization run or lane")
        domain = self.evaluator
        domain.validate_request(copy.deepcopy(request))
        context_for = getattr(domain, "evaluation_context_for", None)
        expected = binding_for(materialized.proposal, request, evaluator_version=domain.evaluator_version,
            evaluation_context=context_for(request) if callable(context_for) else domain.evaluation_context)
        identity = {"intent_id": operation["intent_id"], "fingerprint": operation["fingerprint"],
            "binding": asdict(expected), "lane": operation["lane"], "control_slot": operation["slot_id"],
            "materialization_ref": materialized.ref}
        completed = [row["payload"] for row in self.store.read("governed_evaluation_completed")
                     if row["payload"]["identity"].get("intent_id") == operation["intent_id"]]
        if len(completed) > 1:
            raise ValueError("duplicate evaluation terminal for operation")
        if completed:
            data = completed[0]
            if data["identity"] != identity:
                raise ValueError("evaluation operation identity changed")
            elapsed = data.get("elapsed")
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("invalid durable native evaluation measurement")
            self._measurements[operation["intent_id"]] = (operation, elapsed)
            return decode_evidence(data["evidence"])
        if any(row["payload"]["identity"].get("intent_id") == operation["intent_id"]
               for row in self.store.read("governed_evaluation_started")):
            raise UsageError("incomplete evaluation is outside the active continuation window")
        elapsed_reader = None
        if self.command_executor is not None:
            if self.evaluation_binding != {"executor": json_copy(self.command_executor.manifest_binding),
                                          "domain": json_copy(domain.manifest_binding)}:
                raise ValueError("command evaluation binding changed")
            # Bind the existing durable command protocol to the original artifact
            # commit. EvalRequest, including resume_from, remains unchanged.
            executor = copy.copy(self.command_executor)
            executor.base_commit = materialized.to_dict()["artifact"]["commit"]
            command_operation = {key: value for key, value in operation.items() if key not in {"lane", "slot_id"}}
            invoke = lambda: executor.execute_bound(materialized.proposal, copy.deepcopy(request), domain, command_operation)
            elapsed_reader = lambda: executor.operation_metadata(command_operation)["wall_seconds"]
        else:
            invoke = lambda: InProcessExecutor().execute(materialized.proposal, copy.deepcopy(request), domain)
        with self._provider_scope(operation):
            evidence, elapsed = await self.store.evaluation_call(identity, invoke,
                provider=self.provider, domain=domain, recoverable_command=self.command_executor is not None,
                elapsed_reader=elapsed_reader)
        self._measurements[operation["intent_id"]] = (operation, elapsed)
        # Driver validation follows physical settlement, preserving known usage.
        return evidence

    def operation_metadata(self, operation):
        operation = _operation(operation)
        recorded = self._measurements.get(operation["intent_id"])
        if recorded is None or recorded[0] != operation:
            raise ValueError("no original evaluation measurement for operation")
        return {"wall_seconds": recorded[1]}
