"""M7 construction from frozen intent and an existing M5 context projection.

This module never retrieves memory, allocates budget or evaluates a candidate.
Its caller owns the single candidate-production invocation and durable outcomes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields

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
    # JSON permits escaped lone surrogates; durable artifacts require UTF-8.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} must be valid UTF-8 text") from error


def _funsearch_binding(binding, prompt, parents):
    """Validate a local binding; the owning runtime must audit its journal."""
    fields = {'selection', 'selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs', 'binding_ref'}
    if type(binding) is not dict or set(binding) != fields:
        raise ValueError('FunSearch construction requires a complete selection binding')
    refs = ('selection_ref', 'input_ref', 'prompt_ref', 'binding_ref')
    if any(type(binding[key]) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', binding[key]) for key in refs):
        raise ValueError('FunSearch construction references must be canonical digests')
    selection = binding['selection']
    keys = {'schema_version', 'requested_island', 'island', 'epoch', 'samples', 'ancestry',
            'eligible', 'state_before_ref', 'state_after_ref'}
    if type(selection) is not dict or set(selection) != keys or type(selection['schema_version']) is not int \
            or selection['schema_version'] != 2 or type(selection['island']) is not int \
            or selection['island'] < 0 or type(selection['epoch']) is not int or selection['epoch'] < 0 \
            or (selection['requested_island'] is not None and
                (type(selection['requested_island']) is not int or selection['requested_island'] != selection['island'])):
        raise ValueError('invalid FunSearch selection record')
    samples, ancestry, eligible = selection['samples'], selection['ancestry'], selection['eligible']
    if type(samples) is not list or not samples or any(type(x) is not str or not x for x in samples) \
            or type(ancestry) is not list or ancestry != list(dict.fromkeys(samples)) or ancestry != parents \
            or type(eligible) is not list or any(type(x) is not str or not x for x in eligible) \
            or eligible != sorted(set(eligible)) or not set(samples) <= set(eligible):
        raise ValueError('FunSearch samples differ from selected ancestry or eligibility')
    if any(type(selection[key]) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', selection[key])
           for key in ('state_before_ref', 'state_after_ref')):
        raise ValueError('invalid FunSearch population state reference')
    evidence = binding['evidence_refs']
    if type(evidence) is not dict or set(evidence) != set(parents) or any(
            type(value) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', value)
            for value in evidence.values()):
        raise ValueError('FunSearch evidence references differ from ancestry')
    if binding['selection_ref'] != _ref(selection) or binding['prompt_ref'] != _ref(prompt):
        raise ValueError('FunSearch selection or prompt differs from its digest')
    core = {key: binding[key] for key in ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs')}
    if binding['binding_ref'] != _ref(core):
        raise ValueError('FunSearch prompt binding differs')


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


def validate_hypothesis_binding(binding, parents, candidate):
    """Check an explicit execution base without confusing it with idea ancestry.

    The driver separately binds these values to its original selection and trunk;
    this pure check keeps the materializer's serialized contract self-consistent.
    """
    required = {'schema_version', 'candidate_id', 'cycle', 'hypothesis_id', 'hypothesis',
                'skeleton_parents', 'source_refs', 'execution_base', 'context_ref'}
    if type(binding) is not dict or set(binding) != required or type(binding['schema_version']) is not int \
            or binding['schema_version'] != 1 or binding['candidate_id'] != candidate['id'] \
            or binding['cycle'] != candidate['created_cycle'] or binding['hypothesis'] != candidate['hypothesis'] \
            or binding['skeleton_parents'] != candidate['parents'] or binding['context_ref'] != candidate['context_pack_ref']:
        raise ValueError('hypothesis construction binding differs from selected candidate')
    _text(binding['hypothesis_id'], 'hypothesis identity')
    refs = binding['source_refs']
    if type(refs) is not list or any(type(ref) is not str or not ref for ref in refs) or len(set(refs)) != len(refs):
        raise ValueError('hypothesis source references are invalid')
    base = binding['execution_base']
    if base is None:
        if parents:
            raise ValueError('hypothesis with no trunk cannot receive base artifacts')
    else:
        if type(base) is not dict or set(base) != {'candidate_id', 'artifact_sha256', 'materialization_ref'} \
                or len(parents) != 1 or parents[0]['candidate_id'] != base['candidate_id'] \
                or hashlib.sha256(parents[0]['artifact'].encode()).hexdigest() != base['artifact_sha256'] \
                or type(base['materialization_ref']) is not str \
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', base['materialization_ref']):
            raise ValueError('hypothesis trunk artifact differs from its bound materialization')


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
        base = {"kind", "task_desc", "parent_artifacts", "instructions", "comparison"}
        extra = {'funsearch': {'funsearch_binding'}, 'hypothesis_refine': {'hypothesis_binding'}}
        if type(recipe) is not dict or set(recipe) != base | extra.get(recipe.get('kind'), set()):
            raise ValueError("construction recipe requires explicit permitted inputs")
        if recipe["kind"] not in {"draft", "reflective", "crossover", "funsearch", 'debug', 'improve', 'hypothesis_refine'}:
            raise ValueError("unsupported construction recipe")
        _text(recipe["task_desc"], "construction task")
        if type(recipe["instructions"]) is not list or any(type(x) is not str or not x.strip()
                for x in recipe["instructions"]):
            raise ValueError("construction instructions must be explicit text")
        parents = recipe["parent_artifacts"]
        if type(parents) is not list or any(type(p) is not dict or set(p) != {"candidate_id", "artifact"}
                or type(p["artifact"]) is not str for p in parents) \
                or recipe['kind'] != 'hypothesis_refine' and [p["candidate_id"] for p in parents] != candidate.parents:
            raise ValueError("recipe artifacts must match candidate parent identities in order")
        if recipe['kind'] == 'hypothesis_refine':
            validate_hypothesis_binding(recipe['hypothesis_binding'], parents, asdict(candidate))
            if recipe['comparison']:
                raise ValueError('hypothesis construction cannot substitute base scores for skeleton scores')
        expected = {"draft": 0, "reflective": 1, "crossover": 2, 'debug': 1, 'improve': 1}.get(recipe["kind"])
        if expected is not None and len(parents) != expected or recipe['kind'] == 'funsearch' and len(parents) not in (1, 2):
            raise ValueError("recipe parent count differs from its construction kind")
        if recipe['kind'] == 'funsearch':
            if len(recipe['instructions']) != 1:
                raise ValueError('FunSearch construction requires one bound program prompt')
            _funsearch_binding(recipe['funsearch_binding'], recipe['instructions'][0], candidate.parents)
        comparison = recipe["comparison"]
        if recipe['kind'] == 'debug' and comparison:
            raise ValueError('debug construction cannot invent a numeric comparison')
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

    @classmethod
    def from_dict(cls, payload):
        value = json_copy(payload, label="construction result")
        required = {"schema_version", "plan_ref", "candidate", "artifact", "role", "spec_ref",
                    "projection_ref", "initial_hypothesis", "effective_hypothesis", "cost",
                    "measured_cost_units", "attempts"}
        if type(value) is not dict or set(value) != required or type(value["schema_version"]) is not int \
                or value["schema_version"] != 1:
            raise ValueError("unsupported construction result schema")
        for key in ("plan_ref", "spec_ref", "projection_ref"):
            if type(value[key]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", value[key]):
                raise ValueError("invalid construction result reference")
        for key in ("artifact", "initial_hypothesis", "effective_hypothesis"):
            _text(value[key], key)
        candidate = value["candidate"]
        if type(candidate) is not dict or set(candidate) != {f.name for f in fields(Candidate)} \
                or type(candidate["created_cycle"]) is not int or candidate["created_cycle"] < 0 \
                or type(candidate["parents"]) is not list or any(type(p) is not str or not p for p in candidate["parents"]):
            raise ValueError("invalid construction candidate")
        for key in ("id", "operator", "context_pack_ref", "hypothesis"):
            _text(candidate[key], "candidate " + key)
        Candidate(**candidate).validate()
        if candidate["hypothesis"] != value["effective_hypothesis"]:
            raise ValueError("constructed candidate lost its effective hypothesis")
        if type(value["role"]) is not dict or set(value["role"]) != {"name", "version", "instructions"}:
            raise ValueError("invalid construction role binding")
        RoleDefinition(**value["role"])
        cost = construction_cost(value["cost"], value["measured_cost_units"])
        attempts = value["attempts"]
        if type(attempts) is not list or not attempts:
            raise ValueError("construction result requires its actual attempts")
        previous = 0
        for index, attempt in enumerate(attempts, 1):
            if type(attempt) is not dict or set(attempt) - {"attempt", "status", "known_tokens", "feedback", "hypothesis"} \
                    or not {"attempt", "status", "known_tokens", "feedback"} <= set(attempt) \
                    or type(attempt["attempt"]) is not int or attempt["attempt"] != index \
                    or attempt["status"] not in {"invalid_output", "invalid_artifact", "complete"} \
                    or type(attempt["known_tokens"]) is not int or not previous <= attempt["known_tokens"] <= cost.tokens_in \
                    or type(attempt["feedback"]) is not list or any(type(x) is not str for x in attempt["feedback"]):
                raise ValueError("invalid construction attempt sequence")
            if attempt["status"] == "complete" and (index != len(attempts) or attempt["feedback"]):
                raise ValueError("construction completion cannot precede more attempts")
            if attempt["status"] != "invalid_output":
                _text(attempt.get("hypothesis"), "attempt hypothesis")
            previous = attempt["known_tokens"]
        if attempts[-1]["status"] != "complete" or previous != cost.tokens_in \
                or attempts[-1]["hypothesis"] != value["effective_hypothesis"]:
            raise ValueError("construction result differs from its final attempt")
        return cls(_json(value))

    def validate_for(self, plan):
        value, expected = self.to_dict(), plan.to_dict()
        expected_candidate = {**expected["candidate"], "hypothesis": value["effective_hypothesis"]}
        if value["plan_ref"] != plan.ref or value["candidate"] != expected_candidate \
                or value["role"] != expected["role"] or value["spec_ref"] != _ref(expected["spec"]) \
                or value["projection_ref"] != expected["projection_ref"] \
                or value["initial_hypothesis"] != expected["candidate"]["hypothesis"] \
                or expected["spec"]["hypothesis_frozen"] and any(
                    attempt.get("hypothesis", value["initial_hypothesis"]) != value["initial_hypothesis"]
                    for attempt in value["attempts"]):
            raise ValueError("construction outcome differs from its frozen plan")
        return self

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
    if "feedback" in value:
        value["feedback"].encode("utf-8")
    return value


def construction_cost(payload, coverage):
    """Decode measured candidate-production cost without inferring unknown units."""
    payload = json_copy(payload, label="construction cost")
    if type(payload) is not dict or set(payload) != {f.name for f in fields(CostVec)} \
            or list(coverage) != ["token", "node", "eval_count"]:
        raise ValueError("invalid construction cost or measurement coverage")
    for key, value in payload.items():
        if type(value) not in (int, float) or value < 0 or key in {
                "tokens_in", "tokens_out", "node_count", "eval_count"} and type(value) is not int:
            raise ValueError("invalid construction physical measurement")
    if payload["node_count"] != 1 or payload["eval_count"] != 0 or any(
            payload[key] != 0 for key in ("tokens_out", "wall_seconds", "gpu_hours", "usd")):
        raise ValueError("construction cost must measure one attempt and no evaluations")
    return CostVec(**payload)


class ConstructionIntegrityError(OperatorFailure):
    """Known physical bill whose construction must not enter evaluation."""

    integrity_failure = True


def decode_construction_outcome(data, identity):
    """Decode a terminal result without changing provider state or accounting."""
    if type(data) is not dict or set(data) != {"identity", "outcome"} or data["identity"] != identity:
        raise ValueError("construction terminal identity changed")
    outcome = data["outcome"]
    if type(outcome) is not dict:
        raise ValueError("invalid construction terminal")
    if set(outcome) == {"kind", "result"} and outcome["kind"] == "returned":
        return ConstructionResult.from_dict(outcome["result"])
    failures = {kind.__name__: kind for kind in (OperatorFailure, OperatorBudgetExhausted,
                                                ConstructionIntegrityError)}
    if set(outcome) != {"kind", "failure_type", "detail", "cost", "measured_cost_units"} \
            or outcome["kind"] != "failed" or outcome["failure_type"] not in failures \
            or type(outcome["detail"]) is not str:
        raise ValueError("unsupported construction outcome")
    cost = construction_cost(outcome["cost"], outcome["measured_cost_units"])
    return failures[outcome["failure_type"]](cost, outcome["detail"],
        measured_cost_units=tuple(outcome["measured_cost_units"]))


class PromptMaterializer:
    """Generate a measured artifact; caller supplies its scoped metered provider."""
    def __init__(self, roles, *, max_attempts=1, validator=None,
                 validator_version=None, validator_deterministic=False):
        self.roles = _roles(roles)
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("construction max_attempts must be a positive integer")
        if validator is not None and not callable(validator):
            raise ValueError("local construction validator must be callable")
        self.max_attempts, self.validator = max_attempts, validator
        if validator_version is not None:
            _text(validator_version, "validator version")
        if type(validator_deterministic) is not bool:
            raise ValueError("validator recovery declaration must be boolean")
        self.validator_version, self.validator_deterministic = validator_version, validator_deterministic

    @property
    def manifest_binding(self):
        if self.validator is not None and self.validator_version is None:
            raise ValueError("durable construction requires an explicit validator version")
        deterministic = self.validator is None or self.validator_deterministic
        return {"schema_version": 1, "kind": "prompt_materializer_v1",
                "recovery_model": "recorded_calls" if deterministic else "terminal_only",
                "configuration": {"max_attempts": self.max_attempts,
                    "roles": {key: asdict(role) for key, role in self.roles.items()},
                    "validator": {"kind": "nonempty" if self.validator is None else "custom",
                        "version": "1" if self.validator is None else self.validator_version,
                        "deterministic": deterministic}}}

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
            detail = detail.encode("utf-8", errors="backslashreplace").decode("utf-8")
            return failure_type(CostVec(tokens_in=used, node_count=1), detail,
                                measured_cost_units=coverage)

        for index in range(self.max_attempts):
            request = {"schema_version": 1, "plan_ref": plan.ref, "role": value["role"],
                "recipe": value["recipe"], "context": value["projection"], "hypothesis": hypothesis,
                "hypothesis_frozen": value["spec"]["hypothesis_frozen"], "attempt": index + 1,
                "repair_feedback": feedback,
                "output_contract": {"artifact": "nonempty text", "hypothesis":
                    "Copy the input hypothesis exactly, without any changes."
                    if value["spec"]["hypothesis_frozen"] else "nonempty text"}}
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
            except (TypeError, ValueError, RecursionError) as error:
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
                for issue in feedback:
                    _text(issue, "local validation issue")
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
