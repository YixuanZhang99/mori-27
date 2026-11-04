"""Portable currency authority proofs recompute history without a live ledger."""
import copy
import hashlib
import json
import sqlite3

import pytest

from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.governed_currency_audit import (
    RecordedCurrencyView, verify_governance_evidence,
)

RUN = "a" * 64
OTHER_RUN = "b" * 64
PLAN = "sha256:" + "c" * 64


def usage(prompt, completion):
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion}


@pytest.fixture
def authority(tmp_path):
    ledger = CampaignBudget.create(tmp_path / "campaign.db")
    ledger.reserve("legacy", "d" * 64, 4096, run_id=OTHER_RUN)
    ledger.settle("legacy", usage(100, 20), "e" * 64)
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()["policy_sha256"],
                             expected_head=ledger.snapshot()["journal_head"])
    ledger.protect_run(RUN, PLAN, [
        {"slot_id": slot, "phase": "operator", "ordinal": 0, "bound": ledger.quote_call(4096)}
        for slot in ("control-0000", "control-0001")])
    ledger.admit_call(RUN, "control", "control-0000", {
        "call_id": "control", "request_sha256": "f" * 64,
        "phase": "operator", "ordinal": 0}, ledger.quote_call(4096))
    ledger.settle("control", usage(10, 2), "e" * 64)
    return ledger


