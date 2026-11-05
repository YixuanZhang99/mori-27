"""Offline migration and protected obligations on the existing currency authority."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from zoo.mle_bench_lite.cny_budget import CampaignBudget

RUN = "a" * 64
OTHER_RUN = "b" * 64
PLAN = "sha256:" + "c" * 64


def usage(prompt=100, completion=20):
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion}


def migrated(tmp_path, *, limit=200000000):
    ledger = CampaignBudget.create(tmp_path / "campaign.db", limit_micro_cny=limit)
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()["policy_sha256"],
                             expected_head=ledger.snapshot()["journal_head"])
    return ledger


def obligations(ledger, *, slots=("control-0000", "control-0001")):
    return [{"slot_id": slot, "phase": "operator", "ordinal": 0,
             "bound": ledger.quote_call(4096)} for slot in slots]


def binding(call_id="call", *, phase="operator", ordinal=0):
    return {"call_id": call_id, "request_sha256": "d" * 64, "phase": phase, "ordinal": ordinal}


def rows(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT seq,payload,hash FROM events ORDER BY seq").fetchall()


def test_explicit_migration_preserves_old_policy_charges_and_event_bytes(tmp_path):
    ledger = CampaignBudget.create(tmp_path / "campaign.db")
    ledger.reserve("old", "d" * 64, 4096, run_id=OTHER_RUN)
    ledger.settle("old", usage(), "e" * 64)
    old_rows, policy = rows(ledger.path), ledger.manifest_binding()
    old_snapshot = ledger.snapshot()
    ledger.enable_governance(expected_policy_sha256=policy["policy_sha256"],
                             expected_head=old_snapshot["journal_head"])
    assert rows(ledger.path)[:2] == old_rows
    assert ledger.manifest_binding() == policy
    snapshot = CampaignBudget(ledger.path).snapshot()
    assert snapshot["settled_upper_bound_micro_cny"] == 360
    assert snapshot["operations"] == old_snapshot["operations"]
    marker = json.loads(rows(ledger.path)[-1][1])
    assert marker["kind"] == "governance_enabled" and marker["schema_version"] == 2
    assert marker["previous_head"] == old_snapshot["journal_head"]


def test_governance_requires_explicit_migration_and_stable_anchor(tmp_path):
    ledger = CampaignBudget.create(tmp_path / "campaign.db")
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="migration|enable"):
        ledger.protect_run(RUN, PLAN, obligations(ledger))
    with pytest.raises(ValueError, match="anchor|head|policy"):
        ledger.enable_governance(expected_policy_sha256="0" * 64,
                                 expected_head=before["journal_head"])
    assert ledger.snapshot() == before
    ledger.reserve("pending", "d" * 64, 4096)
    with pytest.raises(ValueError, match="unresolved"):
        ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()["policy_sha256"],
                                 expected_head=ledger.snapshot()["journal_head"])


def test_outstanding_obligations_reduce_legacy_main_admission(tmp_path):
    # Each defensible call costs <= 2,129,920 micro CNY; hold exactly two calls.
    ledger = migrated(tmp_path, limit=4259840)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="exhausted|protected"):
        ledger.reserve("legacy-main", "d" * 64, 4096, run_id=OTHER_RUN)
    assert ledger.snapshot() == before
    audit = ledger.audit_run(RUN, PLAN)
    assert audit["outstanding_micro_cny"] == 4259840
    assert audit["protection_valid"] is True


def test_control_conversion_and_settlement_release_only_unused_capacity(tmp_path):
    ledger = migrated(tmp_path, limit=4259840)
    frozen = obligations(ledger)
    ledger.protect_run(RUN, PLAN, frozen)
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    report = CampaignBudget(ledger.path).audit_run(RUN, PLAN)
    assert report["outstanding_micro_cny"] == 2129920
    assert report["reserved_micro_cny"] == 2129920
    assert report["pending_calls"] == ["call"]
    with pytest.raises(ValueError, match="unresolved"):
        ledger.admit_call(RUN, "control", "control-0001", binding("other"), ledger.quote_call(4096))
    ledger.settle("call", usage(), "e" * 64)
    report = ledger.audit_run(RUN, PLAN)
    assert report["settled_upper_bound_micro_cny"] == 360
    assert report["outstanding_micro_cny"] == 2129920
    assert report["reserved_micro_cny"] == 0
    assert report["slots"]["control-0000"]["settled"] == 1
    assert ledger.snapshot()["remaining_micro_cny"] == 2129560


def test_protection_and_settlement_are_idempotent_but_changed_plan_is_rejected(tmp_path):
    ledger = migrated(tmp_path)
    frozen = obligations(ledger)
    ledger.protect_run(RUN, PLAN, frozen)
    before = rows(ledger.path)
    ledger.protect_run(RUN, PLAN, copy.deepcopy(frozen))
    assert rows(ledger.path) == before
    altered = copy.deepcopy(frozen)
    altered[0]["bound"] = ledger.quote_call(8192)
    with pytest.raises(ValueError, match="changed|different|frozen"):
        ledger.protect_run(RUN, PLAN, altered)
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    ledger.settle("call", usage(), "e" * 64)
    settled = rows(ledger.path)
    ledger.settle("call", usage(), "e" * 64)
    assert rows(ledger.path) == settled


def test_known_failed_slot_can_cancel_only_unconsumed_obligations(tmp_path):
    ledger = migrated(tmp_path)
    frozen = obligations(ledger)
    frozen.append({"slot_id": "control-0000", "phase": "evaluation", "ordinal": 0,
                   "bound": ledger.quote_call(4096)})
    ledger.protect_run(RUN, PLAN, frozen)
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    with pytest.raises(ValueError, match="unresolved"):
        ledger.cancel_control(RUN, "control-0000", reason="known_failure")
    ledger.settle("call", usage(), "e" * 64)
    ledger.cancel_control(RUN, "control-0000", reason="known_failure")
    report = ledger.audit_run(RUN, PLAN)
    assert report["outstanding_micro_cny"] == 2129920
    assert report["slots"]["control-0000"] == {"planned": 2, "pending": 0,
        "admitted": 0, "settled": 1, "cancelled": 1}
    with pytest.raises(ValueError, match="cancelled|consumed|obligation"):
        ledger.admit_call(RUN, "control", "control-0000", binding("eval", phase="evaluation"),
                          ledger.quote_call(4096))


@pytest.mark.parametrize("bad", [
    lambda b: b.update(output_allowance=True),
    lambda b: b.update(reserved_micro_cny=1),
    lambda b: b.update(schema_version=True),
    lambda b: b.update(other=1),
])
def test_invalid_currency_bound_fails_without_modifying_ledger(tmp_path, bad):
    ledger = migrated(tmp_path)
    frozen = obligations(ledger)
    bad(frozen[0]["bound"])
    before = rows(ledger.path)
    with pytest.raises(ValueError):
        ledger.protect_run(RUN, PLAN, frozen)
    assert rows(ledger.path) == before


def test_known_bound_overrun_keeps_full_charge_and_blocks_both_lanes(tmp_path):
    ledger = migrated(tmp_path)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    ledger.settle("call", usage(prompt=1048577, completion=4097), "e" * 64)
    report = ledger.audit_run(RUN, PLAN)
    assert report["settled_upper_bound_micro_cny"] == 2129930
    assert report["reserved_micro_cny"] == 0
    assert report["protection_valid"] is False
    assert report["breaches"] == ["call"]
    for lane, slot in (("main", None), ("control", "control-0001")):
        with pytest.raises(ValueError, match="bound|protection|breach"):
            ledger.admit_call(RUN, lane, slot, binding("next"), ledger.quote_call(4096))
    with pytest.raises(ValueError, match="bound|protection|breach"):
        ledger.reserve("legacy", "d" * 64, 4096)


def test_concurrent_main_and_control_cannot_expose_converted_obligation(tmp_path):
    ledger = migrated(tmp_path, limit=2129920)
    ledger.protect_run(RUN, PLAN, obligations(ledger, slots=("control-0000",)))
    def attempt(control):
        try:
            reopened = CampaignBudget(ledger.path)
            if control:
                reopened.admit_call(RUN, "control", "control-0000", binding(), reopened.quote_call(4096))
            else:
                reopened.reserve("main", "d" * 64, 4096)
            return control
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, (False, True)))
    assert result == [None, True]
    report = ledger.audit_run(RUN, PLAN)
    assert report["outstanding_micro_cny"] == 0
    assert report["reserved_micro_cny"] == 2129920


def test_unresolved_call_cannot_be_repeated_or_cleared_by_reopen(tmp_path):
    ledger = migrated(tmp_path)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    reopened = CampaignBudget(ledger.path)
    before = rows(ledger.path)
    with pytest.raises(ValueError, match="unresolved"):
        reopened.admit_call(RUN, "control", "control-0000", binding(), reopened.quote_call(4096))
    assert rows(ledger.path) == before
    assert reopened.audit_run(RUN, PLAN)["pending_calls"] == ["call"]


def test_changed_slot_phase_ordinal_and_plan_are_rejected(tmp_path):
    ledger = migrated(tmp_path)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    before = rows(ledger.path)
    for slot, call in (("foreign", binding()), ("control-0000", binding(phase="evaluation")),
                       ("control-0000", binding(ordinal=1))):
        with pytest.raises(ValueError, match="obligation|slot"):
            ledger.admit_call(RUN, "control", slot, call, ledger.quote_call(4096))
    with pytest.raises(ValueError, match="plan"):
        ledger.audit_run(RUN, "sha256:" + "0" * 64)
    assert rows(ledger.path) == before


def test_migration_anchor_rejects_boolean_sequence(tmp_path):
    ledger = CampaignBudget.create(tmp_path / "campaign.db")
    with pytest.raises(ValueError, match="head|anchor"):
        ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()["policy_sha256"],
                                 expected_head={"seq": False, "sha256": "0" * 64})
    assert rows(ledger.path) == []


def rehash_events(path, mutate):
    with sqlite3.connect(path) as db:
        events = [json.loads(payload) for (payload,) in db.execute("SELECT payload FROM events ORDER BY seq")]
        mutate(events)
        db.execute("DELETE FROM events")
        previous = "0" * 64
        for seq, event in enumerate(events, 1):
            encoded = json.dumps({"seq": seq, "previous": previous, "event": event},
                                 sort_keys=True, separators=(",", ":"), allow_nan=False)
            previous = hashlib.sha256(encoded.encode()).hexdigest()
            db.execute("INSERT INTO events VALUES (?,?,?)", (seq,
                json.dumps(event, sort_keys=True, separators=(",", ":")), previous))
        db.execute("UPDATE head SET seq=?,hash=?", (len(events), previous))


@pytest.mark.parametrize("damage", ["bound", "ordinal", "marker", "version", "cancel_pending"])
def test_rehashed_semantically_invalid_currency_history_is_rejected(tmp_path, damage):
    ledger = migrated(tmp_path)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    def mutate(events):
        if damage == "bound":
            events[-1]["reserved_micro_cny"] = 1
        elif damage == "ordinal":
            events[-1]["ordinal"] = 1
        elif damage == "marker":
            events.pop(0)
        elif damage == "version":
            events[-1]["schema_version"] = 3
        else:
            events.append({"kind": "cancel_control", "schema_version": 2, "run_id": RUN,
                "plan_ref": PLAN, "slot_id": "control-0000", "reason": "erase_unknown"})
    rehash_events(ledger.path, mutate)
    with pytest.raises(ValueError):
        ledger.audit_run(RUN, PLAN)
    with pytest.raises(ValueError):
        CampaignBudget(ledger.path)


def test_audit_is_read_only_and_recomputes_external_appends(tmp_path):
    ledger = migrated(tmp_path)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    before = ledger.path.read_bytes()
    first = ledger.audit_run(RUN, PLAN)
    assert ledger.path.read_bytes() == before
    other = CampaignBudget(ledger.path)
    other.cancel_control(RUN, "control-0000", reason="known_failure")
    second = ledger.audit_run(RUN, PLAN)
    assert second["outstanding_micro_cny"] == first["outstanding_micro_cny"] - 2129920
    assert second["journal_head"] != first["journal_head"]


@pytest.mark.parametrize("boundary", ["protect", "admit", "settle"])
def test_sigkill_after_authority_commit_preserves_exact_obligation_state(tmp_path, boundary):
    import os
    import signal
    import subprocess
    import sys
    ledger = migrated(tmp_path)
    script = '''import json, os, signal, sys
from zoo.mle_bench_lite.cny_budget import CampaignBudget
ledger = CampaignBudget(sys.argv[1])
run, plan, frozen, boundary = json.loads(sys.argv[2])
ledger.protect_run(run, plan, frozen)
if boundary != "protect":
    ledger.admit_call(run, "control", "control-0000",
        {"call_id":"child", "request_sha256":"d"*64, "phase":"operator", "ordinal":0},
        ledger.quote_call(4096))
if boundary == "settle":
    ledger.settle("child", {"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}, "e"*64)
os.kill(os.getpid(), signal.SIGKILL)
'''
    child = subprocess.run([sys.executable, "-c", script, str(ledger.path),
        json.dumps([RUN, PLAN, obligations(ledger), boundary])], capture_output=True, text=True,
        env=os.environ.copy(), timeout=10)
    assert child.returncode == -signal.SIGKILL, child.stderr
    report = CampaignBudget(ledger.path).audit_run(RUN, PLAN)
    assert report["outstanding_micro_cny"] == (4259840 if boundary == "protect" else 2129920)
    assert report["reserved_micro_cny"] == (2129920 if boundary == "admit" else 0)
    assert report["settled_upper_bound_micro_cny"] == (360 if boundary == "settle" else 0)
    assert report["pending_calls"] == (["child"] if boundary == "admit" else [])


def test_shared_runs_protect_capacity_against_each_other(tmp_path):
    ledger = migrated(tmp_path, limit=4259840)
    ledger.protect_run(RUN, PLAN, obligations(ledger, slots=("control-0000",)))
    ledger.protect_run(OTHER_RUN, PLAN, obligations(ledger, slots=("control-0000",)))
    with pytest.raises(ValueError, match="exhausted|protected"):
        ledger.admit_call(OTHER_RUN, "main", None, binding("main"), ledger.quote_call(4096))
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    ledger.settle("call", usage(), "e" * 64)
    assert ledger.audit_run(OTHER_RUN, PLAN)["outstanding_micro_cny"] == 2129920
    ledger.admit_call(OTHER_RUN, "control", "control-0000", binding("other"), ledger.quote_call(4096))
    ledger.settle("other", usage(), "f" * 64)
    assert ledger.snapshot()["settled_upper_bound_micro_cny"] == 720


def test_run_audit_exposes_exact_frozen_obligations_and_admission_bindings(tmp_path):
    ledger = migrated(tmp_path)
    frozen = obligations(ledger)
    ledger.protect_run(RUN, PLAN, frozen)
    ledger.admit_call(RUN, "control", "control-0000", binding(), ledger.quote_call(4096))
    report = ledger.audit_run(RUN, PLAN)
    assert report["frozen_obligations"] == frozen
    assert report["operations"][0]["request_sha256"] == "d" * 64
    assert report["operations"][0]["slot_id"] == "control-0000"
    report["frozen_obligations"][0]["bound"]["output_allowance"] = 1
    assert ledger.audit_run(RUN, PLAN)["frozen_obligations"] == frozen
    assert report["admission_open"] is False
