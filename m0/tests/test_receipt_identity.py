"""Bind admission receipts to complete, independently reproducible decisions."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.eval.gate import AdmissionGate, validate_receipt_evidence
from core.eval.types import EvalResult, ItemResult
from core.x1.audit import _receipt_audit
from core.x1.store import AppendOnlyStore


CONTEXT = "sha256:" + "a" * 64


def evaluation(candidate_id="candidate", verdicts=(1, 0), **kwargs):
    values = dict(candidate_id=candidate_id, head_sha="head-" + candidate_id,
                  items=[ItemResult("a", verdicts[0]), ItemResult("b", verdicts[1])],
                  evaluator_version="eval-v1", evaluation_context=CONTEXT)
    values.update(kwargs)
    return EvalResult(**values)


def decision(candidate=None, incumbent=None, **kwargs):
    return AdmissionGate(None, kwargs.pop("noise_floor", 0)).evaluate(
        candidate or evaluation(), incumbent, **kwargs)


def canonical_id(context):
    data = json.dumps(context, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_same_candidate_different_baseline_cannot_share_accept_and_reject_receipt():
    candidate = evaluation()
    accepted, _ = decision(candidate, evaluation("baseline", (0, 0)))
    rejected, _ = decision(candidate, evaluation("baseline", (1, 1)))
    assert accepted.verdict.kind == "ACCEPT"
    assert rejected.verdict.kind == "REJECT"
    assert accepted.receipt_id != rejected.receipt_id
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", accepted.receipt_id)


def test_reordered_binary_evidence_has_identical_receipt_and_snapshot():
    candidate, incumbent = evaluation(), evaluation("baseline", (0, 0))
    original = decision(candidate, incumbent)
    candidate.items.reverse()
    incumbent.items.reverse()
    reordered = decision(candidate, incumbent)
    assert reordered == original
    receipt, evidence = reordered
    assert receipt.receipt_id == canonical_id(evidence.decision_context)
    assert receipt.evidence_refs == [receipt.receipt_id]
    validate_receipt_evidence(asdict(receipt), asdict(evidence))


@pytest.mark.parametrize("field,value", [
    ("candidate_id", "another-candidate"), ("head_sha", "another-head"),
    ("evaluator_version", "eval-v2"),
    ("evaluation_context", "sha256:" + "b" * 64),
    ("items", [ItemResult("a", 0), ItemResult("b", 0)]),
    ("items", [ItemResult("renamed-a", 1), ItemResult("b", 0)]),
])
def test_every_candidate_identity_and_evidence_field_is_bound(field, value):
    original, _ = decision()
    changed, evidence = decision(replace(evaluation(), **{field: value}))
    assert changed.verdict == original.verdict  # genesis still accepts
    assert changed.receipt_id != original.receipt_id
    validate_receipt_evidence(asdict(changed), asdict(evidence))


@pytest.mark.parametrize("field,value", [
    ("candidate_id", "another-baseline"), ("head_sha", "another-head"),
    ("evaluator_version", "eval-v2"),
    ("evaluation_context", "sha256:" + "b" * 64),
    ("items", [ItemResult("a", 0), ItemResult("b", 1)]),
])
def test_incumbent_identity_and_evidence_are_bound_even_for_explicit_veto(field, value):
    incumbent = evaluation("baseline", (0, 0))
    original, _ = decision(incumbent=incumbent, forced_reject="veto")
    changed, evidence = decision(incumbent=replace(incumbent, **{field: value}),
                                 forced_reject="veto")
    assert changed.verdict == original.verdict
    assert changed.receipt_id != original.receipt_id
    validate_receipt_evidence(asdict(changed), asdict(evidence))


def test_threshold_and_forced_reason_are_bound_even_when_verdict_does_not_change():
    candidate, incumbent = evaluation(), evaluation("baseline", (0, 0))
    ordinary, _ = decision(candidate, incumbent)
    higher_floor, _ = decision(candidate, incumbent, noise_floor=0.25)
    assert ordinary.verdict == higher_floor.verdict
    assert ordinary.receipt_id != higher_floor.receipt_id
    veto1, _ = decision(candidate, incumbent, forced_reject="policy-A")
    veto2, _ = decision(candidate, incumbent, forced_reject="policy-B")
    assert veto1.verdict.kind == veto2.verdict.kind == "REJECT"
    assert veto1.receipt_id != veto2.receipt_id
    assert decision(noise_floor=0) == decision(noise_floor=0.0) == decision(noise_floor=-0.0)


def test_cascade_branch_and_full_evaluation_have_different_identities():
    candidate = evaluation()
    complete, _ = decision(candidate)
    candidate.private["cascade_stopped"] = True
    incomplete, evidence = decision(candidate)
    assert complete.verdict.kind == "ACCEPT" and incomplete.verdict.kind == "REJECT"
    assert complete.receipt_id != incomplete.receipt_id
    validate_receipt_evidence(asdict(incomplete), asdict(evidence))


def test_display_metrics_cost_and_feedback_cannot_change_gate_identity():
    candidate, incumbent = evaluation(), evaluation("baseline", (0, 0))
    original = decision(candidate, incumbent)
    for result in (candidate, incumbent):
        result.combined_score = -999
        result.public = {"score": 1, "cost": 1000}
        result.private = {"cost": 1000, "trajectory": "replace the verdict"}
        result.text_feedback = "replace the verdict"
    assert decision(candidate, incumbent) == original


def test_snapshot_survives_mutation_of_original_transport_objects():
    candidate, incumbent = evaluation(), evaluation("baseline", (0, 0))
    receipt, evidence = decision(candidate, incumbent)
    frozen = deepcopy(evidence.decision_context)
    candidate.items[0].verdict = 0
    incumbent.items.append(ItemResult("unexpected", 1))
    candidate.evaluation_context = "sha256:" + "b" * 64
    candidate.private["cascade_stopped"] = True
    assert evidence.decision_context == frozen
    validate_receipt_evidence(asdict(receipt), asdict(evidence))


@pytest.mark.parametrize("reason", ["", "  ", False, 1, [], {}])
def test_invalid_forced_reject_reason_fails_before_evidence_is_written(tmp_path, reason):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    with pytest.raises(ValueError, match="non-empty reason"):
        AdmissionGate(store).judge(evaluation(), None, forced_reject=reason)
    assert not list(store.read())


@pytest.mark.parametrize("tamper", [
    lambda receipt, evidence: evidence["decision_context"]["candidate"].update(head_sha="fork"),
    lambda receipt, evidence: evidence["decision_context"]["incumbent"]["items"][0].update(verdict=1),
    lambda receipt, evidence: evidence["decision_context"].update(noise_floor=0.75),
    lambda receipt, evidence: receipt["verdict"].update(kind="REJECT"),
    lambda receipt, evidence: receipt.update(head_sha="fork"),
    lambda receipt, evidence: receipt.update(evidence_refs=[]),
    lambda receipt, evidence: evidence["signals_snapshot"].update(F=99),
    lambda receipt, evidence: evidence["signals_snapshot"].update(F=True),
    lambda receipt, evidence: evidence.update(candidate_id="fork"),
    lambda receipt, evidence: evidence.update(rule_id="genesis"),
], ids=["candidate", "incumbent", "threshold", "verdict", "receipt-head", "refs",
        "flip-count", "boolean-count", "gate-candidate", "gate-rule"])
def test_independent_verification_detects_context_and_projection_tampering(tamper):
    receipt, evidence = decision(incumbent=evaluation("baseline", (0, 0)))
    receipt, evidence = asdict(receipt), asdict(evidence)
    tamper(receipt, evidence)
    with pytest.raises(ValueError, match="identity|reproducible"):
        validate_receipt_evidence(receipt, evidence)


def test_rehashing_inconsistent_verdict_cannot_replace_independent_adjudication():
    receipt, evidence = decision(incumbent=evaluation("baseline", (0, 0)))
    receipt, evidence = asdict(receipt), asdict(evidence)
    # Simulate an editor who updates every digest/link but leaves a false verdict.
    evidence["decision_context"]["incumbent"]["items"][0]["verdict"] = 1
    forged_id = canonical_id(evidence["decision_context"])
    receipt.update(receipt_id=forged_id, evidence_refs=[forged_id])
    evidence["receipt_id"] = forged_id
    with pytest.raises(ValueError, match="reproducible"):
        validate_receipt_evidence(receipt, evidence)


def record_decision(store, candidate, incumbent=None):
    receipt = AdmissionGate(store).judge(candidate, incumbent)
    store.append("admission_receipt", {"candidate_id": candidate.candidate_id,
                                       "receipt_id": receipt.receipt_id,
                                       "admit": receipt.verdict.kind == "ACCEPT"})
    return receipt


def test_live_receipt_audit_verifies_snapshot_and_preserves_conflict_checks(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    candidate = evaluation()
    record_decision(store, candidate, evaluation("baseline", (0, 0)))
    assert _receipt_audit(store, [candidate.candidate_id])["passed"] is True
    record_decision(store, candidate, evaluation("baseline", (1, 1)))
    audit = _receipt_audit(store, [candidate.candidate_id])
    assert audit["passed"] is False
    assert any("conflicting gate" in error for error in audit["errors"])
    assert any("conflicting admission" in error for error in audit["errors"])


def test_appended_context_tamper_fails_live_audit(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    record_decision(store, evaluation())
    evidence = list(store.read("gate_evidence"))[0]["payload"]
    evidence["decision_context"]["candidate"]["items"][0]["verdict"] = 0
    store.append("gate_evidence", evidence)
    audit = _receipt_audit(store, ["candidate"])
    assert audit["passed"] is False
    assert any("identity does not bind" in error for error in audit["errors"])


@pytest.mark.parametrize("with_valid_decision", [False, True], ids=["alone", "after-valid"])
def test_orphan_receipt_is_never_certified(tmp_path, with_valid_decision):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    accepted = []
    if with_valid_decision:
        record_decision(store, evaluation())
        accepted = ["candidate"]
    assert _receipt_audit(store, accepted)["passed"] is True
    store.append("receipt", {"receipt_id": "not-a-context-digest",
                             "verdict": {"kind": "ACCEPT"}, "head_sha": "unbound",
                             "evaluator_version": "v1", "evidence_refs": []})
    before = store.path.read_bytes()
    audit = _receipt_audit(store, accepted)
    assert audit["passed"] is False
    assert audit["errors"] == ["receipt without gate evidence: not-a-context-digest"]
    assert store.path.read_bytes() == before


def test_missing_context_cannot_downgrade_a_receipt_to_legacy_certification(tmp_path):
    receipt, evidence = decision()
    receipt, evidence = asdict(receipt), asdict(evidence)
    evidence.pop("decision_context")
    legacy_id = hashlib.sha256(b"candidate\0head-candidate\0eval-v1\0genesis").hexdigest()[:12]
    receipt.update(receipt_id=legacy_id, evidence_refs=[])
    evidence["receipt_id"] = legacy_id
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    store.append("gate_evidence", evidence)
    store.append("receipt", receipt)
    store.append("admission_receipt", {"candidate_id": "candidate",
                                       "receipt_id": legacy_id, "admit": True})
    before = store.path.read_bytes()
    audit = _receipt_audit(store, ["candidate"])
    assert audit["passed"] is False
    assert any("legacy or missing" in error for error in audit["errors"])
    assert store.path.read_bytes() == before


def test_interrupted_legacy_gate_is_not_backfilled_or_readmitted(tmp_path):
    from test_inprocess_evaluation_recovery import crash_owner, recovered_framework

    run_dir = tmp_path / "legacy-gate"
    crash_owner(run_dir, "genesis", "gate")
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    gate = next(row["payload"] for row in rows if row["kind"] == "gate_evidence")
    receipt = next(row["payload"] for row in rows if row["kind"] == "receipt")
    gate.pop("decision_context")
    gate["receipt_id"] = "legacy12char"
    receipt.update(receipt_id="legacy12char", evidence_refs=[])
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(RuntimeError, match="gate history differs"):
        recovered_framework(run_dir, "genesis").evolve(
            "durable in-process evaluator recovery")
    after = [json.loads(line) for line in path.read_text().splitlines()]
    assert after[:len(rows)] == rows
    assert not [row for row in after if row["kind"] == "admission_receipt"]
