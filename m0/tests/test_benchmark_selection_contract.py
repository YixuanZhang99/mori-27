"""Selection semantics and physical-cost coverage for measured comparisons.

All records are protocol fixtures, not external benchmark results.
"""
from dataclasses import asdict, replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tasks.benchmark import (BenchmarkRunRecord, ScoreRunRecord,
                                  SelectionCandidate, SelectionContract, SelectionReceipt,
                                  compare_same_budget, compare_scores_same_budget)

SINGLE = SelectionContract("single_run", "official-final-v1", "test")


def receipt_for(selection, candidate_id, evidence_ref):
    pooled = selection.selection_object != "single_run"
    candidate = SelectionCandidate(
        candidate_id, evidence_ref, validation_score=1.0 if pooled else None,
        chain_id="chain" if selection.selection_object == "best_single_chain" else None,
        terminal=pooled)
    return SelectionReceipt(selection, (candidate,), candidate_id)


def score_run(task, seed, arm, selection=SINGLE, budget=None, actual_costs=None):
    return ScoreRunRecord(
        benchmark="selection-fixture", task_list_sha256="locked", task_id=task,
        seed=seed, arm=arm, backbone="same-model",
        budget=budget or {"wallclock": 10, "token": 100},
        actual_costs=actual_costs or {"wallclock": 8, "token": 80}, score=float(seed),
        evidence_refs=(f"audit://{arm}/{task}/{seed}",), measured=True,
        selection=selection,
        selection_receipt=(receipt_for(selection, f"{arm}:{task}:{seed}",
                                       f"audit://{arm}/{task}/{seed}")
                           if selection is not None else None))


def medal_run(task, seed, arm, selection=SINGLE, budget=None, actual_costs=None):
    return BenchmarkRunRecord(
        benchmark="selection-fixture", task_list_sha256="locked", task_id=task,
        seed=seed, arm=arm, backbone="same-model",
        budget=budget or {"wallclock": 10}, actual_costs=actual_costs or {"wallclock": 8},
        valid_submission=True, any_medal=False,
        evidence_refs=(f"audit://{arm}/{seed}",), measured=True, selection=selection,
        selection_receipt=receipt_for(selection, f"{arm}:{seed}", f"audit://{arm}/{seed}"))


def paired(factory=score_run, selection=SINGLE):
    return ([factory(1, seed, "host", selection) for seed in (1, 2, 3)],
            [factory(1, seed, "governed", selection) for seed in (1, 2, 3)])


@pytest.mark.parametrize("selection_object", [
    "single_run", "archive_best", "best_single_chain"])
def test_explicit_selection_objects_are_preserved_in_comparison_reports(selection_object):
    selection = SelectionContract(selection_object, "declared-selector-v2", "held-out")
    host, governed = paired(selection=selection)
    report = compare_scores_same_budget(host, governed, 0)
    assert report.selection == selection
    assert asdict(report)["selection"] == asdict(selection)
    assert report.declared_cost_units == ("token", "wallclock")
    assert report.actual_cost_units == ("token", "wallclock")


@pytest.mark.parametrize("field,value", [
    ("selection_object", "archive_best"),
    ("policy", "different-selector-v2"),
    ("split", "different-held-out"),
])
def test_paired_comparison_rejects_any_selection_contract_fork(field, value):
    host, governed = paired()
    forked = replace(governed[0].selection, **{field: value})
    governed[0] = replace(
        governed[0], selection=forked,
        selection_receipt=receipt_for(forked, governed[0].selection_receipt.selected_candidate_id,
                                      governed[0].evidence_refs[0]))
    with pytest.raises(ValueError, match="one identical selection contract"):
        compare_scores_same_budget(host, governed, 0)


def test_medal_comparison_uses_the_same_selection_contract_guard():
    host, governed = paired(medal_run)
    forked = SelectionContract("best_single_chain", "official-final-v1", "test")
    governed[0] = replace(
        governed[0], selection=forked,
        selection_receipt=receipt_for(forked, governed[0].selection_receipt.selected_candidate_id,
                                      governed[0].evidence_refs[0]))
    with pytest.raises(ValueError, match="one identical selection contract"):
        compare_same_budget(host, governed, 0)


@pytest.mark.parametrize("selection,message", [
    (None, "explicit selection contract"),
    (SelectionContract("other", "selector-v1", "test"), "selection_object"),
    (SelectionContract("single_run", "", "test"), "policy"),
    (SelectionContract("single_run", "selector-v1", " "), "split"),
])
def test_measured_records_require_a_valid_explicit_selection_contract(selection, message):
    with pytest.raises(ValueError, match=message):
        score_run(1, 1, "host", selection).validate_measured()


def test_declared_budget_units_require_actual_measurements_not_implicit_zero():
    record = score_run(1, 1, "host", actual_costs={"wallclock": 8})
    with pytest.raises(ValueError, match="missing declared budget units: token"):
        record.validate_measured()


def test_matrix_rejects_declared_cost_unit_set_forks():
    host, governed = paired()
    governed[0] = replace(governed[0], budget={"wallclock": 10},
                          actual_costs={"wallclock": 8})
    with pytest.raises(ValueError, match="identical declared and actual cost-unit sets"):
        compare_scores_same_budget(host, governed, 0)


def test_matrix_rejects_actual_cost_unit_set_forks():
    host, governed = paired()
    governed[0] = replace(governed[0], actual_costs={"wallclock": 8, "token": 80, "usd": 2})
    with pytest.raises(ValueError, match="identical declared and actual cost-unit sets"):
        compare_scores_same_budget(host, governed, 0)


def test_required_physical_cost_dimensions_are_mandatory():
    host, governed = paired()
    with pytest.raises(ValueError, match="required declared cost units: gpu_hours"):
        compare_scores_same_budget(host, governed, 0,
                                   required_cost_units={"wallclock", "gpu_hours"})


def test_extra_actual_units_are_transparent_without_efficiency_claims(tmp_path):
    host, governed = paired()
    extra = {"wallclock": 8, "token": 80, "usd": 2}
    host = [replace(run, actual_costs=extra) for run in host]
    governed = [replace(run, actual_costs=extra) for run in governed]
    report = compare_scores_same_budget(host, governed, 0,
                                        required_cost_units={"wallclock", "token"})
    assert report.actual_cost_units == ("token", "usd", "wallclock")
    assert report.actual_cost_totals["host"]["usd"] == 6
    serialized = asdict(report)
    assert "admitted_per_usd" not in serialized
    assert "cost_efficiency" not in serialized


def test_m9_gate_does_not_consume_selection_or_benchmark_cost_fields():
    gate = (Path(__file__).resolve().parents[1] / "core/eval/gate.py").read_text()
    for forbidden in ("SelectionContract", "selection_object", "actual_cost_totals",
                      "declared_cost_units", "admitted_per_usd"):
        assert forbidden not in gate
