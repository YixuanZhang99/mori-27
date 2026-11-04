"""M7 construction from frozen intent and an existing M5 context projection.

This module never retrieves memory, allocates budget or evaluates a candidate.
Its caller owns the single candidate-production invocation and durable outcomes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from core.composition.context import ContextPack
from core.composition.contracts import OperatorBudgetExhausted, OperatorFailure, json_copy
from core.executor.types import Candidate, CostVec, ExecutorSpec
from core.llm import ProviderBudgetExhausted, UsageError, reset_usage, take_usage


def _json(value):
    return json.dumps(json_copy(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _ref(value):
    return "sha256:" + hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


@dataclass(frozen=True)
class RoleDefinition:
    name: str
    version: str
    instructions: str

    def __post_init__(self):
        for key in ("name", "version", "instructions"):
            _text(getattr(self, key), "role " + key)


def _roles(roles):
    if type(roles) is not dict or not roles or any(
            not isinstance(value, RoleDefinition) or key != value.name for key, value in roles.items()):
        raise ValueError("roles must map registered names to role definitions")
    return dict(roles)


def project_context(pack, fields, *, expected_ref):
    """Select actual v1 content fields, retaining each included source's evidence."""
    if not isinstance(pack, ContextPack) or pack.ref != expected_ref:
        raise ValueError("construction context differs from candidate context reference")
    if type(fields) is not list or any(type(key) is not str or key not in {
            "memory", "grounding", "query"} for key in fields) or len(set(fields)) != len(fields):
        raise ValueError("context projection requires distinct supported content fields")
    source = json_copy(pack.to_dict())
    if type(source) is not dict or type(source.get("schema_version")) is not int \
            or source["schema_version"] != 1 or set(source) != {
                "schema_version", "usage", "scope", "query", "budget", "memory", "grounding"}:
        raise ValueError("construction requires an explicit ContextPack v1")
    if type(source["scope"]) is not dict or type(source["memory"]) is not list \
            or type(source["grounding"]) is not list or type(source["query"]) is not str:
        raise ValueError("invalid context content shape")
    for entry in source["memory"]:
        if type(entry) is not dict or type(entry.get("provenance")) is not dict:
            raise ValueError("context memory must retain source provenance")
    for entry in source["grounding"]:
        if type(entry) is not dict or type(entry.get("digest_id")) is not str:
            raise ValueError("context grounding must retain source digest identity")
    return {"schema_version": 1, "source_ref": expected_ref,
            "scope": source["scope"], "fields": list(fields),
            "content": {key: source[key] for key in fields}}


@dataclass(frozen=True)
class ConstructionPlan:
    _encoded: str

    @classmethod
    def create(cls, candidate, recipe, spec, context_pack, *, roles):
        roles = _roles(roles)
        if not isinstance(candidate, Candidate) or not isinstance(spec, ExecutorSpec):
            raise ValueError("construction requires canonical candidate and executor spec")
        candidate.validate()
        _text(candidate.id, "candidate identity")
        _text(candidate.hypothesis, "initial hypothesis")
        if type(candidate.parents) is not list or any(type(x) is not str for x in candidate.parents):
            raise ValueError("candidate parents must be identities")
        if type(spec.role) is not str or spec.role not in roles or type(spec.hypothesis_frozen) is not bool:
            raise ValueError("construction requires a registered role and boolean hypothesis policy")
        if spec.hypothesis is not None:
            _text(spec.hypothesis, "spec hypothesis")
            if spec.hypothesis != candidate.hypothesis:
                raise ValueError("candidate and executor hypotheses conflict")
        if spec.execution_ref is not None:
            _text(spec.execution_ref, "execution correlation")
        projection = project_context(context_pack, spec.context_projection,
                                     expected_ref=candidate.context_pack_ref)
        recipe = json_copy(recipe, label="construction recipe")
        if type(recipe) is not dict or set(recipe) != {
                "kind", "task_desc", "parent_artifacts", "instructions", "comparison"}:
            raise ValueError("construction recipe requires explicit permitted inputs")
        if recipe["kind"] not in {"draft", "reflective", "crossover"}:
            raise ValueError("unsupported construction recipe")
        _text(recipe["task_desc"], "construction task")
        if type(recipe["instructions"]) is not list or any(type(x) is not str or not x.strip()
                for x in recipe["instructions"]):
            raise ValueError("construction instructions must be explicit text")
        parents = recipe["parent_artifacts"]
        if type(parents) is not list or any(type(p) is not dict or set(p) != {"candidate_id", "artifact"}
                or type(p["artifact"]) is not str for p in parents) \
                or [p["candidate_id"] for p in parents] != candidate.parents:
            raise ValueError("recipe artifacts must match candidate parent identities in order")
        expected = {"draft": 0, "reflective": 1, "crossover": 2}[recipe["kind"]]
        if len(parents) != expected:
            raise ValueError("recipe parent count differs from its construction kind")
        comparison = recipe["comparison"]
        if type(comparison) is not dict or set(comparison) - set(candidate.parents) \
                or any(type(value) not in (int, float) for value in comparison.values()):
            raise ValueError("comparison may contain only selected parent numeric values")
        return cls(_json({"schema_version": 1, "candidate": asdict(candidate), "recipe": recipe,
            "spec": asdict(spec), "role": asdict(roles[spec.role]), "projection": projection,
            "projection_ref": _ref(projection)}))

    @property
    def ref(self):
        return "sha256:" + hashlib.sha256(self._encoded.encode()).hexdigest()

    def to_dict(self):
        return json.loads(self._encoded)


