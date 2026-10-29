"""Registered baseline components for the composed Framework execution path.

The legacy prompt domain is an explicit compatibility boundary. New domains
return the canonical executor EvalResult directly; the runtime never consumes
M0's small display result alongside canonical evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, replace

from core.budget.ledger import BudgetLedger
from core.budget.types import AccountingStamp
from core.composition.contracts import Decision, OperatorRequest, Proposal
from core.composition.admission import LayeredAdmissionController, layered_options
from core.composition.budget import HierarchicalBudget, hierarchical_options
from core.composition.evaluation import (EvaluationContract, ItemOutcome, PrivateEvaluationData,
                                        PublicEvaluationData, binding_for, validate_request)
from core.composition.registry import Registry
from core.composition.context import ContextMemory, context_options
from core.composition.knowledge import LocalKnowledge, knowledge_options
from core.composition.strategies import GreedyPolicy, LLMCyclesPolicy, policy_options
from core.eval.types import validate_eval_result as validate_legacy_result
from core.executor.types import Candidate, CostVec, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.llm import UsageError, reset_usage, take_usage
from core.memory import ScopedMemory
from core.operator.ops import draft, reflective_improve
from core.operator.types import OperatorSpec


def _options(options, allowed=()):
    if not isinstance(options, dict):
        raise ValueError("component options must be an object")
    if set(options) - set(allowed):
        raise ValueError(f"unsupported component options: {sorted(set(options) - set(allowed))}")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _number(value, name, *, minimum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or minimum is not None and value < minimum:
        raise ValueError(f"{name} must be a finite number" +
                         (f" >= {minimum}" if minimum is not None else ""))


def _objective_options(options, *, margin=False):
    _options(options, {"metric", "direction", *({"margin"} if margin else set())})
    _text(options.get("metric", "dev/score"), "metric")
    if options.get("direction", "maximize") not in {"maximize", "minimize"}:
        raise ValueError("direction must be maximize or minimize")
    if margin:
        _number(options.get("margin", 0.0), "margin", minimum=0)


def _operator_options(options):
    _options(options, {"prompt_version", "metric"})
    _text(options.get("prompt_version", "1"), "prompt_version")
    _text(options.get("metric", "dev/score"), "metric")


def _domain_options(options):
    _options(options, {"metric"})
    _text(options.get("metric", "dev/score"), "metric")


def _skill_options(options):
    _options(options, {"text"})
    _text(options.get("text"), "instruction text")


def _budget_options(options):
    _options(options, {"total_budget", "control_share", "reeval_floor"})
    for key, minimum in (("total_budget", 1), ("reeval_floor", 0)):
        if key in options and (type(options[key]) is not int or options[key] < minimum):
            raise ValueError(f"{key} must be an integer >= {minimum}")
    if "control_share" in options:
        _number(options["control_share"], "control_share")
        if not 0 < options["control_share"] < 1:
            raise ValueError("control_share must be in (0,1)")
    if "total_budget" in options and "reeval_floor" in options \
            and options["reeval_floor"] > options["total_budget"]:
        raise ValueError("reeval_floor cannot exceed total_budget")


class OperatorFailure(RuntimeError):
    """A failed proposal with known provider cost, suitable for settlement."""
    def __init__(self, cost: CostVec, detail: str, *, measured_cost_units=None):
        super().__init__(detail)
        self.cost = cost
        self.detail = detail
        self.measured_cost_units = measured_cost_units


class InstructionSkill:
    def __init__(self, text):
        _text(text, "instruction text")
        self.text = text

    def apply(self, request: OperatorRequest) -> OperatorRequest:
        context = dict(request.context)
        previous = context.get("instruction", "")
        if not isinstance(previous, str):
            raise ValueError("existing instruction must be a string")
        context["instruction"] = "\n".join(part for part in (previous, self.text) if part)
        return replace(request, context=context)


class PromptOperator:
    measured_cost_units = ("token", "node", "eval_count")

    def __init__(self, llm, kind, *, prompt_version="1", metric="dev/score"):
        if not callable(llm):
            raise ValueError("provided LLM must be callable")
        if kind not in {"draft", "reflective"}:
            raise ValueError("unsupported prompt operator")
        self.llm, self.kind = llm, kind
        self.prompt_version, self.metric = prompt_version, metric

    async def propose(self, request: OperatorRequest) -> Proposal:
        _text(request.candidate_id, "candidate id")
        if self.kind == "draft" and request.parents:
            raise ValueError("draft requires no parents")
        if self.kind == "reflective" and (len(request.parents) != 1 or len(request.evidence) != 1):
            raise ValueError("reflective requires one parent and its evidence")
        # Render context at the only prompt boundary. Typed retrieval packs can
        # later populate this mapping without changing the operator signature.
        context = {key: value for key, value in request.context.items() if value}
        extra = "\nCONTEXT:\n" + json.dumps(context, sort_keys=True, ensure_ascii=False) if context else ""
        strategy = "\nSTRATEGY:\n" + json.dumps(request.strategy, sort_keys=True, ensure_ascii=False) \
            if request.strategy else ""
        if self.kind == "reflective":
            parent, evidence = request.parents[0], request.evidence[0]
            if evidence.candidate_id != parent.candidate.id:
                raise ValueError("parent evidence identity mismatch")
            score = evidence.eval_result.metrics[self.metric]
            _number(score, "parent objective")
            feedback = evidence.eval_result.text_feedback or "No textual feedback supplied."
        reset_usage(self.llm)
        try:
            if self.kind == "draft":
                variation = draft(self.llm, OperatorSpec("composed-draft", "draft", self.prompt_version),
                                  request.task_desc + extra + strategy, request.candidate_id)
            else:
                variation = reflective_improve(
                    self.llm, OperatorSpec("composed-reflective", "improve", self.prompt_version),
                    parent.candidate.id, parent.artifact, feedback + extra + strategy,
                    score, request.candidate_id)
        except UsageError:
            raise
        except Exception as error:
            used = take_usage(self.llm)
            raise OperatorFailure(CostVec(tokens_in=used, node_count=1),
                                  f"{type(error).__name__}: {error}",
                                  measured_cost_units=("token", "node", "eval_count")) from error
        used = take_usage(self.llm)
        if not isinstance(variation.patch_text, str) or not variation.patch_text.strip():
            raise OperatorFailure(CostVec(tokens_in=used, node_count=1), "operator returned an empty artifact",
                                  measured_cost_units=("token", "node", "eval_count"))
        candidate = Candidate(request.candidate_id, list(variation.parent_ids),
                              operator=self.kind, created_cycle=request.cycle,
                              context_pack_ref=request.context.get("context_pack_ref"))
        return Proposal(candidate, variation.patch_text, CostVec(tokens_in=used, node_count=1),
                        measured_cost_units=("token", "node", "eval_count"))

    async def __call__(self, request):
        return await self.propose(request)


class LegacyPromptDomain:
    """Adapt the legacy evaluator once, including its explicitly metered usage.

    Legacy evaluators own their usage contract. GSM8K consumes solver usage into
    its own meter; residual usage on a shared proposing LLM is added only once.
    """
    # Candidate creation belongs to the operator. This adapter creates zero
    # framework nodes and performs exactly one evaluation invocation.
    measured_cost_units = ("token", "node", "eval_count")

    def __init__(self, evaluator, llm, *, metric="dev/score"):
        if not callable(evaluator):
            raise ValueError("legacy prompt evaluator must be callable")
        self.evaluator, self.llm, self.metric = evaluator, llm, metric

    @property
    def evaluator_version(self):
        # M0's legacy EvalResult defaults to det-v1. An absent content context
        # stays explicitly opaque; no dataset digest is invented by the adapter.
        return getattr(self.evaluator, "evaluator_version", "det-v1")

    @property
    def evaluation_context(self):
        return getattr(self.evaluator, "evaluation_context", "")

    def validate_context(self):
        check = getattr(self.evaluator, "validate_context", None)
        if callable(check):
            check()

    def validate_request(self, request):
        validate_request(request)
        if request.fidelity != "dev" or request.split_id != "dev" \
                or any(getattr(request, field) is not None for field in
                       ("time_limit", "budget_token", "seed_set", "resume_from")):
            raise ValueError("legacy prompt domain only supports an unconstrained dev request")

    async def evaluate(self, proposal: Proposal, request) -> EvalResult:
        self.validate_request(request)
        head = hashlib.sha256(proposal.artifact.encode("utf-8")).hexdigest()
        version = self.evaluator_version
        context = self.evaluation_context
        invocation = binding_for(proposal, request, evaluator_version=version, evaluation_context=context)
        check = getattr(self.evaluator, "validate_context", None)
        if callable(check):
            check()
        # The proposal's charge has already been captured in Proposal.cost.
        # The explicit zero denotes no further shared-provider work so far.
        if self.llm is not self.evaluator:
            self.llm.last_usage = {"total_tokens": 0}
        reset_usage(self.evaluator)
        error = None
        try:
            legacy = validate_legacy_result(
                self.evaluator(proposal.candidate.id, head, proposal.artifact),
                candidate_id=proposal.candidate.id, head_sha=head,
                evaluator_version=version, evaluation_context=context)
            _number(legacy.combined_score, "evaluation objective")
            metadata = {"adapter": "legacy_prompt", "reliability": json.loads(json.dumps(
                asdict(legacy.reliability), allow_nan=False))}
        except UsageError:
            raise
        except Exception as caught:
            error = caught
        used = take_usage(self.evaluator)
        if self.llm is not self.evaluator:
            used += take_usage(self.llm)
        if error is not None:
            detail = f"{type(error).__name__}: {error}"
            return EvalResult(EvalStatus.FAILED_TO_RUN, cost=CostVec(tokens_in=used, eval_count=1),
                              fidelity=request.fidelity, text_feedback=detail,
                              contract=EvaluationContract(invocation, self.measured_cost_units,
                                  token_accounting="total_only", binding_source="invocation"))
        returned_binding = replace(invocation, candidate_id=legacy.candidate_id,
                                   artifact_sha256=legacy.head_sha,
                                   evaluator_version=legacy.evaluator_version,
                                   evaluation_context=legacy.evaluation_context)
        return EvalResult(EvalStatus.OK, {self.metric: float(legacy.combined_score)},
                          cost=CostVec(tokens_in=used, eval_count=1),
                          fidelity=request.fidelity, text_feedback=legacy.text_feedback,
                          contract=EvaluationContract(returned_binding, self.measured_cost_units,
                              token_accounting="total_only",
                              public=PublicEvaluationData(dict(legacy.public), metadata),
                              private=PrivateEvaluationData(data=dict(legacy.private)),
                              items=tuple(ItemOutcome(item.item_id, item.verdict) for item in legacy.items)))


class InProcessExecutor:
    async def execute(self, proposal, request, domain):
        result = await domain.evaluate(proposal, request)
        if not isinstance(result, EvalResult):
            raise ValueError("domain must return canonical EvalResult")
        # The driver must settle known usage even if identity/status validation
        # fails. Keep the raw producer result intact until that ordered boundary.
        status = {EvalStatus.OK: "scored", EvalStatus.FAILED_TO_RUN: "failed_to_run",
                  EvalStatus.TIMEOUT: "timeout", EvalStatus.INVALID: "invalid"}.get(result.status, "invalid") \
            if isinstance(result.status, EvalStatus) else "invalid"
        return EvidenceRecord(proposal.candidate.id, result, executor_status=status,
                              result_text=result.text_feedback)


class MetricAdmission:
    """Pure objective comparison over public canonical evaluation evidence."""
    def __init__(self, metric="dev/score", direction="maximize", margin=0.0):
        _objective_options({"metric": metric, "direction": direction, "margin": margin}, margin=True)
        self.metric, self.direction, self.margin = metric, direction, float(margin)

    def judge(self, evidence, incumbent):
        if evidence.eval_result.status is not EvalStatus.OK:
            return Decision(False, "evaluation did not succeed")
        value = evidence.eval_result.metrics.get(self.metric)
        _number(value, "candidate objective")
        if incumbent is None:
            return Decision(True, "initial successful candidate")
        if incumbent.eval_result.status is not EvalStatus.OK:
            raise ValueError("incumbent must have successful evidence")
        if evidence.eval_result.fidelity != incumbent.eval_result.fidelity:
            raise ValueError("admission requires the same fidelity")
        def binding(result):
            return getattr(result, "binding", getattr(getattr(result, "contract", None), "binding", None))
        candidate_binding, baseline_binding = binding(evidence.eval_result), binding(incumbent.eval_result)
        if (candidate_binding is None) != (baseline_binding is None):
            raise ValueError("admission requires matching evaluation contracts")
        if candidate_binding is not None and any(
                getattr(candidate_binding, field) != getattr(baseline_binding, field)
                for field in ("evaluator_version", "evaluation_context", "split_id", "fidelity", "seed_set", "request_sha256")):
            raise ValueError("admission requires the same evaluator, content context, split and seeds")
        baseline = incumbent.eval_result.metrics.get(self.metric)
        _number(baseline, "incumbent objective")
        improvement = value - baseline if self.direction == "maximize" else baseline - value
        return Decision(improvement > self.margin,
                        "objective exceeds margin" if improvement > self.margin
                        else "objective does not exceed margin")


def _provided(context, options):
    if not callable(context.llm):
        raise ValueError("provided provider must be callable")
    return context.llm


def _native(context, options):
    domain = context.evaluator
    if any(not callable(getattr(domain, method, None)) for method in ("evaluate", "validate_request")):
        raise ValueError("native domain requires evaluate and validate_request")
    _text(getattr(domain, "evaluator_version", None), "native evaluator_version")
    evaluation_context = getattr(domain, "evaluation_context", None)
    if not isinstance(evaluation_context, str) or not evaluation_context:
        raise ValueError("native domain requires an explicit content evaluation_context")
    # Pure binding validation uses the same digest syntax as returned evidence.
    from core.executor.types import EvalRequest
    binding_for(Proposal(Candidate("native-preflight"), ""), EvalRequest("dev"),
                evaluator_version=domain.evaluator_version, evaluation_context=evaluation_context)
    return domain


def _tokens(context, options):
    def metadata(name):
        value = getattr(context.llm, name, None)
        return value if isinstance(value, str) and value.strip() else "unavailable"
    stamp = context.accounting_stamp or AccountingStamp(
        metadata("supplier"), metadata("model"), "unavailable", "unavailable", "unavailable")
    cfg = context.loop_config
    return BudgetLedger(options.get("total_budget", cfg.total_budget),
                        options.get("control_share", cfg.control_share),
                        options.get("reeval_floor", cfg.reeval_floor), stamp, context.store)


def _hierarchical(context, options):
    stamp = context.accounting_stamp or AccountingStamp(
        getattr(context.llm, "supplier", "unavailable"),
        getattr(context.llm, "model", "unavailable"), "unavailable", "unavailable", "unavailable")
    return HierarchicalBudget(options, stamp, context.store)


def default_registry():
    registry = Registry()
    registry.register("provider", "provided", _provided)
    registry.register("domain", "legacy_prompt", lambda ctx, opts: LegacyPromptDomain(
        ctx.evaluator, ctx.llm, **opts), validate_options=_domain_options)
    registry.register("domain", "native", _native)
    registry.register("policy", "greedy", lambda ctx, opts: GreedyPolicy(ctx.scope_context, **opts),
                      validate_options=policy_options)
    registry.register("policy", "llm_cycles", lambda ctx, opts: LLMCyclesPolicy(
        ctx.scope_context, ctx.llm, **opts), validate_options=policy_options)
    for name in ("draft", "reflective"):
        registry.register("operator", name, lambda ctx, opts, kind=name:
                          PromptOperator(ctx.llm, kind, **opts), validate_options=_operator_options)
    registry.register("skill", "instruction", lambda ctx, opts: InstructionSkill(opts["text"]),
                      validate_options=_skill_options)
    registry.register("frontier", "tree", lambda ctx, opts: ResearchFrontier(
        store=ctx.store, **opts), validate_options=_objective_options)
    registry.register("memory", "scoped", lambda ctx, opts: ContextMemory(
        ctx.store, ctx.scope_context, getattr(ctx.evaluator, "evaluation_context", "")),
        validate_options=context_options)
    registry.register("knowledge", "local_files", lambda ctx, opts: LocalKnowledge(
        opts, ctx.store, mode=ctx.mode), validate_options=knowledge_options)
    registry.register("executor", "inprocess", lambda ctx, opts: InProcessExecutor())
    registry.register("admission", "metric", lambda ctx, opts: MetricAdmission(**opts),
                      validate_options=lambda opts: _objective_options(opts, margin=True))
    registry.register("admission", "layered", lambda ctx, opts: LayeredAdmissionController(
        store=ctx.store, **opts), validate_options=layered_options)
    registry.register("budget", "tokens", _tokens, validate_options=_budget_options)
    registry.register("budget", "hierarchical", _hierarchical, validate_options=hierarchical_options)
    return registry


def composed_profile(name="composed-greedy", mode="benchmark"):
    """A complete reproducible assembly; callers can replace any registry name."""
    return {"schema_version": 1, "name": name, "mode": mode,
            "provider": {"name": "provided"}, "domain": {"name": "legacy_prompt"},
            "policy": {"name": "greedy"},
            "operators": [{"name": "draft"}, {"name": "reflective"}],
            "frontier": {"name": "tree"}, "memory": {"name": "scoped"},
            "executor": {"name": "inprocess"}, "admission": {"name": "metric"},
            "budget": {"name": "tokens"}, "skills": []}
