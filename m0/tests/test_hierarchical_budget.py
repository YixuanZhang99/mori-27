"""One physical journal, atomic scoped caps, fidelity decisions and recovery."""
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from core.budget.ledger import BudgetError
from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget, JOURNAL_KIND, hierarchical_options
from core.composition.evaluation import EvaluationBinding, EvaluationContract
from core.executor.types import Candidate, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.x1.store import AppendOnlyStore

STAMP = AccountingStamp("offline", "native-fixture-v1", "tokenizer-v1", "price-v1", "logical-date")


def options(units=None):
    units = {"token": 10, "eval_count": 1, "node": 1,
             "wallclock": 2.0, "gpu_hours": 0.5, "usd": 0.1} if units is None else units
    return {"limits": {"global": {key: value * 10 for key, value in units.items()},
                       "direction": {key: value * 5 for key, value in units.items()},
                       "candidate": {key: value * 3 for key, value in units.items()}},
            "reservation": units, "fidelity_rungs": [
                {"fidelity": "proxy", "seed_set": [0], "time_limit": 2, "budget_token": 10},
                {"fidelity": "full", "seed_set": [0, 1, 2], "time_limit": 10,
                 "budget_token": 30, "resume_from": "artifact://training-state"}]}


def budget(tmp_path, config=None):
    return HierarchicalBudget(options() if config is None else config,
                              STAMP, AppendOnlyStore(tmp_path / "budget.jsonl"))


def reserve(controller, identifier="one", *, candidate="candidate", direction="branch", operation="dev"):
    node = Candidate(candidate)
    request = controller.allocate(node, direction_id=direction) if operation == "dev" else None
    return controller.reserve_operation(identifier, node, direction, operation, request=request)


def settle(controller, receipt, amounts=None):
    controller.settle_operation(receipt.intent_id, receipt.amounts if amounts is None else amounts,
                                measured_units=controller.units, fingerprint=receipt.fingerprint)


def test_global_direction_candidate_are_views_of_one_charge_and_one_atomic_basket_record(tmp_path):
    controller = budget(tmp_path)
    receipt = reserve(controller)
    assert receipt.granted
    before = controller.state()
    assert before["global"]["reserved"] == before["directions"]["branch"]["reserved"] == before["candidates"]["candidate"]["reserved"] == receipt.amounts
    actual = {key: 0 for key in controller.units}
    actual.update(token=4, eval_count=1, node=1, wallclock=1.5, gpu_hours=0.25, usd=0.03)
    settle(controller, receipt, actual)
    state = controller.state()
    assert state["global"]["used"] == state["directions"]["branch"]["used"] == state["candidates"]["candidate"]["used"] == actual
    assert state["global"]["used"]["token"] == 4
    assert not state["open_intents"] and all(value == 0 for value in state["global"]["reserved"].values())
    rows = list(controller.store.read(JOURNAL_KIND))
    assert len(rows) == 2 and [row["payload"]["event"] for row in rows] == ["reserve", "settle"]
    assert rows[0]["payload"]["data"]["intent"]["amounts"] == receipt.amounts
    assert rows[1]["payload"]["data"]["actual_costs"] == actual
    assert "standard_spent" not in state


@pytest.mark.parametrize("level", ["global", "direction", "candidate"])
def test_any_one_layer_or_unit_rejection_is_atomic_across_all_layers_and_units(tmp_path, level):
    config = options()
    config["limits"][level]["gpu_hours"] = 0.1
    controller = budget(tmp_path, config)
    before = controller.checkpoint_state()
    receipt = reserve(controller)
    assert not receipt.granted and level in receipt.reason and "gpu_hours" in receipt.reason
    assert controller.checkpoint_state() == before
    assert not controller.store.path.exists()


def test_direction_and_candidate_limits_are_independent_slices_not_extra_global_charges(tmp_path):
    config = options({"token": 10})
    config["limits"] = {"global": {"token": 50}, "direction": {"token": 20}, "candidate": {"token": 10}}
    controller = budget(tmp_path, config)
    first = reserve(controller, "one", candidate="a", direction="left")
    settle(controller, first)
    assert not reserve(controller, "two", candidate="a", direction="right").granted
    second = reserve(controller, "three", candidate="b", direction="left")
    settle(controller, second)
    assert not reserve(controller, "four", candidate="c", direction="left").granted
    third = reserve(controller, "five", candidate="c", direction="right")
    settle(controller, third)
    assert controller.state()["global"]["used"] == {"token": 30}
    assert controller.state()["directions"]["left"]["used"] == {"token": 20}