@dataclass(frozen=True)
class ConstructionResult:
    _encoded: str

    def to_dict(self):
        return json.loads(self._encoded)

    @property
    def artifact(self):
        return self.to_dict()["artifact"]

    @property
    def candidate(self):
        return Candidate(**self.to_dict()["candidate"])

    @property
    def cost(self):
        return CostVec(**self.to_dict()["cost"])

    @property
    def measured_cost_units(self):
        return ("token", "node", "eval_count")

    @property
    def plan_ref(self):
        return self.to_dict()["plan_ref"]


def _output(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate construction output field")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if type(value) is not dict or set(value) - {"artifact", "hypothesis", "feedback"} \
            or not {"artifact", "hypothesis"} <= set(value):
        raise ValueError("construction output requires artifact and hypothesis only, with optional feedback")
    _text(value["artifact"], "constructed artifact")
    _text(value["hypothesis"], "executed hypothesis")
    if "feedback" in value and type(value["feedback"]) is not str:
        raise ValueError("construction feedback must be text")
    return value


class PromptMaterializer:
    """Generate a measured artifact; caller supplies its scoped metered provider."""
    def __init__(self, roles, *, max_attempts=1, validator=None):
        self.roles = _roles(roles)
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("construction max_attempts must be a positive integer")
        if validator is not None and not callable(validator):
            raise ValueError("local construction validator must be callable")
        self.max_attempts, self.validator = max_attempts, validator

    async def construct(self, plan, provider):
        if not isinstance(plan, ConstructionPlan) or not callable(provider):
            raise ValueError("materializer requires a construction plan and provider")
        value = plan.to_dict()
        role = self.roles.get(value["spec"]["role"])
        if role is None or asdict(role) != value["role"]:
            raise ValueError("construction role definition changed after plan binding")
        used, attempts, feedback = 0, [], []
        initial = hypothesis = value["candidate"]["hypothesis"]
        coverage = ("token", "node", "eval_count")

        def failed(detail, failure_type=OperatorFailure):
            return failure_type(CostVec(tokens_in=used, node_count=1), detail,
                                measured_cost_units=coverage)

        for index in range(self.max_attempts):
            request = {"schema_version": 1, "plan_ref": plan.ref, "role": value["role"],
                "recipe": value["recipe"], "context": value["projection"], "hypothesis": hypothesis,
                "hypothesis_frozen": value["spec"]["hypothesis_frozen"], "attempt": index + 1,
                "repair_feedback": feedback,
                "output_contract": {"artifact": "nonempty text", "hypothesis": "nonempty text"}}
            reset_usage(provider)
            try:
                raw = provider(_json(request))
            except UsageError:
                raise
            except Exception as error:
                used += take_usage(provider)  # Unknown is not a bill for the known prefix.
                kind = OperatorBudgetExhausted if isinstance(error, ProviderBudgetExhausted) else OperatorFailure
                raise failed(f"{type(error).__name__}: {error}", kind) from error
            used += take_usage(provider)
            try:
                output = _output(raw)
            except (TypeError, ValueError) as error:
                feedback = [str(error)]
                attempts.append({"attempt": index + 1, "status": "invalid_output",
                                 "known_tokens": used, "feedback": feedback})
                continue
            if value["spec"]["hypothesis_frozen"] and output["hypothesis"] != initial:
                raise failed("materializer changed the frozen hypothesis")
            hypothesis = output["hypothesis"]
            try:
                feedback = self.validator(output["artifact"]) if self.validator is not None else ()
                if type(feedback) not in (list, tuple) or any(type(x) is not str or not x.strip() for x in feedback):
                    raise ValueError("local validator must return text issues")
                feedback = list(feedback)
            except Exception as error:
                raise failed(f"local construction validation failed: {type(error).__name__}: {error}") from error
            attempts.append({"attempt": index + 1, "status": "invalid_artifact" if feedback else "complete",
                             "hypothesis": hypothesis, "known_tokens": used, "feedback": feedback})
            if not feedback:
                candidate = {**value["candidate"], "hypothesis": hypothesis}
                return ConstructionResult(_json({"schema_version": 1, "plan_ref": plan.ref,
                    "candidate": candidate, "artifact": output["artifact"], "role": value["role"],
                    "spec_ref": _ref(value["spec"]), "projection_ref": value["projection_ref"],
                    "initial_hypothesis": initial, "effective_hypothesis": hypothesis,
                    "cost": asdict(CostVec(tokens_in=used, node_count=1)),
                    "measured_cost_units": list(coverage), "attempts": attempts}))
        raise failed("construction attempts exhausted: " + "; ".join(feedback))
