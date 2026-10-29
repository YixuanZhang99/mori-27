"""Read-only C1/C2 governance reconciliation over append-only run evidence."""
from __future__ import annotations

import math

from core.budget.types import COST_ACCOUNTS
from core.eval.gate import stop_action, validate_receipt_evidence
from core.x1.checkpoint import payload_digest


def _valid_amount(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) \
        and math.isfinite(value) and value >= 0


def _ledger_audit(store, summary: dict) -> dict:
    totals = {account: 0.0 for account in COST_ACCOUNTS}
    reserves: dict[str, str] = {}
    reserve_amounts: dict[str, float] = {}
    settled: dict[str, str] = {}
    expected_deltas: dict[str, float] = {}
    reconciled: set[str] = set()
    errors: list[str] = []
    unmapped = 0
    settlement_count = 0
    for record in store.read("ledger"):
        entry = record.get("payload", {})
        account = entry.get("account")
        intent_id = entry.get("intent_id")
        kind = entry.get("entry_kind")
        if account not in COST_ACCOUNTS or not isinstance(intent_id, str) or not intent_id \
                or entry.get("unit", "token") != "token":
            errors.append("invalid ledger account, intent or unit")
            continue
        if kind == "reserve":
            if intent_id in reserves or intent_id in settled \
                    or not _valid_amount(entry.get("reserved")) \
                    or entry.get("reserved") <= 0:
                errors.append(f"invalid reserve lifecycle: {intent_id}")
            else:
                reserves[intent_id] = account
                reserve_amounts[intent_id] = entry["reserved"]
        elif kind == "reserve_released":
            if reserves.get(intent_id) != account:
                errors.append(f"release without matching open reserve: {intent_id}")
            else:
                reserves.pop(intent_id)
                reserve_amounts.pop(intent_id)
        elif kind == "settle":
            settlement_count += 1
            actual = entry.get("settled")
            if not _valid_amount(actual):
                errors.append(f"invalid settlement amount: {intent_id}")
                continue
            totals[account] += actual
            if reserves.get(intent_id) != account:
                unmapped += 1
            else:
                reserves.pop(intent_id)
                expected_deltas[intent_id] = reserve_amounts.pop(intent_id) - actual
                settled[intent_id] = account
        elif kind == "reconcile_delta":
            delta = entry.get("settled")
            if settled.get(intent_id) != account or intent_id in reconciled \
                    or isinstance(delta, bool) or not isinstance(delta, (int, float)) \
                    or not math.isfinite(delta) \
                    or not math.isclose(delta, expected_deltas[intent_id],
                                        rel_tol=0.0, abs_tol=1e-9):
                errors.append(f"invalid or duplicate reconcile delta: {intent_id}")
            else:
                reconciled.add(intent_id)
        else:
            errors.append(f"unsupported ledger entry: {kind}")
    reported = summary.get("spent", {}) if isinstance(summary, dict) else {}
    account_coverage = set(reported) == set(COST_ACCOUNTS)
    summary_totals = {}
    numeric_summary = account_coverage
    for account in COST_ACCOUNTS:
        value = reported.get(account)
        if not _valid_amount(value):
            numeric_summary = False
        else:
            summary_totals[account] = value
    zero_gap = numeric_summary and all(
        math.isclose(totals[account], summary_totals[account],
                     rel_tol=0.0, abs_tol=1e-9) for account in COST_ACCOUNTS)
    passed = not errors and not unmapped and not reserves and zero_gap
    return {"passed": passed, "account_coverage": account_coverage and numeric_summary,
            "zero_gap": zero_gap, "settlement_count": settlement_count,
            "settled_intent_count": len(settled), "open_reserve_count": len(reserves),
            "unmapped_settlement_count": unmapped,
            "settled_by_account": totals, "reported_by_account": summary_totals,
            "errors": errors}