def test_zero_operation_reservation_still_requires_explicit_complete_coverage(tmp_path):
    config = options()
    zeros = {key: 0 for key in config["reservation"]}
    config["operation_reservations"] = {"planning": zeros}
    controller = budget(tmp_path, config)
    receipt = reserve(controller, operation="planning", direction="coordination")
    assert receipt.granted and receipt.amounts == zeros
    with pytest.raises(BudgetError, match="coverage"):
        controller.settle_operation(receipt.intent_id, zeros, measured_units=["token"], fingerprint=receipt.fingerprint)
    assert controller.state()["open_intents"] == [receipt.intent_id]
    settle(controller, receipt)
    assert controller.state()["global"]["used"] == zeros


@pytest.mark.parametrize("error", ["missing_cost", "missing_coverage", "negative", "nan", "boolean", "fractional_count"])
def test_missing_or_invalid_usage_never_releases_or_partially_settles_reservation(tmp_path, error):
    controller = budget(tmp_path)
    receipt = reserve(controller)
    actual, coverage = dict(receipt.amounts), list(controller.units)
    if error == "missing_cost":
        del actual["usd"]
    elif error == "missing_coverage":
        coverage.remove("usd")
    else:
        actual["token"] = {"negative": -1, "nan": float("nan"), "boolean": True, "fractional_count": 1.5}[error]
    before, journal = controller.checkpoint_state(), controller.store.path.read_bytes()
    with pytest.raises(BudgetError):
        controller.settle_operation(receipt.intent_id, actual, measured_units=coverage, fingerprint=receipt.fingerprint)
    assert controller.checkpoint_state() == before
    assert controller.store.path.read_bytes() == journal


