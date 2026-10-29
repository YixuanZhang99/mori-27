"""Validation and versioned transport for the single canonical evaluation result.

Producers return binding and measurement coverage inside EvalResult.contract.
The driver compares that returned declaration against independent expectations;
it must never fill missing producer declarations from its own request.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields, replace

from core.composition.contracts import json_copy
from core.executor.evaluation_contract import (EvaluationBinding, EvaluationContract, ItemOutcome,
    PrivateEvaluationData, PublicEvaluationData)
from core.executor.types import CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.llm import UsageError

COST_UNITS = frozenset({"token", "usd", "eval_count", "node", "wallclock", "gpu_hours"})


@dataclass(frozen=True)
class ComparisonResult:
    status: EvalStatus
    metrics: dict[str, float]
    fidelity: str
    uncertainty: float | None
    binding: EvaluationBinding


@dataclass(frozen=True)
class ComparisonEvidence:
    candidate_id: str
    eval_result: ComparisonResult
    attempt: int
    executor_status: str


def _text(value, label, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")


def _finite(value, label, *, minimum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or minimum is not None and value < minimum:
        raise ValueError(f"{label} must be finite" + (f" and >= {minimum}" if minimum is not None else ""))


def _metrics(values, label):
    if type(values) is not dict:
        raise ValueError(f"{label} must be an object")
    for key, value in values.items():
        _text(key, "metric name")
        _finite(value, f"{label}.{key}")


def validate_request(request):
    if not isinstance(request, EvalRequest):
        raise ValueError("evaluation request must be an EvalRequest")
    request.validate()
    return request


def request_digest(request):
    validate_request(request)
    raw = json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def binding_for(proposal, request, *, evaluator_version, evaluation_context):
    """Build a producer declaration or an independent consumer expectation.

    Consumers must compare the separately returned producer binding, never use
    this helper to repair a missing or mismatching declaration after execution.
    """
    validate_request(request)
    if type(proposal.artifact) is not str:
        raise ValueError("evaluated artifact must be text")
    binding = EvaluationBinding(proposal.candidate.id,
        hashlib.sha256(proposal.artifact.encode()).hexdigest(), request_digest(request),
        evaluator_version, evaluation_context, request.split_id, request.fidelity,
        tuple(request.seed_set) if request.seed_set is not None else None)
    _binding(binding)
    return binding


def _binding(binding):
    if not isinstance(binding, EvaluationBinding):
        raise ValueError("producer must return an EvaluationBinding")
    _text(binding.candidate_id, "candidate identity")
    _text(binding.evaluator_version, "evaluator version")
    _text(binding.split_id, "evaluation split")
    _text(binding.fidelity, "evaluation fidelity")
    if type(binding.artifact_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", binding.artifact_sha256):
        raise ValueError("artifact identity must be a canonical SHA-256 digest")
    if type(binding.request_sha256) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", binding.request_sha256):
        raise ValueError("request identity must be a canonical SHA-256 digest")
    if type(binding.evaluation_context) is not str or binding.evaluation_context \
            and not re.fullmatch(r"sha256:[0-9a-f]{64}", binding.evaluation_context):
        raise ValueError("evaluation context must be empty legacy context or a canonical SHA-256 digest")
    seeds = binding.seed_set
    if seeds is not None and (type(seeds) is not tuple
            or any(type(seed) is not int or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds)):
        raise ValueError("binding seeds must be distinct nonnegative integers")


def measured_costs(result, required_cost_units=("token", "eval_count")):
    """Check physical measurements independently of score/identity validity."""
    if not isinstance(result, EvalResult) or not isinstance(result.cost, CostVec):
        raise UsageError("evaluation must return an explicit CostVec")
    contract = result.contract
    if not isinstance(contract, EvaluationContract):
        raise UsageError("evaluation lacks measurement coverage")
    coverage = contract.measured_cost_units
    if type(coverage) is not tuple or any(type(unit) is not str or unit not in COST_UNITS for unit in coverage) \
            or len(set(coverage)) != len(coverage):
        raise UsageError("evaluation measurement coverage is invalid")
    if not set(required_cost_units) <= COST_UNITS or not set(required_cost_units) <= set(coverage):
        raise UsageError("evaluation does not measure every required cost unit")
    try:
        for name, value in asdict(result.cost).items():
            _finite(value, f"cost.{name}", minimum=0)
            if name in {"tokens_in", "tokens_out", "eval_count", "node_count"} and type(value) is not int:
                raise ValueError("token/count measurements must be integers")
    except ValueError as error:
        raise UsageError(str(error)) from error
    if type(contract.token_accounting) is not str or contract.token_accounting not in {"split", "total_only"} \
            or contract.token_accounting == "total_only" and result.cost.tokens_out != 0:
        raise UsageError("invalid total-only token storage convention")
    values = {"token": result.cost.tokens_in + result.cost.tokens_out, "usd": result.cost.usd,
              "eval_count": result.cost.eval_count, "node": result.cost.node_count,
              "wallclock": result.cost.wall_seconds, "gpu_hours": result.cost.gpu_hours}
    # A nonzero value cannot be passed off as an unmeasured default.
    if any(value != 0 and unit not in coverage for unit, value in values.items()):
        raise UsageError("nonzero cost lacks measurement coverage")
    return {unit: values[unit] for unit in required_cost_units}


def validate_result(result, *, expected_binding=None, required_cost_units=("token", "eval_count"),
                    require_full=True):
    measured_costs(result, required_cost_units)
    contract = result.contract
    _binding(contract.binding)
    if expected_binding is not None:
        _binding(expected_binding)
        if contract.binding != expected_binding:
            raise ValueError("evaluation producer binding mismatch")
    if not isinstance(result.status, EvalStatus):
        raise ValueError("evaluation status must be an EvalStatus")
    _text(result.fidelity, "evaluation fidelity")
    if result.fidelity != contract.binding.fidelity:
        raise ValueError("evaluation fidelity differs from producer binding")
    _metrics(result.metrics, "public metrics")
    if result.status is EvalStatus.OK and not result.metrics:
        raise ValueError("successful evaluation requires public metrics")
    if result.uncertainty is not None:
        _finite(result.uncertainty, "evaluation uncertainty", minimum=0)
    for name in ("text_feedback", "partial_curves_ref", "trajectory_ref", "artifacts_ref"):
        value = getattr(result, name)
        if name == "text_feedback" and value == "":
            continue
        _text(value, name, optional=True)
    if contract.binding_source not in {"producer", "invocation"} \
            or result.status is EvalStatus.OK and contract.binding_source != "producer":
        raise ValueError("successful evidence requires a producer binding")
    if contract.visibility not in {"full", "public"} or require_full and contract.visibility != "full":
        raise ValueError("evaluation requires full producer evidence")
    if not isinstance(contract.public, PublicEvaluationData) or not isinstance(contract.private, PrivateEvaluationData):
        raise ValueError("evaluation public/private payloads must be typed")
    if type(contract.public.data) is not dict or type(contract.public.metadata) is not dict \
            or type(contract.private.data) is not dict:
        raise ValueError("evaluation public/private data must be objects")
    json_copy(contract.public.data, label="public evaluation data")
    json_copy(contract.public.metadata, label="public evaluation metadata")
    json_copy(contract.private.data, label="private evaluation data")
    _metrics(contract.private.metrics, "private metrics")
    if set(result.metrics) & set(contract.private.metrics):
        raise ValueError("a metric cannot be both public and private")
    if contract.items is not None:
        if type(contract.items) is not tuple:
            raise ValueError("per-item outcomes must be a tuple")
        seen = set()
        for item in contract.items:
            if not isinstance(item, ItemOutcome):
                raise ValueError("per-item outcomes must be ItemOutcome records")
            _text(item.item_id, "item identity")
            if item.verdict is not None and (type(item.verdict) is not int or item.verdict not in (0, 1)):
                raise ValueError("item verdict must be a binary integer")
            _metrics(item.metrics, "item metrics")
            if item.verdict is None and not item.metrics:
                raise ValueError("item outcome requires a verdict or metrics")
            if item.seed is not None and (type(item.seed) is not int or item.seed < 0):
                raise ValueError("item seed must be a nonnegative integer")
            if item.seed is not None and contract.binding.seed_set is not None \
                    and item.seed not in contract.binding.seed_set:
                raise ValueError("item seed differs from evaluation seeds")
            if item.visibility not in {"public", "private"}:
                raise ValueError("item visibility must be public or private")
            key = (item.item_id, item.seed)
            if key in seen:
                raise ValueError("duplicate per-item outcome identity")
            seen.add(key)
    if contract.visibility == "public" and (contract.private != PrivateEvaluationData()
            or any(item.visibility != "public" for item in contract.items or ())):
        raise ValueError("public projection contains private evaluation data")
    return result


def validate_evidence(evidence, *, expected_binding=None, required_cost_units=("token", "eval_count"),
                      require_full=True):
    if not isinstance(evidence, EvidenceRecord):
        raise ValueError("executor must return canonical EvidenceRecord")
    validate_result(evidence.eval_result, expected_binding=expected_binding,
                    required_cost_units=required_cost_units, require_full=require_full)
    if evidence.candidate_id != evidence.eval_result.contract.binding.candidate_id:
        raise ValueError("executor and evaluator candidate binding mismatch")
    if type(evidence.attempt) is not int or evidence.attempt < 1:
        raise ValueError("evidence attempt must be a positive integer")
    statuses = {EvalStatus.OK: {"scored"}, EvalStatus.FAILED_TO_RUN: {"failed_to_run", "skipped"},
                EvalStatus.TIMEOUT: {"timeout"}, EvalStatus.INVALID: {"invalid"}}
    if type(evidence.executor_status) is not str or evidence.executor_status not in statuses[evidence.eval_result.status]:
        raise ValueError("executor status is inconsistent with evaluation status")
    for name in ("branch_ref", "insight", "result_text"):
        value = getattr(evidence, name)
        if value == "" and name != "branch_ref":
            continue
        _text(value, name, optional=True)
    return evidence


def public_projection(evidence):
    validate_evidence(evidence)
    result, contract = evidence.eval_result, evidence.eval_result.contract
    visible = replace(contract, public=PublicEvaluationData(json_copy(contract.public.data),
                                                           json_copy(contract.public.metadata)),
                      private=PrivateEvaluationData(), visibility="public",
                      items=tuple(replace(item, metrics=dict(item.metrics)) for item in contract.items
                                  if item.visibility == "public") if contract.items is not None else None)
    return replace(evidence, eval_result=replace(result, metrics=dict(result.metrics), contract=visible))


def comparison_projection(evidence):
    validate_evidence(evidence)
    result = evidence.eval_result
    return ComparisonEvidence(evidence.candidate_id, ComparisonResult(
        result.status, dict(result.metrics), result.fidelity, result.uncertainty, result.contract.binding),
        evidence.attempt, evidence.executor_status)


def _object(data, cls, *, optional=()):
    expected = {item.name for item in fields(cls)}
    if type(data) is not dict or set(data) - expected or expected - set(data) - set(optional):
        raise ValueError(f"invalid {cls.__name__} serialized fields")
    return dict(data)


def _contract_from_payload(data):
    values = _object(data, EvaluationContract)
    binding = _object(values["binding"], EvaluationBinding)
    seeds = binding["seed_set"]
    if seeds is not None:
        if type(seeds) is not list:
            raise ValueError("serialized binding seeds must be a list")
        binding["seed_set"] = tuple(seeds)
    values["binding"] = EvaluationBinding(**binding)
    coverage = values["measured_cost_units"]
    if type(coverage) is not list:
        raise UsageError("serialized measurement coverage must be a list")
    values["measured_cost_units"] = tuple(coverage)
    values["public"] = PublicEvaluationData(**_object(values["public"], PublicEvaluationData))
    values["private"] = PrivateEvaluationData(**_object(values["private"], PrivateEvaluationData))
    if values["items"] is not None:
        if type(values["items"]) is not list:
            raise ValueError("serialized item outcomes must be a list")
        values["items"] = tuple(ItemOutcome(**_object(item, ItemOutcome)) for item in values["items"])
    return EvaluationContract(**values)


def encode_evidence(evidence):
    validate_evidence(evidence)
    return json.loads(json.dumps({"schema_version": 1, "evidence": asdict(evidence)},
                                 ensure_ascii=False, allow_nan=False, sort_keys=True))


def decode_evidence(payload, *, expected_binding=None, required_cost_units=("token", "eval_count"),
                    allow_legacy=False):
    payload = json_copy(payload, label="evidence codec payload")
    if type(payload) is not dict or set(payload) != {"schema_version", "evidence"} \
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported evidence codec schema")
    values = _object(payload["evidence"], EvidenceRecord)
    result = _object(values["eval_result"], EvalResult, optional=("contract",) if allow_legacy else ())
    result["status"] = EvalStatus(result["status"])
    result["cost"] = CostVec(**_object(result["cost"], CostVec))
    if result.get("contract") is not None:
        result["contract"] = _contract_from_payload(result["contract"])
    values["eval_result"] = EvalResult(**result)
    evidence = EvidenceRecord(**values)
    if allow_legacy and evidence.eval_result.contract is None:
        if expected_binding is not None:
            raise ValueError("legacy evidence cannot certify an expected binding")
        return evidence
    return validate_evidence(evidence, expected_binding=expected_binding,
                             required_cost_units=required_cost_units)