def _receipt_audit(store, accepted_candidate_ids: list[str]) -> dict:
    gated: dict[str, str] = {}
    receipts: dict[str, dict] = {}
    admissions: dict[str, tuple[str, bool]] = {}
    gate_contexts: list[dict] = []
    errors: list[str] = []
    for record in store.read("gate_evidence"):
        payload = record.get("payload", {})
        if payload.get("transition") != "verdict":
            continue
        candidate_id, receipt_id = payload.get("candidate_id"), payload.get("receipt_id")
        gate_contexts.append(payload)
        if not candidate_id or not receipt_id or (
                candidate_id in gated and gated[candidate_id] != receipt_id):
            errors.append(f"invalid or conflicting gate evidence: {candidate_id}")
        else:
            gated[candidate_id] = receipt_id
    for record in store.read("receipt"):
        payload = record.get("payload", {})
        receipt_id = payload.get("receipt_id")
        if not receipt_id or (receipt_id in receipts and receipts[receipt_id] != payload):
            errors.append(f"invalid or conflicting receipt: {receipt_id}")
        else:
            receipts[receipt_id] = payload
    referenced_receipts = set(gated.values())
    for receipt_id in receipts:
        if receipt_id not in referenced_receipts:
            errors.append(f"receipt without gate evidence: {receipt_id}")
    for evidence in gate_contexts:
        try:
            validate_receipt_evidence(receipts.get(evidence.get("receipt_id")), evidence)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            errors.append(f"unverifiable receipt decision context: {error}")
    for record in store.read("admission_receipt"):
        payload = record.get("payload", {})
        candidate_id, receipt_id = payload.get("candidate_id"), payload.get("receipt_id")
        admit = payload.get("admit")
        if not candidate_id or not receipt_id or not isinstance(admit, bool) or (
                candidate_id in admissions and admissions[candidate_id] != (receipt_id, admit)):
            errors.append(f"invalid or conflicting admission receipt: {candidate_id}")
        else:
            admissions[candidate_id] = (receipt_id, admit)
    for candidate_id, receipt_id in gated.items():
        receipt = receipts.get(receipt_id)
        kind = (receipt or {}).get("verdict", {}).get("kind")
        if kind not in {"ACCEPT", "REJECT"}:
            errors.append(f"gate has no valid Receipt: {candidate_id}")
            continue
        admission = admissions.get(candidate_id)
        if admission is None:
            errors.append(f"gate has no admission decision: {candidate_id}")
        elif admission != (receipt_id, kind == "ACCEPT"):
            errors.append(f"admission does not match Receipt: {candidate_id}")
    for candidate_id in admissions.keys() - gated.keys():
        errors.append(f"admission without gate evidence: {candidate_id}")
    accepted = set(accepted_candidate_ids)
    accepted_coverage = all(
        candidate_id in gated and candidate_id in admissions
        and admissions[candidate_id][1] for candidate_id in accepted)
    recorded_accepted = {candidate_id for candidate_id, (_, admit) in admissions.items() if admit}
    if recorded_accepted != accepted:
        errors.append("accepted candidate projection differs from admission evidence")
    passed = not errors and accepted_coverage
    return {"passed": passed, "accepted_receipt_coverage": accepted_coverage,
            "gated_candidate_count": len(gated), "receipt_count": len(receipts),
            "admission_decision_count": len(admissions),
            "accepted_decision_count": len(recorded_accepted),
            "rejected_decision_count": sum(not admit for _, admit in admissions.values()),
            "errors": errors}


def _stop_audit(store) -> dict:
    errors: list[str] = []
    count = 0
    for record in store.read("stop_action"):
        payload = record.get("payload", {})
        count += 1
        try:
            expected = stop_action(payload.get("verdict_kind"), payload.get("scope"))
        except (KeyError, TypeError):
            expected = None
        if expected != "stop" or payload.get("action") != expected:
            errors.append(f"non-reproducible stop action: {payload}")
    return {"passed": not errors, "table_driven_stop_count": count,
            "replayed_stop_count": count - len(errors), "errors": errors}


def _baseline_audit(store, ledger: dict) -> dict:
    errors: list[str] = []
    baseline_ids: set[str] = set()
    baseline_count = 0
    for record in store.read("baseline"):
        payload = record.get("payload", {})
        candidate_id = payload.get("candidate_id")
        score = payload.get("score")
        baseline_count += 1
        if not candidate_id or isinstance(score, bool) \
                or not isinstance(score, (int, float)) or not math.isfinite(score):
            errors.append(f"invalid baseline evidence: {candidate_id}")
        else:
            baseline_ids.add(candidate_id)
    frontier_ids = {record.get("payload", {}).get("target")
                    for record in store.read("state_mutation")
                    if record.get("payload", {}).get("op") == "add_node"}
    leaked = sorted(baseline_ids & frontier_ids)
    if leaked:
        errors.append("resident baseline entered the research frontier")
    control_spent = ledger["settled_by_account"].get("control", 0.0)
    passed = not errors and baseline_count > 0 and control_spent > 0
    return {"passed": passed, "baseline_count": baseline_count,
            "unique_baseline_count": len(baseline_ids),
            "control_spent": control_spent, "baseline_in_frontier": bool(leaked),
            "errors": errors}


def receipt_chain(store) -> list[dict]:
    """Bind gate order to the actual Receipt payloads for C4 comparison."""
    receipts = {record.get("payload", {}).get("receipt_id"): record.get("payload", {})
                for record in store.read("receipt")}
    chain = []
    for record in store.read("gate_evidence"):
        gate = record.get("payload", {})
        if gate.get("transition") != "verdict":
            continue
        receipt_id = gate.get("receipt_id")
        receipt = receipts.get(receipt_id)
        chain.append({"candidate_id": gate.get("candidate_id"),
                      "receipt_id": receipt_id, "rule_id": gate.get("rule_id"),
                      "receipt": receipt if receipt is not None else {"missing": True}})
    return chain


def receipt_chain_sha256(store) -> str:
    return payload_digest(receipt_chain(store))


def audit_governance(store, ledger_summary: dict,
                     accepted_candidate_ids: list[str]) -> dict:
    """Recompute C1/C2/C3 from evidence; never trust a cached pass flag."""
    ledger = _ledger_audit(store, ledger_summary)
    receipts = _receipt_audit(store, accepted_candidate_ids)
    stops = _stop_audit(store)
    baseline = _baseline_audit(store, ledger)
    passed = ledger["passed"] and receipts["passed"] and stops["passed"]
    return {"passed": passed, "formal_pass": passed and baseline["passed"],
            "ledger_reconciliation": ledger, "receipt_coverage": receipts,
            "stop_action_replay": stops, "baseline_residence": baseline}