def test_actual_overrun_is_recorded_truthfully_then_prevents_every_next_call(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    receipt = reserve(controller)
    settle(controller, receipt, {"token": 13})
    assert controller.state()["global"]["used"]["token"] == 13
    assert controller.state()["global"]["remaining"]["token"] == 87
    assert not reserve(controller, "next", candidate="another", direction="another").granted
    with pytest.raises(BudgetError, match="read-only"):
        controller.pre_call_check()
    signal = controller.converged()
    assert signal.rule == "reservation_overrun" and signal.statistical is False
    restored = HierarchicalBudget(controller.options, STAMP, controller.store)
    restored.restore_from_journal()
    assert restored.state() == controller.state()
    assert not reserve(restored, "next", candidate="another").granted


def test_unknown_usage_blocks_new_calls_and_can_only_close_against_same_receipt(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    receipt = reserve(controller)
    controller.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint, reason="provider usage absent")
    assert not reserve(controller, "next", candidate="another").granted
    before = controller.checkpoint_state()
    with pytest.raises(BudgetError, match="identity"):
        controller.settle_operation(receipt.intent_id, {"token": 4}, measured_units=["token"], fingerprint="forged")
    assert controller.checkpoint_state() == before
    settle(controller, receipt, {"token": 4})
    assert reserve(controller, "next", candidate="another").granted
    assert not reserve(controller, receipt.intent_id, candidate="another").granted


def test_started_or_unknown_calls_cannot_be_released_as_free_work(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    receipt = reserve(controller)
    controller.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    with pytest.raises(BudgetError, match="unstarted"):
        controller.release_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    controller.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint, reason="unknown charge")
    with pytest.raises(BudgetError, match="unstarted"):
        controller.release_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    assert controller.state()["global"]["reserved"] == {"token": 10}


def test_unstarted_reservation_can_release_but_its_identity_cannot_be_renewed(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    receipt = reserve(controller)
    controller.release_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    assert controller.state()["global"]["committed"] == {"token": 0}
    assert not reserve(controller, receipt.intent_id).granted


def test_fidelity_allocation_is_pure_and_granted_dev_attempts_drive_request_changes(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    candidate = Candidate("candidate")
    low = controller.allocate(candidate, direction_id="branch")
    assert low.fidelity == "proxy" and low.seed_set == [0]
    assert controller.allocate(candidate, direction_id="branch") == low
    assert not controller.store.path.exists()
    planning = reserve(controller, "planning", operation="planning")
    settle(controller, planning, {"token": 1})
    assert controller.allocate(candidate, direction_id="branch") == low
    allocation = controller.reserve_operation("dev", candidate, "branch", "dev", request=low)
    settle(controller, allocation, {"token": 4})
    high = controller.allocate(Candidate("next", ["candidate"]), direction_id="branch")
    assert high.fidelity == "full" and high.seed_set == [0, 1, 2]
    assert high.time_limit == 10 and high.resume_from == "artifact://training-state"
    assert controller.allocate(Candidate("new-root"), direction_id="new-direction") == low


def test_depth_ladder_requires_real_depth_not_generation_number(tmp_path):
    config = options({"token": 10})
    config.update(rung_by="depth", rung_every=2)
    controller = budget(tmp_path, config)
    candidate = Candidate("candidate", created_cycle=500)
    with pytest.raises(BudgetError, match="depth"):
        controller.allocate(candidate)
    assert controller.allocate(candidate, depth=1).fidelity == "proxy"
    assert controller.allocate(candidate, depth=2).fidelity == "full"


def test_caller_cannot_replace_the_allocated_dev_request_before_reservation(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    candidate = Candidate("candidate")
    expected = controller.allocate(candidate, direction_id="branch")
    with pytest.raises(BudgetError, match="allocated fidelity"):
        controller.reserve_operation("forged", candidate, "branch", "dev",
                                     request=replace(expected, seed_set=[99]))
    assert not controller.store.path.exists()
    expected.seed_set.append(99)
    assert controller.allocate(candidate, direction_id="branch").seed_set == [0]


def test_m9_requests_share_physical_budget_but_do_not_advance_dev_ladder(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    candidate = Candidate("candidate")
    for operation, split in (("admission", "admission"), ("final", "final_audit")):
        request = EvalRequest("full", seed_set=[7, 8], split_id=split)
        reservation = controller.reserve_operation(operation, candidate, "branch", operation, request=request)
        settle(controller, reservation, {"token": 2})
    assert controller.state()["global"]["used"] == {"token": 4}
    assert controller.allocate(candidate, direction_id="branch").fidelity == "proxy"
    with pytest.raises(BudgetError, match="independently"):
        controller.allocate(candidate, operation="final")


def test_paired_dev_baseline_uses_all_three_budget_views_without_advancing_fidelity(tmp_path):
    config = options({"token": 10})
    config["operation_reservations"] = {"dev_baseline": {"token": 5}}
    controller = budget(tmp_path, config)
    incumbent = Candidate("incumbent")
    request = EvalRequest("full", seed_set=[7, 8], split_id="dev")
    receipt = controller.reserve_operation("baseline", incumbent, "branch", "dev_baseline", request=request)
    assert receipt.granted and receipt.amounts == {"token": 5}
    settle(controller, receipt, {"token": 4})
    state = controller.state()
    assert state["global"]["used"] == state["directions"]["branch"]["used"] == state["candidates"]["incumbent"]["used"] == {"token": 4}
    assert controller.allocate(Candidate("next"), direction_id="branch").fidelity == "proxy"
    with pytest.raises(BudgetError, match="split"):
        controller.reserve_operation("wrong-baseline", incumbent, "branch", "dev_baseline",
                                     request=replace(request, split_id="admission"))


def test_basket_reservations_are_atomic_under_concurrent_calls(tmp_path):
    config = options({"token": 6})
    config["limits"] = {"global": {"token": 10}, "direction": {"token": 10}, "candidate": {"token": 10}}
    controller = budget(tmp_path, config)
    barrier = threading.Barrier(2)
    def run(identifier):
        barrier.wait()
        return reserve(controller, identifier, candidate=identifier, direction=identifier)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(run, ["first", "second"]))
    assert sum(receipt.granted for receipt in receipts) == 1
    assert controller.state()["global"]["reserved"] == {"token": 6}
    assert len(list(controller.store.read(JOURNAL_KIND))) == 1


def test_decimal_physical_units_do_not_add_floating_roundoff_into_false_rejection(tmp_path):
    config = options({"usd": 0.1})
    config["limits"] = {"global": {"usd": 0.3}, "direction": {"usd": 0.3}, "candidate": {"usd": 0.3}}
    controller = budget(tmp_path, config)
    for identifier in ("one", "two", "three"):
        receipt = reserve(controller, identifier)
        assert receipt.granted
        settle(controller, receipt)
    assert controller.state()["global"]["used"] == {"usd": 0.3}
    assert not reserve(controller, "four").granted


def fact(identifier, score, status=EvalStatus.OK):
    return EvidenceRecord(identifier, EvalResult(status, {"dev/score": score} if score is not None else {}))


def test_patience_rule_requires_minimum_valid_samples_and_is_not_statistical(tmp_path):
    config = options({"token": 10})
    config["convergence"] = {"patience": 2, "min_samples": 3, "min_improvement": 0.01}
    controller = budget(tmp_path, config)
    for index in range(3):
        assert controller.should_continue("branch", fact(f"failed-{index}", None, EvalStatus.FAILED_TO_RUN))
    assert controller.converged() is None and controller.state()["progress"]["samples"] == 0
    assert controller.should_continue("branch", fact("one", 0.5))
    assert controller.should_continue("branch", fact("two", 0.5))
    assert not controller.should_continue("branch", fact("three", 0.5))
    signal = controller.converged()
    assert signal.rule == "observed_dev_patience" and signal.statistical is False
    assert controller.should_continue("another", fact("improved", 0.7))
    assert controller.converged() is None


def test_repeated_observation_is_idempotent_but_changed_evidence_or_direction_is_rejected(tmp_path):
    config = options({"token": 10})
    config["convergence"] = {"patience": 1, "min_samples": 2}
    controller = budget(tmp_path, config)
    sample = fact("one", 0.5)
    controller.should_continue("branch", sample)
    before, journal = controller.checkpoint_state(), controller.store.path.read_bytes()
    controller.should_continue("branch", sample)
    assert controller.checkpoint_state() == before and controller.store.path.read_bytes() == journal
    with pytest.raises(BudgetError, match="rebound"):
        controller.should_continue("other", sample)
    with pytest.raises(BudgetError, match="rebound"):
        controller.should_continue("branch", fact("one", 0.8))
    assert controller.checkpoint_state() == before


def test_global_exhaustion_blocks_direction_continue_even_when_direction_has_room(tmp_path):
    config = options({"token": 10})
    config["limits"] = {"global": {"token": 10}, "direction": {"token": 100}, "candidate": {"token": 100}}
    controller = budget(tmp_path, config)
    receipt = reserve(controller, direction="left")
    settle(controller, receipt)
    assert not controller.should_continue("right")
    assert controller.converged().rule == "global_budget_exhausted"


def test_heldout_or_opaque_final_evidence_cannot_affect_convergence(tmp_path):
    config = options({"token": 10})
    config["convergence"] = {"patience": 1, "min_samples": 1}
    controller = budget(tmp_path, config)
    private = EvidenceRecord("final", EvalResult(EvalStatus.OK, {"dev/score": 0.1}, fidelity="final_audit"))
    with pytest.raises(BudgetError, match="non-dev"):
        controller.should_continue("branch", private)
    assert controller.state()["progress"]["attempts"] == 0
    assert not controller.store.path.exists()


def test_exact_minimum_improvement_boundary_does_not_gain_float_rounding_credit(tmp_path):
    config = options({"token": 10})
    config["convergence"] = {"patience": 1, "min_samples": 2, "min_improvement": 0.01}
    controller = budget(tmp_path, config)
    assert controller.should_continue("branch", fact("one", 0.5))
    assert not controller.should_continue("branch", fact("two", 0.51))
    assert controller.state()["progress"]["best"] == 0.5


def bound_fact(identifier, score, *, request="a" * 64, fidelity="proxy", seeds=(0,),
               context="dataset-a", evaluator="evaluator-v1"):
    binding = EvaluationBinding(identifier, "f" * 64, request, evaluator, context, "dev", fidelity, seeds)
    return EvidenceRecord(identifier, EvalResult(EvalStatus.OK, {"dev/score": score}, fidelity=fidelity,
        contract=EvaluationContract(binding, ("token", "eval_count"))))


@pytest.mark.parametrize("changed", [{"request": "b" * 64}, {"fidelity": "full"},
                                     {"seeds": (0, 1, 2)}, {"context": "dataset-b"},
                                     {"evaluator": "evaluator-v2"}])
def test_changed_comparison_binding_resets_progress_instead_of_comparing_incompatible_scores(tmp_path, changed):
    config = options({"token": 10})
    config["convergence"] = {"patience": 1, "min_samples": 2}
    controller = budget(tmp_path, config)
    assert controller.should_continue("branch", bound_fact("one", 0.9))
    assert not controller.should_continue("branch", bound_fact("two", 0.9))
    assert controller.converged() is not None
    assert controller.should_continue("branch", bound_fact("new-context", 0.2, **changed))
    progress = controller.state()["progress"]
    assert progress["best"] == 0.2 and progress["samples"] == 1 and progress["no_improvement"] == 0
    assert progress["window_resets"] == 1 and controller.converged() is None
    assert not controller.should_continue("branch", bound_fact("same-new-context", 0.2, **changed))
    restored = HierarchicalBudget(config, STAMP, controller.store)
    restored.restore_state(controller.checkpoint_state())
    assert restored.state() == controller.state()
    assert restored.should_continue("branch", bound_fact("returned-old-context", 0.9))
    assert restored.state()["progress"]["samples"] == 1


def test_journal_and_checkpoint_restore_open_settled_and_progress_without_writes(tmp_path):
    config = options({"token": 10})
    config["convergence"] = {"patience": 2, "min_samples": 2}
    controller = budget(tmp_path, config)
    one = reserve(controller, "one")
    settle(controller, one, {"token": 3})
    two = reserve(controller, "two", candidate="next")
    controller.mark_unresolved(two.intent_id, fingerprint=two.fingerprint, reason="interrupted")
    controller.should_continue("branch", fact("candidate", 0.5))
    checkpoint, journal = controller.checkpoint_state(), controller.store.path.read_bytes()
    restored = HierarchicalBudget(config, STAMP, controller.store)
    restored.restore_state(checkpoint)
    assert restored.checkpoint_state() == checkpoint and controller.store.path.read_bytes() == journal
    settle(restored, two, {"token": 2})
    assert restored.state()["global"]["used"] == {"token": 5}
    assert restored.allocate(Candidate("third"), direction_id="branch").fidelity == "full"


def test_forged_or_stale_checkpoint_cannot_adopt_different_journal(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    receipt = reserve(controller)
    checkpoint = controller.checkpoint_state()
    settle(controller, receipt, {"token": 3})
    restored = HierarchicalBudget(controller.options, STAMP, controller.store)
    with pytest.raises(BudgetError, match="differs"):
        restored.restore_state(checkpoint)
    assert restored.state()["global"]["committed"] == {"token": 0}
    mismatch = HierarchicalBudget(controller.options, replace(STAMP, model_version="other-model"), controller.store)
    with pytest.raises(BudgetError, match="configuration"):
        mismatch.restore_from_journal()


def test_journal_integrity_and_exact_reservation_binding_are_rechecked(tmp_path):
    controller = budget(tmp_path, options({"token": 10}))
    reserve(controller)
    rows = list(controller.store.read())
    rows[0]["payload"]["data"]["intent"]["direction_id"] = "forged-direction"
    controller.store.path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    restored = HierarchicalBudget(controller.options, STAMP, controller.store)
    with pytest.raises(BudgetError, match="integrity"):
        restored.restore_from_journal()
    assert restored.state()["global"]["committed"] == {"token": 0}


def test_failed_journal_append_never_changes_in_memory_budget(tmp_path):
    class BrokenStore(AppendOnlyStore):
        def append(self, kind, payload):
            raise OSError("durable evidence unavailable")
    controller = HierarchicalBudget(options({"token": 10}), STAMP, BrokenStore(tmp_path / "broken.jsonl"))
    before = controller.checkpoint_state()
    with pytest.raises(OSError):
        reserve(controller)
    assert controller.checkpoint_state() == before and not controller.store.path.exists()


@pytest.mark.parametrize("change", ["unknown_unit", "missing_reservation_unit", "negative", "fractional_count", "foreign_split", "implicit_patience"])
def test_invalid_configuration_fails_before_any_constructor_side_effect(tmp_path, change):
    config = options()
    if change == "unknown_unit":
        config["limits"]["global"]["magic_coin"] = 1
    elif change == "missing_reservation_unit":
        del config["reservation"]["gpu_hours"]
    elif change == "negative":
        config["limits"]["candidate"]["token"] = -1
    elif change == "fractional_count":
        config["reservation"]["eval_count"] = 0.5
    elif change == "foreign_split":
        config["fidelity_rungs"][0]["split_id"] = "final_audit"
    else:
        config["convergence"] = {"patience": 2}
    store = AppendOnlyStore(tmp_path / "budget.jsonl")
    with pytest.raises(BudgetError):
        HierarchicalBudget(config, STAMP, store)
    assert not store.path.exists()