def rechain(evidence):
    previous = "0" * 64
    for index, row in enumerate(evidence["events"], 1):
        row["seq"] = index
        event = json.loads(row["payload"])
        raw = json.dumps({"seq": index, "previous": previous, "event": event},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
        previous = hashlib.sha256(raw.encode()).hexdigest()
        row["sha256"] = previous
    evidence["journal_head"] = {"seq": len(evidence["events"]), "sha256": previous}
    return evidence


def mutate_event(evidence, kind, **changes):
    for row in evidence["events"]:
        event = json.loads(row["payload"])
        if event["kind"] == kind:
            event.update(changes)
            row["payload"] = json.dumps(event)
            return rechain(evidence)
    raise AssertionError(kind)


def test_export_preserves_exact_full_prefix_and_recomputes_shared_cost(authority):
    with sqlite3.connect(authority.path) as db:
        original_policy = db.execute("SELECT payload FROM policy").fetchone()[0]
        original_rows = db.execute("SELECT seq,payload,hash FROM events ORDER BY seq").fetchall()
    before = authority.path.read_bytes()
    evidence = authority.export_governance_evidence(RUN, PLAN)
    assert evidence["policy_json"] == original_policy
    assert [(r["seq"], r["payload"], r["sha256"]) for r in evidence["events"]] == original_rows
    assert authority.path.read_bytes() == before
    audit = verify_governance_evidence(evidence)
    assert audit == authority.audit_run(RUN, PLAN)
    assert audit["settled_upper_bound_micro_cny"] == 36
    assert audit["campaign_settled_upper_bound_micro_cny"] == 396
    assert audit["outstanding_micro_cny"] == 2_129_920
    assert audit["invoice_verified"] is False


def test_export_uses_read_only_connection(authority, monkeypatch):
    connect = sqlite3.connect
    observed = []
    def read_only(path, *args, **kwargs):
        observed.append(str(path))
        assert "mode=ro" in str(path)
        db = connect(path, *args, **kwargs)
        db.execute("PRAGMA query_only=ON")
        return db
    monkeypatch.setattr(sqlite3, "connect", read_only)
    assert authority.export_governance_evidence(RUN, PLAN)["run_id"] == RUN
    assert len(observed) == 1


@pytest.mark.parametrize("kind,changes", [
    ("governed_settle", {"upper_bound_micro_cny": 0}),
    ("governed_settle", {"bound_violation": True}),
    ("governed_reserve", {"plan_ref": "sha256:" + "9" * 64}),
    ("governed_reserve", {"run_id": OTHER_RUN}),
    ("governed_reserve", {"lane": "main"}),
    ("governed_reserve", {"slot_id": "control-9999"}),
    ("governed_reserve", {"phase": "evaluation"}),
    ("governed_reserve", {"ordinal": 1}),
    ("governed_reserve", {"schema_version": 3}),
])
def test_rehashed_semantic_forgery_is_rejected(authority, kind, changes):
    evidence = mutate_event(authority.export_governance_evidence(RUN, PLAN), kind, **changes)
    with pytest.raises(ValueError):
        verify_governance_evidence(evidence)


def test_rehashed_downgrade_and_cancel_after_admission_rejected(authority):
    evidence = authority.export_governance_evidence(RUN, PLAN)
    event = json.loads(evidence["events"][-1]["payload"])
    event.pop("schema_version")
    event.pop("bound_violation")
    event["kind"] = "settle"
    evidence["events"][-1]["payload"] = json.dumps(event)
    with pytest.raises(ValueError, match="legacy settlement"):
        verify_governance_evidence(rechain(evidence))
    evidence = authority.export_governance_evidence(RUN, PLAN)
    evidence["events"][-1]["payload"] = json.dumps({"kind": "cancel_control", "schema_version": 2,
        "run_id": RUN, "plan_ref": PLAN, "slot_id": "control-0000", "reason": "failed"})
    with pytest.raises(ValueError):
        verify_governance_evidence(rechain(evidence))


def test_prefix_head_policy_and_envelope_tampering_rejected(authority):
    original = authority.export_governance_evidence(RUN, PLAN)
    for change in ("prefix", "head", "policy", "totals", "run", "plan", "duplicate", "bool_seq"):
        evidence = copy.deepcopy(original)
        if change == "prefix":
            evidence["events"].pop(0)
            rechain(evidence)
        elif change == "head":
            evidence["journal_head"]["seq"] += 1
        elif change == "policy":
            policy = json.loads(evidence["policy_json"])
            policy["input_micro_cny_per_token"] = 0
            evidence["policy_json"] = json.dumps(policy)
        elif change == "totals":
            evidence["settled_upper_bound_micro_cny"] = 0
        elif change == "run":
            evidence["run_id"] = OTHER_RUN
        elif change == "plan":
            evidence["plan_ref"] = "sha256:" + "9" * 64
        elif change == "bool_seq":
            evidence["events"][0]["seq"] = True
        else:
            evidence["events"].append(copy.deepcopy(evidence["events"][-1]))
            rechain(evidence)
        with pytest.raises(ValueError):
            verify_governance_evidence(evidence)


def test_trusted_anchor_rejects_coherent_rollback(authority):
    earlier = authority.export_governance_evidence(RUN, PLAN)
    authority.cancel_control(RUN, "control-0001", reason="complete")
    current = authority.export_governance_evidence(RUN, PLAN)
    assert verify_governance_evidence(earlier)["outstanding_micro_cny"] > 0
    with pytest.raises(ValueError, match="anchor"):
        verify_governance_evidence(earlier, expected_head=current["journal_head"])
    for kwargs in ({"expected_run_id": OTHER_RUN}, {"expected_plan_ref": "sha256:" + "9" * 64},
                   {"expected_policy_sha256": "0" * 64}):
        with pytest.raises(ValueError, match="anchor"):
            verify_governance_evidence(current, **kwargs)


def test_recorded_view_never_opens_ledger_and_does_not_alias_inputs(authority, monkeypatch):
    evidence = authority.export_governance_evidence(RUN, PLAN)
    expected = authority.audit_run(RUN, PLAN)
    binding = authority.manifest_binding()
    bound = authority.quote_call(4096)
    authority.path.unlink()
    def forbidden(*args, **kwargs):
        raise AssertionError("offline proof touched a ledger")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    view = RecordedCurrencyView(evidence)
    evidence["events"].clear()
    assert view.audit_run(RUN, PLAN) == expected
    assert view.manifest_binding() == binding
    assert view.quote_call(4096) == bound
    exported = view.export_governance_evidence(RUN, PLAN)
    exported["events"].clear()
    assert view.audit_run(RUN, PLAN) == expected
    assert view.export_governance_evidence(RUN, PLAN)["events"]
    for method in ("settle", "reserve", "admit_call", "protect_run", "cancel_control", "enable_governance"):
        assert not hasattr(view, method)
    with pytest.raises(ValueError):
        view.audit_run(OTHER_RUN, PLAN)


def test_pending_and_breached_costs_survive_offline_reduction(authority):
    authority.admit_call(RUN, "main", None, {"call_id": "main", "request_sha256": "d" * 64,
        "phase": "operator", "ordinal": 0}, authority.quote_call(1))
    pending = verify_governance_evidence(authority.export_governance_evidence(RUN, PLAN))
    assert pending["pending_calls"] == ["main"]
    assert pending["admission_open"] is False
    assert pending["reserved_micro_cny"] == 2_097_160
    authority.settle("main", usage(10, 2), "e" * 64)
    breached = verify_governance_evidence(authority.export_governance_evidence(RUN, PLAN))
    assert breached["settled_upper_bound_micro_cny"] == 72
    assert breached["campaign_settled_upper_bound_micro_cny"] == 432
    assert breached["protection_valid"] is False
    assert breached["admission_open"] is False


def test_export_is_one_snapshot_even_when_writer_commits_between_reads(authority, monkeypatch):
    with sqlite3.connect(authority.path) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    earlier = authority.audit_run(RUN, PLAN)
    connect = sqlite3.connect
    commits = []
    class ConcurrentRead:
        def __init__(self, db):
            self.db = db
        def execute(self, sql, *args):
            if sql.startswith("SELECT seq, payload, hash FROM events"):
                # The policy SELECT has already established the export snapshot.
                # WAL allows a real, independent write transaction to commit now.
                authority.cancel_control(RUN, "control-0001", reason="complete")
                commits.append(True)
            return self.db.execute(sql, *args)
        def close(self):
            self.db.close()
    def connect_with_writer(path, *args, **kwargs):
        db = connect(path, *args, **kwargs)
        return ConcurrentRead(db) if "mode=ro" in str(path) else db
    monkeypatch.setattr(sqlite3, "connect", connect_with_writer)
    evidence = authority.export_governance_evidence(RUN, PLAN)
    assert commits == [True]
    assert verify_governance_evidence(evidence) == earlier
    current = authority.audit_run(RUN, PLAN)
    assert current["journal_head"]["seq"] == earlier["journal_head"]["seq"] + 1
    assert current["outstanding_micro_cny"] == 0


def test_export_rejects_changed_campaign_binding_and_unknown_run(authority, tmp_path):
    with pytest.raises(ValueError):
        authority.export_governance_evidence(OTHER_RUN, PLAN)
    other = CampaignBudget.create(tmp_path / "other.db")
    other.enable_governance(expected_policy_sha256=other.manifest_binding()["policy_sha256"],
                            expected_head=other.snapshot()["journal_head"])
    other.protect_run(RUN, PLAN, [{"slot_id": "control-0000", "phase": "operator", "ordinal": 0,
                                 "bound": other.quote_call(4096)}])
    original_binding = authority.manifest_binding()
    other.path.replace(authority.path)
    with pytest.raises(ValueError, match="identity or policy changed"):
        authority.export_governance_evidence(RUN, PLAN)
    replacement = CampaignBudget(authority.path).export_governance_evidence(RUN, PLAN)
    with pytest.raises(ValueError, match="anchor"):
        verify_governance_evidence(replacement, expected_policy_sha256=original_binding["policy_sha256"])
