"""Provider receipts linked to physical settlement hashes, without dispatch."""
from __future__ import annotations

import re

from core.x1.checkpoint import payload_digest


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def invocation_records(store):
    """Return exact ordered receipt pairs grouped by their physical intent."""
    result, pending, ordinals = {}, None, {}
    for row in store.read():
        kind, data = row["kind"], row["payload"]
        if kind == "composed_provider_started":
            if pending is not None or set(data) != {"binding", "request_sha256", "invocation"}:
                raise ValueError("governed provider receipt start is missing or overlapping")
            inv = data["invocation"]
            fields = {"intent_id", "fingerprint", "lane", "slot_id", "run_id", "adapter_binding_sha256", "ordinal"}
            if type(inv) is dict and type(inv.get("schema_version")) is int and inv["schema_version"] == 2:
                from core.composition.external_provider import GovernedCallContext
                fields |= {"schema_version", "external_context"}
                context = GovernedCallContext.from_dict(inv.get("external_context"))
                if context.intent_id != inv.get("intent_id") or context.physical_fingerprint != inv.get("fingerprint") or \
                        context.logical_run_id != inv.get("run_id") or context.lane != inv.get("lane") or \
                        context.slot_id != inv.get("slot_id") or context.ordinal != inv.get("ordinal") or \
                        context.adapter_binding_sha256 != inv.get("adapter_binding_sha256") or \
                        context.argument_sha256 != data.get("request_sha256"):
                    raise ValueError("external provider context differs from its physical invocation")
            if type(inv) is not dict or set(inv) != fields or inv["lane"] not in {"main", "control"}:
                raise ValueError("governed provider invocation identity is invalid")
            identifier = inv["intent_id"]
            if type(identifier) is not str or type(inv["ordinal"]) is not int or \
                    inv["ordinal"] != ordinals.get(identifier, 0) or not _sha(data["request_sha256"]):
                raise ValueError("governed provider ordinal or request binding is invalid")
            expected = payload_digest({"request_sha256": data["request_sha256"], "invocation": inv})
            if data["binding"] != expected:
                raise ValueError("governed provider request differs from its binding")
            ordinals[identifier] = inv["ordinal"] + 1
            result.setdefault(identifier, []).append(row)
            pending = data
        elif kind == "composed_provider_completed":
            if pending is None or data.get("binding") != pending["binding"] or \
                    set(data) - {"binding", "result", "tokens", "state", "outcome", "observed_binding_sha256"} or \
                    not {"binding", "result", "tokens", "state", "observed_binding_sha256"} <= set(data):
                raise ValueError("governed provider completion has no matching authoritative start")
            if type(data["tokens"]) is not int or data["tokens"] < 0 or type(data["result"]) is not str or \
                    data.get("outcome", "returned") not in {"returned", "budget_exhausted", "failed"} or \
                    data["observed_binding_sha256"] is not None and not _sha(data["observed_binding_sha256"]):
                raise ValueError("governed provider completion contains invalid cost or outcome")
            result[pending["invocation"]["intent_id"]].append(row)
            pending = None
    return result


def evidence_reference(store, intent_id):
    return "sha256:" + payload_digest(invocation_records(store).get(intent_id, []))


def audit_provider_receipts(runtime, sessions, main_binding):
    records = invocation_records(runtime.store)
    operations = runtime.budget._rebuild()[0]["operations"]
    for identifier, operation in operations.items():
        intent = operation["intent"]
        receipt_rows = records.pop(identifier, [])
        binding = main_binding if intent["lane"] == "main" else sessions[intent["control_slot"]]["governance_binding"]
        total = 0
        for row in receipt_rows:
            data = row["payload"]
            if row["kind"] == "composed_provider_started":
                inv = data["invocation"]
                if inv["run_id"] != runtime._logical_run_id or inv["fingerprint"] != operation["fingerprint"] or \
                        inv["lane"] != intent["lane"] or inv["slot_id"] != intent["control_slot"] or \
                        inv["adapter_binding_sha256"] != payload_digest(binding):
                    raise ValueError("governed provider receipt differs from physical authority")
                if inv.get("schema_version") == 2:
                    context = inv["external_context"]
                    phase = intent["operation"] if intent["operation"] in {"operator", "planning"} else "evaluation"
                    if context["candidate_id"] != intent["candidate"]["id"] or context["account"] != intent["account"] or \
                            context["operation"] != intent["operation"] or context["phase"] != phase or \
                            context["physical_plan_ref"] != runtime.governed.plan["plan_ref"]:
                        raise ValueError("external provider context differs from physical intent")
            else:
                total += data["tokens"]
        if operation["status"] == "settled":
            if receipt_rows and receipt_rows[-1]["kind"] != "composed_provider_completed":
                raise ValueError("settled governed invocation has an unresolved provider call")
            if operation["provider_evidence_ref"] != "sha256:" + payload_digest(receipt_rows):
                raise ValueError("governed provider receipt coverage differs from sealed settlement")
            if total > operation["actual_costs"].get("token", 0):
                raise ValueError("governed provider charges exceed physical settlement")
    if records:
        raise ValueError("governed provider receipt has no physical reservation")
