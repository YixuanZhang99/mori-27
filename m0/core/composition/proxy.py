"""Bound, durable monitoring of heterogeneous development proxies.

Calibration is an explicitly separate development split. This controller never
calls a provider, spends budget, imports gate evidence, or mutates search state.
The runtime must reserve the anchor operation before ``begin`` and execute the
exact returned request. A degraded monitor stays degraded for this run: every
candidate needs an anchor and only a new comparable true best may advance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from dataclasses import asdict, dataclass
from decimal import Decimal

from core.composition.contracts import Proposal, json_copy
from core.composition.evaluation import (binding_for, decode_evidence, encode_evidence,
    request_digest, validate_evidence)
from core.executor.evaluation_contract import EvaluationBinding
from core.executor.types import EvalRequest, EvalStatus, EvidenceRecord

JOURNAL_KIND = "proxy_validity"
_FIELDS = {"every_n_cycles", "anchor_request", "proxy_metric", "true_metric",
           "proxy_direction", "true_direction", "min_pairs", "window", "min_rank_correlation"}


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _hash(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


def proxy_options(options):
    """Strict, side-effect-free validation for hierarchical.proxy_validity."""
    if type(options) is not dict or set(options) != _FIELDS:
        raise ValueError("proxy_validity requires exactly its documented configuration fields")
    json_copy(options, label="proxy validity configuration")
    for name in ("every_n_cycles", "min_pairs", "window"):
        if type(options[name]) is not int or options[name] < (3 if name == "min_pairs" else 1):
            raise ValueError(f"{name} must be a positive integer; min_pairs must be at least three")
    if options["window"] < options["min_pairs"]:
        raise ValueError("proxy window must cover min_pairs")
    for name in ("proxy_metric", "true_metric"):
        _text(options[name], name)
    for name in ("proxy_direction", "true_direction"):
        if type(options[name]) is not str or options[name] not in {"maximize", "minimize"}:
            raise ValueError("proxy and true directions must be maximize or minimize")
    threshold = options["min_rank_correlation"]
    if type(threshold) not in (int, float) or not -1 <= threshold <= 1:
        raise ValueError("min_rank_correlation must be finite and between -1 and 1")
    request = options["anchor_request"]
    if type(request) is not dict or not {"fidelity", "split_id"}.issubset(request) \
            or set(request) - {"fidelity", "split_id", "seed_set", "time_limit", "budget_token", "resume_from"}:
        raise ValueError("anchor_request must be an explicit canonical evaluation request")
    parsed = EvalRequest(**request)
    parsed.validate()
    if parsed.split_id != "calibration":
        raise ValueError("proxy anchors require the independent calibration split")


def _ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2
        for position in order[start:end]:
            ranks[position] = average
        start = end
    return ranks


def spearman_rank_correlation(left, right):
    """Average-rank Pearson correlation; constant or <2 pairs is undefined."""
    if len(left) != len(right):
        raise ValueError("rank correlation requires paired observations")
    for value in (*left, *right):
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("rank correlation requires finite numeric observations")
    if len(left) < 2:
        return None
    a, b = _ranks(left), _ranks(right)
    center = (len(left) + 1) / 2
    numerator = sum((x - center) * (y - center) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - center) ** 2 for x in a) * sum((y - center) ** 2 for y in b))
    return None if denominator == 0 else max(-1.0, min(1.0, numerator / denominator))


@dataclass(frozen=True)
class AnchorPlan:
    key: str
    cycle: int
    proposal: Proposal
    request: EvalRequest
    binding: EvaluationBinding
    proxy_evidence: EvidenceRecord
    mandatory: bool
    role: str = "candidate"
    forced: bool = False


@dataclass(frozen=True)
class ProxyObservation:
    pair_id: str
    mode: str
    rank_correlation: float | None
    valid_pairs: int
    alerts: tuple[str, ...]
    true_improved: bool
    negative_feedback: dict | None


class ProxyValidityController:
    def __init__(self, options, store, *, run_id):
        proxy_options(options)
        _text(run_id, "proxy run identity")
        self._options, self.store, self.run_id = json_copy(options), store, run_id
        self._config_ref = _hash(self._options)
        self._data, self._seq, self._head = {"calls": {}}, 0, None
        self._lock = threading.RLock()

    @property
    def options(self):
        return json_copy(self._options)

    @property
    def anchor_request(self):
        return EvalRequest(**json_copy(self._options["anchor_request"]))

    def _needs(self, cycle, data):
        if type(cycle) is not int or cycle < 0:
            raise ValueError("calibration cycle must be a nonnegative integer")
        if any(call["status"] == "started" for call in data["calls"].values()):
            raise ValueError("unfinished calibration cannot be called again")
        candidates = [call for call in data["calls"].values() if call["intent"]["role"] == "candidate"]
        if candidates and cycle <= max(call["intent"]["cycle"] for call in candidates):
            raise ValueError("calibration cycles cannot be repeated or rolled back")
        return not data["calls"] or self._summary(data)["mode"] == "degraded" \
            or cycle % self._options["every_n_cycles"] == 0

    def needs_anchor(self, cycle):
        with self._lock:
            return self._needs(cycle, self._data)

    def _intent(self, proposal, proxy, cycle, binding, mandatory, role="candidate", forced=False):
        if not isinstance(proposal, Proposal) or not isinstance(binding, EvaluationBinding):
            raise ValueError("calibration plan requires a Proposal and expected producer binding")
        proposal.candidate.validate()
        validate_evidence(proxy)
        source = proxy.eval_result.contract.binding
        if proxy.eval_result.status is not EvalStatus.OK or source.split_id != "dev":
            raise ValueError("proxy monitoring accepts only successful dev evidence")
        if self._options["proxy_metric"] not in proxy.eval_result.metrics:
            raise ValueError("proxy evidence lacks the configured metric")
        if not source.evaluation_context or not binding.evaluation_context \
                or source.evaluation_context == binding.evaluation_context:
            raise ValueError("calibration and proxy require distinct nonempty content bindings")
        if source.candidate_id != proposal.candidate.id \
                or source.artifact_sha256 != hashlib.sha256(proposal.artifact.encode()).hexdigest():
            raise ValueError("proxy evidence differs from the proposed candidate artifact")
        expected = binding_for(proposal, self.anchor_request,
            evaluator_version=binding.evaluator_version, evaluation_context=binding.evaluation_context)
        if binding != expected:
            raise ValueError("anchor binding differs from the exact candidate and calibration request")
        if type(cycle) is not int or cycle < 0 or type(mandatory) is not bool \
                or type(role) is not str or role not in {"candidate", "baseline"} or type(forced) is not bool:
            raise ValueError("invalid calibration plan authority")
        proxy_payload = encode_evidence(proxy)
        return _json({"cycle": cycle, "candidate": asdict(proposal.candidate),
            "artifact_sha256": source.artifact_sha256, "request": asdict(self.anchor_request),
            "binding": asdict(binding), "proxy": proxy_payload,
            "proxy_receipt_ref": _hash({"run_id": self.run_id, "evidence": proxy_payload}),
            "mandatory": mandatory, "role": role, "forced": forced})

    def plan(self, proposal, proxy_evidence, cycle, *, anchor_binding, force=False, role="candidate"):
        with self._lock:
            if type(force) is not bool or type(role) is not str or role not in {"candidate", "baseline"}:
                raise ValueError("invalid calibration scheduling override")
            if role == "baseline":
                force = True
            if force:
                self._validate_forced_cycle(cycle, self._data)
            elif not self._needs(cycle, self._data):
                return None
            mandatory = self._summary(self._data)["mode"] == "degraded"
            intent = self._intent(proposal, proxy_evidence, cycle, anchor_binding, mandatory, role, force)
            key = _hash({"run_id": self.run_id, "config_ref": self._config_ref, "intent": intent})
            return AnchorPlan(key, cycle, copy.deepcopy(proposal), self.anchor_request,
                              copy.deepcopy(anchor_binding), copy.deepcopy(proxy_evidence), mandatory, role, force)

    @staticmethod
    def _validate_forced_cycle(cycle, data):
        if type(cycle) is not int or cycle < 0 or data["calls"] and cycle < max(
                call["intent"]["cycle"] for call in data["calls"].values()):
            raise ValueError("calibration cycles cannot be rolled back")
        if any(call["status"] == "started" for call in data["calls"].values()):
            raise ValueError("unfinished calibration cannot be called again")

    def _plan_intent(self, plan):
        if not isinstance(plan, AnchorPlan) or plan.request != self.anchor_request:
            raise ValueError("anchor plan request was changed")
        intent = self._intent(plan.proposal, plan.proxy_evidence, plan.cycle, plan.binding, plan.mandatory,
                              plan.role, plan.forced)
        if plan.key != _hash({"run_id": self.run_id, "config_ref": self._config_ref, "intent": intent}):
            raise ValueError("anchor plan identity was changed")
        return intent

    def begin(self, plan):
        with self._lock:
            self._commit("begin", {"key": plan.key, "intent": self._plan_intent(plan)})

    def record(self, plan, evidence):
        with self._lock:
            intent = self._plan_intent(plan)
            call = self._data["calls"].get(plan.key)
            if call is None or call["intent"] != intent:
                raise ValueError("anchor evidence has no matching started call")
            validate_evidence(evidence, expected_binding=plan.binding)
            if evidence.eval_result.status is EvalStatus.OK and self._options["true_metric"] not in evidence.eval_result.metrics:
                raise ValueError("calibration evidence lacks the configured true metric")
            payload = encode_evidence(evidence)
            if call["status"] == "recorded":
                if call["anchor"] != payload:
                    raise ValueError("anchor receipt cannot be rebound")
            else:
                self._commit("record", {"key": plan.key, "anchor": payload})
            return self._observation(plan.key)

    def mark_failed(self, plan, reason):
        with self._lock:
            self._plan_intent(plan)
            _text(reason, "calibration failure reason")
            self._commit("failed", {"key": plan.key, "reason": reason})

    def _reduce(self, data, event, payload):
        calls = data["calls"]
        if event == "begin":
            if type(payload) is not dict or set(payload) != {"key", "intent"}:
                raise ValueError("invalid calibration begin journal")
            intent = payload["intent"]
            expected_fields = {"cycle", "candidate", "artifact_sha256", "request", "binding", "proxy", "proxy_receipt_ref", "mandatory", "role", "forced"}
            if type(intent) is not dict or set(intent) != expected_fields:
                raise ValueError("invalid calibration intent")
            if type(intent["forced"]) is not bool or type(intent["mandatory"]) is not bool \
                    or type(intent["role"]) is not str or intent["role"] not in {"candidate", "baseline"} \
                    or intent["role"] == "baseline" and not intent["forced"]:
                raise ValueError("invalid calibration scheduling authority")
            if intent["forced"]:
                self._validate_forced_cycle(intent["cycle"], data)
            if payload["key"] in calls or not intent["forced"] and not self._needs(intent["cycle"], data) \
                    or intent["mandatory"] != (self._summary(data)["mode"] == "degraded"):
                raise ValueError("calibration intent is reused or changes its scheduled authority")
            if intent["role"] == "candidate" and any(call["intent"]["cycle"] == intent["cycle"]
                    and call["intent"]["role"] == "candidate" for call in calls.values()):
                raise ValueError("a cycle may contribute only one proxy candidate sample")
            proxy = decode_evidence(intent["proxy"])
            binding = dict(intent["binding"])
            if binding.get("seed_set") is not None:
                binding["seed_set"] = tuple(binding["seed_set"])
            parsed = EvaluationBinding(**binding)
            # Rebuild every receipt authority without needing the original code.
            source = proxy.eval_result.contract.binding
            from core.executor.types import Candidate
            candidate = Candidate(**intent["candidate"])
            candidate.validate()
            for previous in calls.values():
                if previous["intent"]["candidate"]["id"] == candidate.id:
                    if previous["intent"]["candidate"] != intent["candidate"] \
                            or previous["intent"]["artifact_sha256"] != intent["artifact_sha256"]:
                        raise ValueError("calibration candidate identity cannot be rebound")
                    if intent["role"] == previous["intent"]["role"] == "candidate":
                        raise ValueError("the same candidate cannot contribute repeated rank samples")
            if source.candidate_id != candidate.id or source.artifact_sha256 != intent["artifact_sha256"] \
                    or parsed.candidate_id != candidate.id or parsed.artifact_sha256 != source.artifact_sha256 \
                    or intent["request"] != asdict(self.anchor_request) \
                    or parsed.request_sha256 != request_digest(self.anchor_request) \
                    or parsed.split_id != "calibration" or parsed.fidelity != self.anchor_request.fidelity \
                    or parsed.seed_set != (tuple(self.anchor_request.seed_set) if self.anchor_request.seed_set is not None else None) \
                    or not source.evaluation_context or not parsed.evaluation_context \
                    or parsed.evaluation_context == source.evaluation_context \
                    or source.split_id != "dev" or proxy.eval_result.status is not EvalStatus.OK \
                    or self._options["proxy_metric"] not in proxy.eval_result.metrics \
                    or intent["proxy_receipt_ref"] != _hash({"run_id": self.run_id, "evidence": intent["proxy"]}) \
                    or payload["key"] != _hash({"run_id": self.run_id, "config_ref": self._config_ref, "intent": intent}):
                raise ValueError("calibration intent binding mismatch")
            # Canonical binding validation also rejects malformed digest/version.
            from core.composition.evaluation import _binding
            _binding(parsed)
            calls[payload["key"]] = {"intent": intent, "status": "started"}
            return
        fields = {"record": {"key", "anchor"}, "failed": {"key", "reason"}}
        if event not in fields or type(payload) is not dict or set(payload) != fields[event]:
            raise ValueError("invalid calibration journal event")
        call = calls.get(payload["key"])
        if call is None or call["status"] != "started":
            raise ValueError("calibration result requires an unfinished original call")
        if event == "failed":
            _text(payload["reason"], "calibration failure reason")
            call.update(status="failed", reason=payload["reason"])
            return
        anchor = decode_evidence(payload["anchor"])
        if _json(asdict(anchor.eval_result.contract.binding)) != call["intent"]["binding"]:
            raise ValueError("calibration result binding mismatch")
        if anchor.eval_result.status is EvalStatus.OK and self._options["true_metric"] not in anchor.eval_result.metrics:
            raise ValueError("calibration result lacks the true metric")
        call.update(status="recorded", anchor=payload["anchor"])

    def _commit(self, event, payload):
        payload = json_copy(payload)
        updated = copy.deepcopy(self._data)
        self._reduce(updated, event, payload)
        row = {"schema_version": 1, "seq": self._seq + 1, "previous": self._head,
               "run_id": self.run_id, "config_ref": self._config_ref, "event": event, "data": payload}
        row["event_ref"] = _hash(row)
        self.store.append(JOURNAL_KIND, row)
        self._data, self._seq, self._head = updated, row["seq"], row["event_ref"]

    def _oriented(self, value, kind):
        number = Decimal(str(value))
        return number if self._options[kind + "_direction"] == "maximize" else number.copy_negate()

    def _rank_value(self, value, kind):
        return value if self._options[kind + "_direction"] == "maximize" else -value

    def _summary(self, data):
        pairs, comparable_bases, alerts, basis_ref, observations = [], {}, [], None, {}
        for key, call in data["calls"].items():
            if call["status"] == "started":
                continue
            if call["status"] == "failed" or call["anchor"]["evidence"]["eval_result"]["status"] != "ok":
                alerts.append({"pair_id": key, "rule": "anchor_failed"})
                observations[key] = {"true_improved": False, "negative_feedback": None}
                continue
            intent, anchor = call["intent"], call["anchor"]
            proxy_binding = intent["proxy"]["evidence"]["eval_result"]["contract"]["binding"]
            signature = {"proxy": {name: value for name, value in proxy_binding.items()
                                  if name not in {"candidate_id", "artifact_sha256"}},
                         "anchor": {name: value for name, value in intent["binding"].items()
                                   if name not in {"candidate_id", "artifact_sha256"}}}
            current_basis = _hash(signature)
            if intent["role"] == "candidate" and current_basis != basis_ref:
                pairs, basis_ref = [], current_basis
            comparables = comparable_bases.setdefault(current_basis, [])
            proxy_score = intent["proxy"]["evidence"]["eval_result"]["metrics"][self._options["proxy_metric"]]
            true_score = anchor["evidence"]["eval_result"]["metrics"][self._options["true_metric"]]
            anchor_ref = _hash({"run_id": self.run_id, "evidence": anchor})
            pair = {"pair_id": key, "candidate_id": intent["candidate"]["id"],
                    "proxy_score": proxy_score, "true_score": true_score,
                    "proxy_receipt_ref": intent["proxy_receipt_ref"], "anchor_receipt_ref": anchor_ref}
            best = max(comparables, key=lambda row: self._oriented(row["true_score"], "true")) if comparables else None
            true_improved = best is None or self._oriented(true_score, "true") > self._oriented(best["true_score"], "true")
            feedback = None
            if intent["role"] == "candidate" and best is not None and self._oriented(proxy_score, "proxy") > self._oriented(best["proxy_score"], "proxy") \
                    and self._oriented(true_score, "true") < self._oriented(best["true_score"], "true"):
                alerts.append({"pair_id": key, "rule": "proxy_improved_true_regressed"})
                feedback = {"schema_version": 1, "kind": "proxy_improved_true_regressed",
                    "candidate_id": pair["candidate_id"], "pair_id": key, "basis_ref": current_basis,
                    "proxy_metric": self._options["proxy_metric"], "true_metric": self._options["true_metric"],
                    "proxy_direction": self._options["proxy_direction"], "true_direction": self._options["true_direction"],
                    "current": copy.deepcopy(pair), "baseline": copy.deepcopy(best),
                    "comparison": "previous_comparable_true_best",
                    "statistical": False}
            comparables.append(pair)
            if intent["role"] == "candidate":
                pairs.append(pair)
            window = pairs[-self._options["window"]:]
            correlation = spearman_rank_correlation(
                [self._rank_value(row["proxy_score"], "proxy") for row in window],
                [self._rank_value(row["true_score"], "true") for row in window])
            if intent["role"] == "candidate" and len(window) >= self._options["min_pairs"]:
                if correlation is None:
                    alerts.append({"pair_id": key, "rule": "rank_correlation_undefined"})
                elif correlation < self._options["min_rank_correlation"]:
                    alerts.append({"pair_id": key, "rule": "rank_correlation_below_threshold"})
            observations[key] = {"true_improved": true_improved, "negative_feedback": feedback}
        window = pairs[-self._options["window"]:]
        correlation = spearman_rank_correlation(
            [self._rank_value(row["proxy_score"], "proxy") for row in window],
            [self._rank_value(row["true_score"], "true") for row in window])
        mode = "degraded" if alerts else "monitoring" if len(window) >= self._options["min_pairs"] else "warmup"
        return {"mode": mode, "rank_correlation": correlation, "valid_pairs": len(window),
                "basis_ref": basis_ref, "alerts": alerts, "observations": observations,
                "pairs": pairs, "statistical": False,
                "requires_anchor_every_candidate": mode == "degraded",
                "advancement_rule": "true_best_only" if mode == "degraded" else "configured_admission"}

    def _observation(self, key):
        summary = self._summary(self._data)
        details = summary["observations"][key]
        return ProxyObservation(key, summary["mode"], summary["rank_correlation"], summary["valid_pairs"],
            tuple(alert["rule"] for alert in summary["alerts"] if alert["pair_id"] == key),
            details["true_improved"], copy.deepcopy(details["negative_feedback"]))

    def observation(self, pair_id):
        with self._lock:
            if pair_id not in self._summary(self._data)["observations"]:
                raise ValueError("unknown or unfinished calibration observation")
            return self._observation(pair_id)

    def cached_anchor(self, proposal, proxy_evidence, *, anchor_binding):
        """Return only an exact successful pair, detached from durable state."""
        with self._lock:
            intent = self._intent(proposal, proxy_evidence, 0, anchor_binding, False)
            for call in reversed(tuple(self._data["calls"].values())):
                if call["status"] == "recorded" and call["anchor"]["evidence"]["eval_result"]["status"] == "ok" \
                        and call["intent"]["binding"] == intent["binding"] \
                        and call["intent"]["proxy_receipt_ref"] == intent["proxy_receipt_ref"]:
                    return decode_evidence(copy.deepcopy(call["anchor"]))
            return None

    def allows_advancement(self, pair_id):
        """Strict true-best check, including baselines recorded after a candidate."""
        with self._lock:
            call = self._data["calls"].get(pair_id)
            if call is None or call["status"] != "recorded" or call["intent"]["role"] != "candidate" \
                    or call["anchor"]["evidence"]["eval_result"]["status"] != "ok":
                return False
            def basis(item):
                return {key: value for key, value in item["intent"]["binding"].items()
                        if key not in {"candidate_id", "artifact_sha256"}}
            score = self._oriented(call["anchor"]["evidence"]["eval_result"]["metrics"][self._options["true_metric"]], "true")
            for key, other in self._data["calls"].items():
                if key == pair_id or other["status"] != "recorded" \
                        or other["anchor"]["evidence"]["eval_result"]["status"] != "ok" or basis(other) != basis(call):
                    continue
                if score <= self._oriented(other["anchor"]["evidence"]["eval_result"]["metrics"][self._options["true_metric"]], "true"):
                    return False
            return True

    def validate_feedback(self, feedback):
        with self._lock:
            supplied = json_copy(feedback, label="proxy negative feedback")
            if type(supplied) is not dict or supplied.get("pair_id") not in self._summary(self._data)["observations"]:
                raise ValueError("feedback lacks authoritative calibration receipts")
            expected = self._observation(supplied["pair_id"]).negative_feedback
            if expected is None or supplied != expected:
                raise ValueError("feedback differs from the original paired calibration evidence")
            return copy.deepcopy(expected)

    def feedback_records(self, feedback):
        with self._lock:
            checked = self.validate_feedback(feedback)
            result = {}
            for role in ("current", "baseline"):
                call = self._data["calls"][checked[role]["pair_id"]]
                result[role + "_proxy"] = copy.deepcopy(call["intent"]["proxy"])
                result[role + "_anchor"] = copy.deepcopy(call["anchor"])
            return result

    def state(self):
        with self._lock:
            summary = self._summary(self._data)
            summary.pop("observations")
            summary["open_calls"] = [key for key, call in self._data["calls"].items() if call["status"] == "started"]
            return copy.deepcopy(summary)

    def checkpoint_state(self):
        with self._lock:
            return {"schema_version": 1, "run_id": self.run_id, "config_ref": self._config_ref,
                    "seq": self._seq, "head": self._head, "state": self.state()}

    def _rebuild(self):
        data, sequence, head = {"calls": {}}, 0, None
        for row in self.store.read(JOURNAL_KIND):
            event = json_copy(row["payload"])
            if type(event) is not dict or set(event) != {"schema_version", "seq", "previous", "run_id", "config_ref", "event", "data", "event_ref"} \
                    or type(event["schema_version"]) is not int or event["schema_version"] != 1 \
                    or type(event["seq"]) is not int or event["seq"] != sequence + 1 \
                    or event["previous"] != head or event["run_id"] != self.run_id or event["config_ref"] != self._config_ref \
                    or event["event_ref"] != _hash({key: value for key, value in event.items() if key != "event_ref"}):
                raise ValueError("proxy journal configuration, run, sequence or integrity mismatch")
            self._reduce(data, event["event"], event["data"])
            sequence, head = event["seq"], event["event_ref"]
        return data, sequence, head

    def restore_from_journal(self):
        with self._lock:
            if self._seq or self._data != {"calls": {}}:
                raise ValueError("proxy restore requires a fresh controller")
            self._data, self._seq, self._head = self._rebuild()

    def restore_state(self, checkpoint):
        with self._lock:
            if self._seq or self._data != {"calls": {}}:
                raise ValueError("proxy restore requires a fresh controller")
            previous = self._data, self._seq, self._head
            self._data, self._seq, self._head = self._rebuild()
            try:
                if checkpoint != self.checkpoint_state():
                    raise ValueError("proxy checkpoint differs from the durable journal")
            except Exception:
                self._data, self._seq, self._head = previous
                raise
