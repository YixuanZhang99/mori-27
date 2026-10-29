"""Recomputable layered admission with durable query limits and a frozen audit.

The controller never calls an evaluator or a provider. The runtime reserves M3
resources before before_call(), executes that exact call, then supplies the raw
canonical evidence to record(). Every started gate call, including an incumbent
baseline or a failure, consumes one M9 query. Final audit has its own one-call
limit, freezes selection, and never produces search mutations.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields

from core.composition.contracts import Decision, Proposal, json_copy
from core.composition.evaluation import (ComparisonEvidence, binding_for, comparison_projection,
    decode_evidence, encode_evidence, request_digest, validate_evidence)
from core.executor.evaluation_contract import EvaluationBinding
from core.executor.types import Candidate, EvalRequest, EvalStatus


def _finite(value, name, minimum=0):
    try:
        good = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        good = False
    if not good or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")


def _texts(value, name):
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value) \
            or len(set(value)) != len(value):
        raise ValueError(f"{name} must be a list of distinct nonempty strings")


def layered_options(options):
    allowed = {"metric", "direction", "margin", "min_dev_gain", "trigger", "call_budget", "layers",
               "admission_fidelity", "admission_seeds", "final_fidelity", "final_seeds", "selection",
               "monotonicity", "final_audit", "integrity_hooks", "blocked_patterns", "blocked_sources"}
    if type(options) is not dict or set(options) - allowed:
        raise ValueError("unknown layered admission options")
    for name, default in (("metric", "dev/score"), ("admission_fidelity", "admission"),
                          ("final_fidelity", "final_audit")):
        if type(options.get(name, default)) is not str or not options.get(name, default).strip():
            raise ValueError(f"{name} must be nonempty text")
    if options.get("direction", "maximize") not in ("maximize", "minimize"):
        raise ValueError("direction must be maximize or minimize")
    _finite(options.get("margin", 0.0), "margin")
    if "trigger" in options and "min_dev_gain" in options:
        raise ValueError("declare min_dev_gain once, in trigger or as a flat option")
    trigger = options.get("trigger", {})
    if type(trigger) is not dict or set(trigger) - {"min_dev_gain"}:
        raise ValueError("trigger only supports min_dev_gain")
    _finite(trigger.get("min_dev_gain", options.get("min_dev_gain", 0.0)), "min_dev_gain")
    if type(options.get("call_budget", 20)) is not int or options.get("call_budget", 20) < 0:
        raise ValueError("call_budget must be a nonnegative integer")
    if options.get("layers", ["dev", "admission", "final_audit"]) not in (
            ["dev", "admission"], ["dev", "admission", "final_audit"]):
        raise ValueError("layers must be dev/admission, optionally followed by final_audit")
    if options.get("selection", "best") != "best":
        raise ValueError("only selection=best is implemented; top_k is unsupported")
    if options.get("monotonicity", True) is not True:
        raise ValueError("layered admission requires monotonicity=true")
    final = options.get("final_audit", {"isolation": True, "runs": 1})
    if type(final) is not dict or set(final) != {"isolation", "runs"} \
            or final["isolation"] is not True or type(final["runs"]) is not int or final["runs"] != 1:
        raise ValueError("final_audit requires isolation=true and runs=1")
    for name in ("admission_seeds", "final_seeds"):
        seeds = options.get(name)
        if seeds is not None and (type(seeds) is not list or not seeds
                or any(type(seed) is not int or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds)):
            raise ValueError(f"{name} must be None or distinct nonnegative integer seeds")
    hooks = options.get("integrity_hooks", ["hash_check"])
    _texts(hooks, "integrity_hooks")
    if set(hooks) - {"hash_check", "canary_scan", "source_blocklist"}:
        raise ValueError("unsupported integrity hook; human_approval requires an explicit HITL implementation")
    if "hash_check" not in hooks:
        raise ValueError("hash_check cannot be disabled")
    for name in ("blocked_patterns", "blocked_sources"):
        _texts(options.get(name, []), name)


def _json(value):
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False))


def _digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _binding_payload(binding):
    return _json(asdict(binding))


@dataclass(frozen=True)
class GateCall:
    key: str
    phase: str
    proposal: Proposal
    request: EvalRequest
    binding: EvaluationBinding


@dataclass(frozen=True)
class GatePlan:
    plan_id: str
    candidate_id: str
    incumbent_id: str | None
    candidate_key: str | None
    incumbent_key: str | None
    calls: tuple[GateCall, ...]
    candidate_dev: ComparisonEvidence
    incumbent_dev: ComparisonEvidence | None
    triggered: bool
    reason: str


@dataclass(frozen=True)
class FinalPlan:
    selected_id: str | None
    key: str | None
    calls: tuple[GateCall, ...]
    enabled: bool


@dataclass(frozen=True)
class LayeredDecision(Decision):
    receipt_id: str
    decision_context: dict


def _comparison_payload(view, split):
    if type(view) is not dict or set(view) != {"candidate_id", "eval_result", "attempt", "executor_status"} \
            or type(view["attempt"]) is not int or view["attempt"] < 1:
        raise ValueError("invalid restricted comparison view")
    result = view["eval_result"]
    if type(result) is not dict or set(result) != {"status", "metrics", "fidelity", "uncertainty", "binding"}:
        raise ValueError("receipt comparison contains unauthorized fields")
    binding = result["binding"]
    if type(binding) is not dict or set(binding) != {item.name for item in fields(EvaluationBinding)} \
            or binding["candidate_id"] != view["candidate_id"] or binding["split_id"] != split \
            or binding["fidelity"] != result["fidelity"]:
        raise ValueError("receipt comparison binding mismatch")
    for name in ("candidate_id", "evaluator_version", "split_id", "fidelity"):
        if type(binding[name]) is not str or not binding[name].strip():
            raise ValueError("invalid receipt binding text")
    for name, pattern in (("artifact_sha256", r"[0-9a-f]{64}"), ("request_sha256", r"sha256:[0-9a-f]{64}")):
        if type(binding[name]) is not str or not re.fullmatch(pattern, binding[name]):
            raise ValueError("invalid receipt binding digest")
    context = binding["evaluation_context"]
    if type(context) is not str or context and not re.fullmatch(r"sha256:[0-9a-f]{64}", context):
        raise ValueError("invalid receipt dataset binding")
    seeds = binding["seed_set"]
    if seeds is not None and (type(seeds) is not list or any(type(seed) is not int or seed < 0 for seed in seeds)
                              or len(set(seeds)) != len(seeds)):
        raise ValueError("invalid receipt seed binding")
    statuses = {"ok": {"scored"}, "failed_to_run": {"failed_to_run", "skipped"},
                "timeout": {"timeout"}, "invalid": {"invalid"}}
    if type(result["status"]) is not str or result["status"] not in statuses \
            or view["executor_status"] not in statuses[result["status"]] or type(result["metrics"]) is not dict:
        raise ValueError("invalid receipt comparison status")
    for name, value in result["metrics"].items():
        if type(name) is not str or not name.strip() or type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("invalid receipt public metric")
    if result["uncertainty"] is not None:
        _finite(result["uncertainty"], "receipt uncertainty")


def _trigger_passed(candidate, incumbent, rules):
    if candidate.eval_result.status is not EvalStatus.OK:
        return False
    values = [candidate.eval_result.metrics.get(rules["metric"])]
    if incumbent is not None:
        if incumbent.eval_result.status is not EvalStatus.OK:
            raise ValueError("development incumbent must be successful")
        LayeredAdmissionController._compatible(comparison_projection(candidate), comparison_projection(incumbent))
        values.append(incumbent.eval_result.metrics.get(rules["metric"]))
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("development trigger requires a finite public objective")
    if len(values) == 1:
        return True
    gain = values[0] - values[1] if rules["direction"] == "maximize" else values[1] - values[0]
    return gain > 0 and gain >= rules["min_dev_gain"]


def validate_layered_receipt(receipt, *, candidate_evidence=None, incumbent_evidence=None,
                             candidate_dev=None, incumbent_dev=None):
    """Recompute a receipt using actual records, never a self-attested score."""
    if not isinstance(receipt, LayeredDecision):
        raise ValueError("receipt must be a LayeredDecision")
    context = json_copy(receipt.decision_context)
    expected = {"schema_version", "candidate_id", "incumbent_id", "rules", "development",
                "admission", "decision", "admission_rule_evaluated", "development_trigger_passed"}
    if set(context) != expected or type(context["schema_version"]) is not int or context["schema_version"] != 1 \
            or context["decision"] != {"admit": receipt.admit, "reason": receipt.reason} \
            or _digest(context) != receipt.receipt_id or type(context["admission_rule_evaluated"]) is not bool \
            or type(context["development_trigger_passed"]) is not bool:
        raise ValueError("invalid layered receipt identity")
    rules = context["rules"]
    if type(rules) is not dict or set(rules) != {"metric", "direction", "margin", "min_dev_gain", "monotonicity"}:
        raise ValueError("invalid layered receipt rules")
    layered_options({"metric": rules["metric"], "direction": rules["direction"], "margin": rules["margin"],
                     "min_dev_gain": rules["min_dev_gain"], "monotonicity": rules["monotonicity"]})
    admission = context["admission"]
    if type(admission) is not dict or set(admission) != {"candidate", "incumbent"}:
        raise ValueError("invalid admission receipt evidence")
    development = context["development"]
    if type(development) is not dict or set(development) != {"candidate", "incumbent"}:
        raise ValueError("invalid development receipt evidence")
    for section, split in ((development, "dev"), (admission, "admission")):
        for role in ("candidate", "incumbent"):
            if section[role] is not None:
                _comparison_payload(section[role], split)
                if section[role]["candidate_id"] != context[role + "_id"]:
                    raise ValueError("receipt comparison candidate identity mismatch")
    if development["candidate"] is None or (development["incumbent"] is None) != (context["incumbent_id"] is None):
        raise ValueError("receipt omitted required development evidence")
    for role, record in (("candidate", candidate_dev), ("incumbent", incumbent_dev)):
        if development[role] is None:
            if record is not None:
                raise ValueError("receipt omitted supplied development evidence")
            continue
        if record is None:
            raise ValueError("receipt validation requires actual evaluation records for the development trigger")
        validate_evidence(record)
        if record.eval_result.contract.binding.split_id != "dev" \
                or _json(asdict(comparison_projection(record))) != development[role]:
            raise ValueError("receipt differs from actual development evidence")
    trigger = _trigger_passed(candidate_dev, incumbent_dev, rules)
    if trigger != context["development_trigger_passed"]:
        raise ValueError("development trigger is not reproducible from actual evidence")
    for role, record, candidate_id in (("candidate", candidate_evidence, context["candidate_id"]),
                                      ("incumbent", incumbent_evidence, context["incumbent_id"])):
        if admission[role] is None:
            if record is not None:
                raise ValueError("receipt omitted supplied evaluation evidence")
            continue
        if record is None:
            raise ValueError("receipt validation requires actual evaluation records")
        validate_evidence(record)
        if record.candidate_id != candidate_id or record.eval_result.contract.binding.split_id != "admission" \
                or not record.eval_result.contract.binding.evaluation_context \
                or _json(asdict(comparison_projection(record))) != admission[role]:
            raise ValueError("receipt differs from actual evaluation evidence")
        dev_binding = development[role]["eval_result"]["binding"]
        actual_binding = record.eval_result.contract.binding
        if actual_binding.artifact_sha256 != dev_binding["artifact_sha256"] \
                or actual_binding.evaluator_version != dev_binding["evaluator_version"]:
            raise ValueError("development and admission must evaluate the same artifact and evaluator version")
    if not context["admission_rule_evaluated"]:
        if receipt.admit:
            raise ValueError("unevaluated admission cannot authorize acceptance")
        return receipt
    if candidate_evidence is None:
        raise ValueError("evaluated admission requires candidate evidence")
    if not trigger:
        raise ValueError("admission evaluation cannot bypass the development trigger")
    accepted = candidate_evidence.eval_result.status is EvalStatus.OK
    if context["incumbent_id"] is not None:
        if incumbent_evidence is None:
            raise ValueError("paired admission requires incumbent evidence")
        accepted = accepted and incumbent_evidence.eval_result.status is EvalStatus.OK
    if accepted:
        metric = rules["metric"]
        values = [candidate_evidence.eval_result.metrics.get(metric)]
        if incumbent_evidence is not None:
            LayeredAdmissionController._compatible(comparison_projection(candidate_evidence),
                                                   comparison_projection(incumbent_evidence))
            values.append(incumbent_evidence.eval_result.metrics.get(metric))
        for value in values:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("receipt requires a finite public objective")
        if len(values) == 2:
            gain = values[0] - values[1] if rules["direction"] == "maximize" else values[1] - values[0]
            accepted = gain > rules["margin"]
    if receipt.admit != accepted:
        raise ValueError("receipt decision is not reproducible from admission evidence")
    return receipt


class LayeredAdmissionController:
    """M9 query accounting, exact-bound evidence cache and a best-only ratchet.

    min_dev_gain and margin are absolute differences in the configured metric.
    Canary patterns and blocked source references are explicit exact strings;
    source checks do not imply a general URL or content-classification service.
    """
    def __init__(self, *, store=None, **options):
        layered_options(options)
        self.options = {"metric": options.get("metric", "dev/score"),
            "direction": options.get("direction", "maximize"), "margin": options.get("margin", 0.0),
            "trigger": {"min_dev_gain": options.get("trigger", {}).get("min_dev_gain", options.get("min_dev_gain", 0.0))},
            "call_budget": options.get("call_budget", 20),
            "layers": options.get("layers", ["dev", "admission", "final_audit"]),
            "admission_fidelity": options.get("admission_fidelity", "admission"),
            "admission_seeds": options.get("admission_seeds"),
            "final_fidelity": options.get("final_fidelity", "final_audit"),
            "final_seeds": options.get("final_seeds"), "selection": "best", "monotonicity": True,
            "final_audit": {"isolation": True, "runs": 1},
            "integrity_hooks": options.get("integrity_hooks", ["hash_check"]),
            "blocked_patterns": options.get("blocked_patterns", []),
            "blocked_sources": options.get("blocked_sources", [])}
        self.options = json_copy(self.options)
        self.metric, self.direction = self.options["metric"], self.options["direction"]
        self.store = store
        self._config_id = _digest(self.options)
        self._cache, self._calls, self._authorized, self._decisions, self._prepared = {}, {}, {}, {}, {}
        self._development_records = {}
        self._dev_best = self._selected = None
        self._frozen = False
        self._final = None
        self._sequence = 0

    @property
    def gate_calls(self):
        return sum(item["phase"] == "admission" for item in self._calls.values())

    @property
    def final_calls(self):
        return sum(item["phase"] == "final_audit" for item in self._calls.values())

    @property
    def remaining_calls(self):
        return self.options["call_budget"] - self.gate_calls

    @property
    def frozen(self):
        return self._frozen

    def request_for(self, phase):
        if phase not in {"admission", "final_audit"}:
            raise ValueError("unknown admission phase")
        prefix = "admission" if phase == "admission" else "final"
        seeds = self.options[prefix + "_seeds"]
        return EvalRequest(self.options[prefix + "_fidelity"],
                           seed_set=list(seeds) if seeds is not None else None, split_id=phase)

    def validate_domain(self, domain):
        if not callable(getattr(domain, "evaluation_context_for", None)) \
                or not callable(getattr(domain, "validate_request", None)):
            raise ValueError("layered admission needs split-aware domain validation and content identities")
        contexts = {}
        for phase in self.options["layers"][1:]:
            request = self.request_for(phase)
            domain.validate_request(request)
            context = domain.evaluation_context_for(request)
            if not context:
                raise ValueError("layered evaluation requires a content-bound split")
            binding_for(Proposal(Candidate("gate-preflight"), ""), request,
                        evaluator_version=domain.evaluator_version, evaluation_context=context)
            contexts[phase] = context
        if len(set(contexts.values())) != len(contexts):
            raise ValueError("admission and final audit need distinct dataset content identities")
        return contexts

    def check_integrity(self, proposal, source_refs=()):
        if not isinstance(proposal, Proposal) or type(proposal.artifact) is not str:
            raise ValueError("integrity check requires a concrete proposal")
        if any(pattern in proposal.artifact for pattern in self.options["blocked_patterns"]):
            raise ValueError("candidate contains a blocked canary pattern")
        if not isinstance(source_refs, (tuple, list)) or any(type(item) is not str for item in source_refs):
            raise ValueError("source references must be strings")
        if set(source_refs) & set(self.options["blocked_sources"]):
            raise ValueError("candidate context contains a blocked source")

    def _call(self, proposal, phase, domain):
        request = self.request_for(phase)
        domain.validate_request(request)
        context = domain.evaluation_context_for(request)
        if not context:
            raise ValueError("admission split lacks a dataset content identity")
        binding = binding_for(proposal, request, evaluator_version=domain.evaluator_version,
                              evaluation_context=context)
        return GateCall(_digest(_binding_payload(binding)), phase, proposal, request, binding)

    def _score(self, evidence):
        value = evidence.eval_result.metrics.get(self.metric)
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("admission requires a finite public objective")
        return value

    def _gain(self, candidate, baseline):
        delta = self._score(candidate) - self._score(baseline)
        return delta if self.direction == "maximize" else -delta

    @staticmethod
    def _compatible(candidate, baseline):
        left, right = candidate.eval_result.binding, baseline.eval_result.binding
        if any(getattr(left, field) != getattr(right, field) for field in
               ("evaluator_version", "evaluation_context", "split_id", "fidelity", "seed_set", "request_sha256")):
            raise ValueError("admission comparisons require identical evaluator, dataset, split, request and seeds")

    @staticmethod
    def _match_proposal(proposal, evidence, split):
        validate_evidence(evidence)
        binding = evidence.eval_result.contract.binding
        digest = hashlib.sha256(proposal.artifact.encode()).hexdigest()
        if binding.candidate_id != proposal.candidate.id or binding.artifact_sha256 != digest \
                or binding.split_id != split:
            raise ValueError("proposal differs from its evaluated artifact or split")

    def _persist(self, event):
        self._sequence += 1
        if self.store is not None:
            self.store.append("layered_admission_state", {"controller": self._config_id,
                "event": event, "state": self.checkpoint_state()})

    def prepare(self, candidate, dev, incumbent, incumbent_dev, domain, *, source_refs=()):
        if self._frozen:
            raise ValueError("search is frozen for final audit")
        self.check_integrity(candidate, source_refs)
        self._match_proposal(candidate, dev, "dev")
        if (incumbent is None) != (incumbent_dev is None):
            raise ValueError("incumbent proposal and development evidence must be supplied together")
        if self._selected is not None and (incumbent is None or incumbent.candidate.id != self._selected.candidate_id):
            raise ValueError("incumbent differs from the current gate-selected candidate")
        candidate_view = comparison_projection(dev)
        baseline_view = None
        if incumbent is not None:
            if incumbent.candidate.id == candidate.candidate.id:
                raise ValueError("candidate and incumbent identities must differ")
            self._match_proposal(incumbent, incumbent_dev, "dev")
            baseline_view = comparison_projection(incumbent_dev)
            self._compatible(candidate_view, baseline_view)
            if baseline_view.eval_result.status is not EvalStatus.OK:
                raise ValueError("incumbent development evidence must be successful")
        for observed in (incumbent_dev, dev):
            if observed is None:
                continue
            key = _digest(_binding_payload(observed.eval_result.contract.binding))
            if key in self._development_records and self._development_records[key] != observed:
                raise ValueError("development evidence changed for an existing evaluation binding")
            if key not in self._development_records:
                self._development_records[key] = decode_evidence(encode_evidence(observed))
                self._persist("development_recorded")
        for observed, view in ((incumbent_dev, baseline_view), (dev, candidate_view)):
            if observed is None or observed.eval_result.status is not EvalStatus.OK:
                continue
            self._score(view)
            if self._dev_best is not None:
                self._compatible(view, comparison_projection(self._dev_best))
            if self._dev_best is None or self._gain(view, comparison_projection(self._dev_best)) > 0:
                self._dev_best = decode_evidence(encode_evidence(observed))
                self._persist("dev_best")
        reason, triggered = "development trigger passed", True
        if dev.eval_result.status is not EvalStatus.OK:
            reason, triggered = "development evaluation did not succeed", False
        elif baseline_view is not None:
            gain = self._gain(candidate_view, baseline_view)
            if gain <= 0 or gain < self.options["trigger"]["min_dev_gain"]:
                reason, triggered = "development gain below trigger", False
        candidate_call = incumbent_call = None
        calls = []
        if triggered:
            candidate_call = self._call(candidate, "admission", domain)
            if candidate_call.binding.evaluation_context == candidate_view.eval_result.binding.evaluation_context:
                raise ValueError("admission cannot reuse the development dataset context")
            incumbent_call = self._call(incumbent, "admission", domain) if incumbent is not None else None
            if self._selected is not None and incumbent_call.binding != self._selected.eval_result.contract.binding:
                raise ValueError("gate-selected incumbent evaluation context changed")
            for call in (incumbent_call, candidate_call):
                if call is None or call.key in self._cache:
                    continue
                if call.key in self._calls:
                    reason, triggered = "previous admission invocation has no reusable evidence", False
                    break
                calls.append(call)
            if triggered and len(calls) > self.remaining_calls:
                reason, triggered = "admission call budget exhausted", False
            if triggered:
                for call in calls:
                    self._authorized[call.key] = self._call_payload(call)
            else:
                calls = []
        identity = {"candidate": asdict(candidate_view), "incumbent": asdict(baseline_view) if baseline_view else None,
                    "candidate_key": candidate_call.key if candidate_call else None,
                    "incumbent_key": incumbent_call.key if incumbent_call else None,
                    "triggered": triggered, "reason": reason, "config": self._config_id}
        plan = GatePlan(_digest(identity), candidate.candidate.id,
            incumbent.candidate.id if incumbent else None, candidate_call.key if candidate_call else None,
            incumbent_call.key if incumbent_call else None, tuple(calls), candidate_view, baseline_view, triggered, reason)
        self._prepared[plan.plan_id] = _json(asdict(plan))
        return plan

    def _validate_plan(self, plan):
        if not isinstance(plan, GatePlan) or self._prepared.get(plan.plan_id) != _json(asdict(plan)):
            raise ValueError("admission plan was not prepared or has changed")
        if self._selected is not None and plan.incumbent_id != self._selected.candidate_id \
                and plan.plan_id not in self._decisions:
            raise ValueError("admission plan uses a stale incumbent")

    @staticmethod
    def _call_payload(call):
        if not isinstance(call, GateCall) or call.phase not in {"admission", "final_audit"}:
            raise ValueError("invalid planned gate call")
        actual = binding_for(call.proposal, call.request, evaluator_version=call.binding.evaluator_version,
                             evaluation_context=call.binding.evaluation_context)
        if actual != call.binding or call.request.split_id != call.phase or call.key != _digest(_binding_payload(call.binding)):
            raise ValueError("planned call binding changed")
        return {"phase": call.phase, "binding": _binding_payload(call.binding), "request": _json(asdict(call.request))}

    def before_call(self, call):
        payload = self._call_payload(call)
        if self._authorized.get(call.key) != payload:
            raise ValueError("gate invocation was not authorized by its prepared plan")
        if call.key in self._calls or call.key in self._cache:
            raise ValueError("gate invocation was already started or cached")
        if call.phase == "admission":
            if self._frozen or self.remaining_calls < 1:
                raise ValueError("admission query limit reached or search frozen")
        elif not self._frozen or self._final is None or self._final["key"] != call.key \
                or self._final["status"] != "ready" or self.final_calls >= 1:
            raise ValueError("final audit is not authorized or has already run")
        self._calls[call.key] = {**payload, "status": "pending"}
        if call.phase == "final_audit":
            self._final["status"] = "pending"
        self._persist("call_started")

    def record(self, call, evidence):
        payload = self._call_payload(call)
        recorded = self._calls.get(call.key)
        if recorded is None or recorded != {**payload, "status": "pending"}:
            raise ValueError("evidence requires its pending recorded invocation")
        validate_evidence(evidence, expected_binding=call.binding)
        self._cache[call.key] = decode_evidence(encode_evidence(evidence), expected_binding=call.binding)
        self._calls[call.key]["status"] = "complete"
        if call.phase == "final_audit":
            self._final["status"] = "complete"
        self._persist("call_completed")

    def mark_failed(self, call, reason="evaluation invocation failed"):
        payload = self._call_payload(call)
        if self._calls.get(call.key) != {**payload, "status": "pending"}:
            raise ValueError("only a pending invocation can be marked failed")
        if type(reason) is not str or not reason.strip():
            raise ValueError("failed invocation requires a reason")
        self._calls[call.key]["status"] = "failed"
        self._calls[call.key]["failure_reason"] = reason
        if call.phase == "final_audit":
            self._final["status"] = "failed"
        self._persist("call_failed")

    @staticmethod
    def _view(evidence):
        return _json(asdict(comparison_projection(evidence))) if evidence is not None else None

    def _decision(self, plan, admit, reason, *, evaluated=False):
        candidate = self._cache.get(plan.candidate_key)
        incumbent = self._cache.get(plan.incumbent_key)
        candidate_dev = self._development_records[_digest(_binding_payload(plan.candidate_dev.eval_result.binding))]
        incumbent_dev = self._development_records[_digest(_binding_payload(plan.incumbent_dev.eval_result.binding))] \
            if plan.incumbent_dev else None
        rules = {"metric": self.metric, "direction": self.direction, "margin": self.options["margin"],
                 "min_dev_gain": self.options["trigger"]["min_dev_gain"], "monotonicity": True}
        context = {"schema_version": 1, "candidate_id": plan.candidate_id, "incumbent_id": plan.incumbent_id,
            "rules": rules,
            "development": {"candidate": _json(asdict(plan.candidate_dev)),
                            "incumbent": _json(asdict(plan.incumbent_dev)) if plan.incumbent_dev else None},
            "admission": {"candidate": self._view(candidate), "incumbent": self._view(incumbent)},
            "admission_rule_evaluated": evaluated,
            "development_trigger_passed": _trigger_passed(candidate_dev, incumbent_dev, rules),
            "decision": {"admit": admit, "reason": reason}}
        receipt = LayeredDecision(admit, reason, _digest(context), context)
        validate_layered_receipt(receipt, candidate_evidence=candidate, incumbent_evidence=incumbent,
                                 candidate_dev=candidate_dev, incumbent_dev=incumbent_dev)
        self._decisions[plan.plan_id] = receipt
        for call in plan.calls:
            self._authorized.pop(call.key, None)
        if admit:
            self._selected = candidate
        elif self._selected is None and incumbent is not None and incumbent.eval_result.status is EvalStatus.OK:
            self._selected = incumbent
        self._persist("decision")
        if self.store is not None:
            self.store.append("layered_admission_receipt", asdict(receipt))
        return receipt

    def decline(self, plan, reason):
        if self._frozen:
            raise ValueError("search is frozen")
        if type(reason) is not str or not reason.strip():
            raise ValueError("declined plan requires a reason")
        self._validate_plan(plan)
        if plan.plan_id in self._decisions:
            return self._decisions[plan.plan_id]
        return self._decision(plan, False, reason)

    def judge(self, plan):
        if self._frozen:
            raise ValueError("search is frozen")
        self._validate_plan(plan)
        if plan.plan_id in self._decisions:
            return self._decisions[plan.plan_id]
        if not plan.triggered:
            return self._decision(plan, False, plan.reason)
        candidate, baseline = self._cache.get(plan.candidate_key), self._cache.get(plan.incumbent_key)
        if candidate is None or plan.incumbent_key is not None and baseline is None:
            raise ValueError("admission plan does not yet have all required evidence")
        if candidate.eval_result.status is not EvalStatus.OK:
            return self._decision(plan, False, "candidate admission evaluation did not succeed", evaluated=True)
        left = comparison_projection(candidate)
        self._score(left)
        if baseline is None:
            return self._decision(plan, True, "initial candidate passed admission", evaluated=True)
        if baseline.eval_result.status is not EvalStatus.OK:
            return self._decision(plan, False, "incumbent admission evaluation did not succeed", evaluated=True)
        right = comparison_projection(baseline)
        self._compatible(left, right)
        accepted = self._gain(left, right) > self.options["margin"]
        return self._decision(plan, accepted, "admission objective exceeds margin" if accepted
                              else "admission objective does not exceed margin", evaluated=True)

    def freeze(self, selected, domain):
        selected_id = selected.candidate.id if selected is not None else None
        if selected_id != (self._selected.candidate_id if self._selected else None):
            raise ValueError("final selection differs from the gate-selected incumbent")
        enabled = "final_audit" in self.options["layers"]
        if selected is not None:
            self._match_proposal(selected, self._selected, "admission")
        if self._frozen:
            key = self._final["key"]
            call = self._call(selected, "final_audit", domain) if key and self._final["status"] == "ready" else None
            if call is not None:
                if call.key != key:
                    raise ValueError("frozen final audit identity changed")
                self._authorized[key] = self._call_payload(call)
            return FinalPlan(selected_id, key, (call,) if call else (), enabled)
        call = self._call(selected, "final_audit", domain) if enabled and selected is not None else None
        if call is not None and call.binding.evaluation_context in {
                self._selected.eval_result.contract.binding.evaluation_context,
                self._dev_best.eval_result.contract.binding.evaluation_context}:
            raise ValueError("final audit requires a distinct frozen dataset context")
        self._frozen = True
        self._final = {"selected_id": selected_id, "key": call.key if call else None,
                       "status": "ready" if call else "disabled" if not enabled else "no_selection"}
        if call:
            self._authorized[call.key] = self._call_payload(call)
        self._persist("selection_frozen")
        return FinalPlan(selected_id, call.key if call else None, (call,) if call else (), enabled)

    def skip_final(self, reason):
        if not self._frozen or self._final is None or self._final["status"] != "ready" or self.final_calls:
            raise ValueError("only an unstarted final audit can be skipped")
        if type(reason) is not str or not reason.strip():
            raise ValueError("skipped audit requires a reason")
        self._final["status"] = "not_run"
        self._final["reason"] = reason
        self._persist("final_not_run")

    def final_report(self):
        if not self._frozen:
            raise ValueError("final audit requires frozen selection")
        if self._final["status"] in {"ready", "pending"}:
            raise ValueError("final audit has not completed")
        evidence = self._cache.get(self._final["key"])
        return {"state": self._final["status"], "selected_id": self._final["selected_id"],
                "evidence": self._view(evidence), "calls": self.final_calls,
                **({"reason": self._final["reason"]} if "reason" in self._final else {})}

    def report(self):
        return {"dev_best": self._view(self._dev_best), "gate_selected": self._view(self._selected),
                "final_audit": self.final_report() if self._frozen else {"state": "not_frozen"},
                "gate_calls": self.gate_calls, "gate_call_budget": self.options["call_budget"]}

    def checkpoint_state(self):
        return {"schema_version": 1, "options": json_copy(self.options), "sequence": self._sequence,
            "calls": json_copy(self._calls), "cache": {key: encode_evidence(value) for key, value in self._cache.items()},
            "development_records": {key: encode_evidence(value) for key, value in self._development_records.items()},
            "dev_best": encode_evidence(self._dev_best) if self._dev_best else None,
            "selected": encode_evidence(self._selected) if self._selected else None,
            "frozen": self._frozen, "final": json_copy(self._final),
            "decisions": {key: _json(asdict(value)) for key, value in self._decisions.items()}}

    def restore_state(self, state):
        state = json_copy(state, label="layered admission checkpoint")
        expected = {"schema_version", "options", "sequence", "calls", "cache", "development_records",
                    "dev_best", "selected", "frozen", "final", "decisions"}
        if type(state) is not dict or set(state) != expected or type(state["schema_version"]) is not int \
                or state["schema_version"] != 1 or state["options"] != self.options \
                or type(state["sequence"]) is not int or state["sequence"] < 0 or type(state["frozen"]) is not bool:
            raise ValueError("incompatible layered admission checkpoint")
        if any(type(state[key]) is not dict for key in ("calls", "cache", "decisions", "development_records")):
            raise ValueError("invalid admission checkpoint maps")
        cache = {key: decode_evidence(value) for key, value in state["cache"].items()}
        development_records = {key: decode_evidence(value) for key, value in state["development_records"].items()}
        for key, record in development_records.items():
            if key != _digest(_binding_payload(record.eval_result.contract.binding)) \
                    or record.eval_result.contract.binding.split_id != "dev":
                raise ValueError("invalid actual development record checkpoint")
        for key, call in state["calls"].items():
            if type(call) is not dict or set(call) - {"phase", "binding", "request", "status", "failure_reason"} \
                    or not {"phase", "binding", "request", "status"} <= set(call) \
                    or call["phase"] not in {"admission", "final_audit"} \
                    or call["status"] not in {"pending", "complete", "failed"}:
                raise ValueError("invalid durable admission invocation")
            if "failure_reason" in call and (call["status"] != "failed"
                    or type(call["failure_reason"]) is not str or not call["failure_reason"].strip()):
                raise ValueError("invalid failed invocation reason")
            request = EvalRequest(**call["request"])
            request.validate()
            binding_data = dict(call["binding"])
            if binding_data.get("seed_set") is not None:
                binding_data["seed_set"] = tuple(binding_data["seed_set"])
            binding = EvaluationBinding(**binding_data)
            _comparison_payload({"candidate_id": binding.candidate_id, "attempt": 1,
                "executor_status": "failed_to_run", "eval_result": {"status": "failed_to_run", "metrics": {},
                    "fidelity": binding.fidelity, "uncertainty": None, "binding": _binding_payload(binding)}}, call["phase"])
            if _digest(_binding_payload(binding)) != key or request != self.request_for(call["phase"]) \
                    or binding.request_sha256 != request_digest(request) or binding.fidelity != request.fidelity \
                    or binding.seed_set != (tuple(request.seed_set) if request.seed_set is not None else None):
                raise ValueError("durable admission invocation identity mismatch")
            if (key in cache) != (call["status"] == "complete"):
                raise ValueError("admission cache differs from invocation outcome")
            if key in cache:
                validate_evidence(cache[key], expected_binding=binding)
        if set(cache) - set(state["calls"]):
            raise ValueError("admission cache lacks a real recorded invocation")
        gate_count = sum(call["phase"] == "admission" for call in state["calls"].values())
        final_count = sum(call["phase"] == "final_audit" for call in state["calls"].values())
        if gate_count > self.options["call_budget"] or final_count > 1:
            raise ValueError("admission checkpoint exceeds call limits")
        dev = decode_evidence(state["dev_best"]) if state["dev_best"] else None
        selected = decode_evidence(state["selected"]) if state["selected"] else None
        if dev is not None and (dev.eval_result.status is not EvalStatus.OK
                or dev.eval_result.contract.binding.split_id != "dev"
                or development_records.get(_digest(_binding_payload(dev.eval_result.contract.binding))) != dev):
            raise ValueError("invalid development best checkpoint")
        if selected is not None:
            key = _digest(_binding_payload(selected.eval_result.contract.binding))
            if key not in cache or cache[key] != selected or selected.eval_result.status is not EvalStatus.OK \
                    or selected.eval_result.contract.binding.split_id != "admission":
                raise ValueError("gate selection lacks successful cached admission evidence")
        final = state["final"]
        if state["frozen"]:
            if type(final) is not dict or set(final) - {"selected_id", "key", "status", "reason"} \
                    or not {"selected_id", "key", "status"} <= set(final) \
                    or final["selected_id"] != (selected.candidate_id if selected else None) \
                    or final["status"] not in {"ready", "pending", "complete", "failed", "disabled", "no_selection", "not_run"}:
                raise ValueError("invalid frozen audit checkpoint")
            if final["status"] in {"pending", "complete", "failed"}:
                if final["key"] not in state["calls"] or state["calls"][final["key"]]["phase"] != "final_audit" \
                        or state["calls"][final["key"]]["status"] != final["status"]:
                    raise ValueError("final audit state differs from its recorded invocation")
        elif final is not None or final_count:
            raise ValueError("unfrozen checkpoint cannot contain final audit")
        decisions = {}
        eligible_selections = []
        for key, value in state["decisions"].items():
            if type(value) is not dict or set(value) != {"admit", "reason", "receipt_id", "decision_context"} \
                    or value["receipt_id"] != _digest(value["decision_context"]) \
                    or value["decision_context"].get("decision") != {"admit": value["admit"], "reason": value["reason"]}:
                raise ValueError("invalid admission receipt checkpoint")
            decisions[key] = LayeredDecision(**value)
            views = value["decision_context"]["admission"]
            actual = {role: cache.get(_digest(view["eval_result"]["binding"])) if view else None
                      for role, view in views.items()}
            development = {role: development_records.get(_digest(view["eval_result"]["binding"])) if view else None
                           for role, view in value["decision_context"]["development"].items()}
            validate_layered_receipt(decisions[key], candidate_evidence=actual["candidate"],
                                     incumbent_evidence=actual["incumbent"],
                                     candidate_dev=development["candidate"], incumbent_dev=development["incumbent"])
            if decisions[key].admit:
                eligible_selections.append(actual["candidate"])
            if actual["incumbent"] is not None and actual["incumbent"].eval_result.status is EvalStatus.OK:
                eligible_selections.append(actual["incumbent"])
        if selected is not None:
            if not any(record == selected for record in eligible_selections):
                raise ValueError("gate selection lacks an accepted decision or verified incumbent")
            selected_view = comparison_projection(selected)
            for record in eligible_selections:
                self._compatible(selected_view, comparison_projection(record))
                if self._gain(comparison_projection(record), selected_view) > 0:
                    raise ValueError("gate selection violates the monotonic incumbent rule")
        elif eligible_selections:
            raise ValueError("checkpoint forgot a gate-selected incumbent")
        if self.store is not None:
            latest = [row["payload"]["state"] for row in self.store.read("layered_admission_state")
                      if row["payload"].get("controller") == self._config_id]
            if latest and latest[-1] != state:
                raise ValueError("durable admission history differs from checkpoint; refusing reexecution")
        self._calls, self._cache, self._decisions = state["calls"], cache, decisions
        self._development_records = development_records
        self._dev_best, self._selected = dev, selected
        self._frozen, self._final, self._sequence = state["frozen"], final, state["sequence"]
        self._authorized, self._prepared = {}, {}
