"""Offline currency authority proofs, with no ledger or provider capability.

Proofs contain the private full campaign prefix, including other runs. They must
not enter model context or lane views. A proof establishes consistency at its
recorded head; only a separately trusted head can reject coherent rollback.
This module does not certify physical receipts, HTTP absence before recording,
provider invoices, or the current live campaign balance.
"""
from __future__ import annotations

import json

from .cny_budget import (
    _audit_run, _call_bound, _hash, _head_anchor, _integer, _json,
    _plan_ref, _reduce_history, _sha,
)


def _verified(evidence, *, expected_run_id=None, expected_plan_ref=None,
              expected_policy_sha256=None, expected_head=None):
    if (type(evidence) is not dict or set(evidence) != {
            "schema_version", "run_id", "plan_ref", "policy_json", "policy_sha256",
            "events", "journal_head"} or type(evidence["schema_version"]) is not int
            or evidence["schema_version"] != 1):
        raise ValueError("currency evidence envelope is unsupported or damaged")
    _sha(evidence["run_id"])
    _plan_ref(evidence["plan_ref"])
    _sha(evidence["policy_sha256"])
    _head_anchor(evidence["journal_head"])
    if type(evidence["policy_json"]) is not str or type(evidence["events"]) is not list:
        raise ValueError("currency evidence requires exact policy and full event prefix")
    events = []
    for row in evidence["events"]:
        if type(row) is not dict or set(row) != {"seq", "payload", "sha256"}:
            raise ValueError("currency evidence event shape is invalid")
        _integer(row["seq"], "event sequence", 1)
        _sha(row["sha256"])
        if type(row["payload"]) is not str:
            raise ValueError("currency evidence event requires exact stored payload")
        events.append((row["seq"], row["payload"], row["sha256"]))
    try:
        policy, state = _reduce_history([(evidence["policy_json"],)], events,
            [(evidence["journal_head"]["seq"], evidence["journal_head"]["sha256"])])
        if _hash(policy) != evidence["policy_sha256"]:
            raise ValueError("currency evidence policy hash differs from policy")
        audit = _audit_run(policy, state, evidence["run_id"], evidence["plan_ref"])
    except (json.JSONDecodeError, KeyError, TypeError, OverflowError) as error:
        raise ValueError(f"currency evidence integrity failed ({type(error).__name__})") from None
    for name, expected in (("run_id", expected_run_id), ("plan_ref", expected_plan_ref),
                           ("policy_sha256", expected_policy_sha256), ("journal_head", expected_head)):
        if expected is not None:
            if name == "journal_head":
                _head_anchor(expected)
            elif name == "plan_ref":
                _plan_ref(expected)
            else:
                _sha(expected)
            if evidence[name] != expected:
                raise ValueError(f"currency evidence {name} differs from trusted anchor")
    return policy, audit


def verify_governance_evidence(evidence, *, expected_run_id=None, expected_plan_ref=None,
                               expected_policy_sha256=None, expected_head=None):
    """Recompute a recorded run audit, optionally binding trusted external anchors.

    No caller-supplied totals are accepted. All legacy and governed events are
    reduced by the same semantic rules as the live authority. A valid historical
    prefix remains valid unless a newer trusted head is supplied explicitly.
    """
    return _verified(evidence, expected_run_id=expected_run_id,
        expected_plan_ref=expected_plan_ref, expected_policy_sha256=expected_policy_sha256,
        expected_head=expected_head)[1]


class RecordedCurrencyView:
    """Detached, read-only view of one verified run at one recorded journal head."""

    def __init__(self, evidence, *, expected_run_id=None, expected_plan_ref=None,
                 expected_policy_sha256=None, expected_head=None):
        # Validate before copying, so non-JSON Python objects cannot be coerced
        # into acceptable evidence through serialization.
        policy, audit = _verified(evidence, expected_run_id=expected_run_id,
            expected_plan_ref=expected_plan_ref, expected_policy_sha256=expected_policy_sha256,
            expected_head=expected_head)
        self._evidence = _json(evidence)
        self._policy = _json(policy)
        self._audit = _json(audit)

    def manifest_binding(self):
        policy = json.loads(self._policy)
        return {**policy, "policy_sha256": _hash(policy)}

    def quote_call(self, output_allowance):
        _integer(output_allowance, "output allowance", 1)
        policy = json.loads(self._policy)
        return _call_bound(policy, {"schema_version": 1, "output_allowance": output_allowance,
            "reserved_micro_cny": policy["context_tokens"] * 2 + output_allowance * 8})

    def audit_run(self, run_id, plan_ref):
        _sha(run_id)
        _plan_ref(plan_ref)
        audit = json.loads(self._audit)
        if run_id != audit["run_id"] or plan_ref != audit["plan_ref"]:
            raise ValueError("recorded currency view is bound to another run or plan")
        return audit

    def export_governance_evidence(self, run_id, plan_ref):
        self.audit_run(run_id, plan_ref)
        return json.loads(self._evidence)

    def _governance(self):
        evidence = json.loads(self._evidence)
        events = [(row['seq'], row['payload'], row['sha256']) for row in evidence['events']]
        _, state = _reduce_history([(evidence['policy_json'],)], events,
            [(evidence['journal_head']['seq'], evidence['journal_head']['sha256'])])
        return state['governance']

    def cell_deadline_claim(self, cell_id):
        from .cny_budget import _identifier
        _identifier(cell_id, 'cell identity')
        claim = self._governance()['cell_claims'].get(cell_id)
        return dict(claim) if claim is not None else None

    def run_deadline_binding(self, run_id):
        _sha(run_id)
        if run_id != json.loads(self._audit)['run_id']:
            raise ValueError('recorded currency view belongs to another run')
        binding = self._governance()['deadline_bindings'].get(run_id)
        return dict(binding) if binding is not None else None

    def response_eligibility(self, call_id):
        from .cny_budget import _identifier
        _identifier(call_id, 'call identity')
        value = self._governance()['response_eligibility'].get(call_id)
        if value is not None and value['run_id'] != json.loads(self._audit)['run_id']:
            raise ValueError('recorded eligibility belongs to another run')
        return dict(value) if value is not None else None

    def evaluation_eligibility(self, run_id, intent_id):
        _sha(intent_id)
        self.run_deadline_binding(run_id)
        value = self._governance()['evaluation_eligibility'].get((run_id, intent_id))
        return dict(value) if value is not None else None

    def cycle_eligibility(self, run_id, cycle_key):
        _sha(cycle_key)
        self.run_deadline_binding(run_id)
        value = self._governance()['cycle_eligibility'].get((run_id, cycle_key))
        return dict(value) if value is not None else None
