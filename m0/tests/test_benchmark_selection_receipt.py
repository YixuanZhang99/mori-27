"""Replayable pre-test selection receipts; fixtures are not benchmark results."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tasks.benchmark import (ScoreRunRecord, SelectionCandidate,
                                  SelectionContract, SelectionReceipt,
                                  compare_scores_same_budget)


def contract(kind="archive_best"):
    return SelectionContract(kind, f"{kind}-validation-max-v1", "validation")


def candidate(cid, score, chain=None, terminal=False, ref=None):
    return SelectionCandidate(cid, ref or f"validation://{cid}", score, chain, terminal)


def test_single_run_receipt_needs_no_validation_score_and_replays():
    selection = contract("single_run")
    only = candidate("final", None)
    receipt = SelectionReceipt(selection, (only,), "final")
    assert receipt.validate_and_replay() == only
    assert len(receipt.receipt_sha256) == 64
    with pytest.raises(ValueError, match="exactly one candidate"):
        SelectionReceipt(selection, (only, candidate("other", None)), "final").validate_and_replay()


def test_archive_best_replays_validation_max_and_deterministic_tie_break():
    selection = contract()
    pool = (candidate("b", 0.8), candidate("a", 0.8), candidate("low", 0.2))
    receipt = SelectionReceipt(selection, pool, "a")
    assert receipt.validate_and_replay().candidate_id == "a"
    with pytest.raises(ValueError, match="deterministic selection replay"):
        SelectionReceipt(selection, pool, "b").validate_and_replay()


def test_archive_best_does_not_silently_select_non_maximum():
    pool = (candidate("low", 0.1), candidate("high", 0.9))
    with pytest.raises(ValueError, match="deterministic selection replay"):
        SelectionReceipt(contract(), pool, "low").validate_and_replay()


def test_best_single_chain_uses_one_terminal_per_chain_not_archive_maximum():
    selection = contract("best_single_chain")
    pool = (
        candidate("chain-a-early", 99, "a", False),
        candidate("chain-a-final", 0.7, "a", True),
        candidate("chain-b-early", 0.6, "b", False),
        candidate("chain-b-final", 0.8, "b", True),
    )
    receipt = SelectionReceipt(selection, pool, "chain-b-final")
    assert receipt.validate_and_replay().candidate_id == "chain-b-final"
    with pytest.raises(ValueError, match="deterministic selection replay"):
        SelectionReceipt(selection, pool, "chain-a-early").validate_and_replay()


@pytest.mark.parametrize("pool,message", [
    ((candidate("a", 1, None, True),), "chain_id"),
    ((candidate("a", 1, "a", False),), "exactly one terminal"),
    ((candidate("a1", 1, "a", True), candidate("a2", 2, "a", True)),
     "exactly one terminal"),
])
def test_best_single_chain_rejects_ambiguous_chain_evidence(pool, message):
    selection = contract("best_single_chain")
    with pytest.raises(ValueError, match=message):
        SelectionReceipt(selection, pool, pool[0].candidate_id).validate_and_replay()


def test_pool_selection_requires_validation_split_and_scores():
    with pytest.raises(ValueError, match="explicit validation split"):
        SelectionReceipt(SelectionContract("archive_best", "max-v1", "not_applicable"),
                         (candidate("a", 1),), "a").validate_and_replay()
    with pytest.raises(ValueError, match="finite validation scores"):
        SelectionReceipt(contract(), (candidate("a", None),), "a").validate_and_replay()


@pytest.mark.parametrize("bad_pool,selected,message", [
    ((), "a", "non-empty candidate tuple"),
    ((candidate("a", 1), candidate("a", 2)), "a", "unique"),
    ((candidate("a", 1),), "missing", "absent"),
    ((SelectionCandidate("a", "", 1),), "a", "evidence_ref"),
    ((candidate("a", float("nan")),), "a", "finite"),
])
def test_malformed_candidate_pools_fail_closed(bad_pool, selected, message):
    with pytest.raises((ValueError, TypeError), match=message):
        SelectionReceipt(contract(), bad_pool, selected).validate_and_replay()


def test_receipt_hash_binds_pool_choice_and_contract_even_after_rehashing():
    pool = (candidate("low", 0.1), candidate("high", 0.9))
    original = SelectionReceipt(contract(), pool, "high")
    tampered = replace(original, selected_candidate_id="low")
    with pytest.raises(ValueError, match="hash mismatch"):
        tampered.validate_and_replay()
    rehashed = SelectionReceipt(tampered.contract, tampered.candidates,
                                tampered.selected_candidate_id)
    with pytest.raises(ValueError, match="deterministic selection replay"):
        rehashed.validate_and_replay()
    changed_contract = replace(original.contract, policy="another-policy-v2")
    with pytest.raises(ValueError, match="hash mismatch"):
        replace(original, contract=changed_contract).validate_and_replay()


def run(receipt, score=10.0, arm="host", seed=1):
    return ScoreRunRecord(
        benchmark="receipt-fixture", task_list_sha256="locked", task_id="task",
        seed=seed, arm=arm, backbone="model", budget={"wallclock": 5},
        actual_costs={"wallclock": 4}, score=score,
        evidence_refs=("official-test://run",), measured=True,
        selection=receipt.contract, selection_receipt=receipt)


def test_measured_record_requires_receipt_and_exact_contract_binding():
    receipt = SelectionReceipt(contract(), (candidate("a", 1),), "a")
    with pytest.raises(ValueError, match="explicit selection receipt"):
        replace(run(receipt), selection_receipt=None).validate_measured()
    with pytest.raises(ValueError, match="contract differ"):
        replace(run(receipt), selection=contract("single_run")).validate_measured()


def test_official_test_score_cannot_change_pre_test_selection_replay():
    pool = (candidate("low-validation", 0.1), candidate("high-validation", 0.9))
    receipt = SelectionReceipt(contract(), pool, "high-validation")
    low_test = run(receipt, score=0.0)
    high_test = run(receipt, score=1_000_000.0)
    low_test.validate_measured()
    high_test.validate_measured()
    assert low_test.selection_receipt.receipt_sha256 == high_test.selection_receipt.receipt_sha256


def test_comparison_reports_every_receipt_digest_and_replays_each_run():
    def make(arm, seed):
        pool = (candidate(f"{arm}-{seed}-low", 0.1),
                candidate(f"{arm}-{seed}-high", 0.9))
        return run(SelectionReceipt(contract(), pool, f"{arm}-{seed}-high"),
                   arm=arm, seed=seed)

    host = [make("host", seed) for seed in (1, 2, 3)]
    governed = [make("governed", seed) for seed in (1, 2, 3)]
    report = compare_scores_same_budget(host, governed, 0)
    assert len(report.selection_receipt_sha256) == 6
    assert report.selection_receipt_sha256["host/task/1"] == host[0].selection_receipt.receipt_sha256
    governed[0] = replace(governed[0], selection_receipt=replace(
        governed[0].selection_receipt, selected_candidate_id="governed-1-low"))
    with pytest.raises(ValueError, match="hash mismatch"):
        compare_scores_same_budget(host, governed, 0)
