"""Portable regressions for content-bound evaluation and durable restoration."""
import copy
import json
from dataclasses import asdict, replace

import pytest

from core.eval.cascade import CascadingEvaluator
from core.eval.types import (EvalResult, ItemResult, validate_eval_comparison,
                             validate_eval_result)
from core.executor.external import ExternalCommandEvaluator, ExternalEvaluatorError
from core.executor.m0 import (_batch_evaluation_operation, _marker_sha256,
                              _restore_m0_result, inprocess_evaluation_operation_state)
from core.loop import Framework, LoopConfig
from core.tasks.gsm8k import GSM8KEvaluator
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM


class Solver:
    def __init__(self):
        self.model = "model-v1"
        self.supplier = "local"
        self.temperature = 0.0
        self.base_url = "https://solver.example/v1"
        self.api_key = "credential"
        self.last_usage = {"total_tokens": 0}
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        self.last_usage = {"total_tokens": 5}
        return "#### 0" if prompt.startswith("fail\n") else "#### 2"


def dataset():
    return [{"question": "one plus one?", "gold": 2},
            {"question": "two plus two?", "gold": 4}]


def test_dataset_inputs_and_public_view_cannot_change_frozen_evaluation():
    items = dataset()
    evaluator = GSM8KEvaluator(items, Solver())
    context = evaluator.evaluation_context
    items[0]["question"] = "changed"
    items[0]["gold"] = 999
    items.reverse()
    items.clear()
    view = evaluator.items
    view[0]["gold"] = 999
    view.clear()
    result = evaluator("candidate", "head", "solve")
    assert evaluator.items == dataset()
    assert result.evaluation_context == context
    assert [item.verdict for item in result.items] == [1, 0]
    assert "one plus one?" in evaluator.solver_llm.calls[0]
    assert copy.deepcopy(evaluator).evaluation_context == context


@pytest.mark.parametrize("change", ["question", "gold", "order", "model", "temperature",
                                     "supplier", "endpoint", "api_version"])
def test_same_version_and_item_ids_do_not_hide_changed_evaluation_content(change):
    original = GSM8KEvaluator(dataset(), Solver())
    items, solver = dataset(), Solver()
    if change == "question":
        items[0]["question"] = "a different problem"
    elif change == "gold":
        items[0]["gold"] = 3
    elif change == "order":
        items.reverse()
    elif change == "endpoint":
        solver.base_url = "https://different.example/v1"
    elif change == "api_version":
        solver.base_url += "?api-version=2026-01-01"
    else:
        setattr(solver, change, 0.7 if change == "temperature" else "different")
    changed = GSM8KEvaluator(items, solver)
    left = original("candidate", "head", "solve")
    right = changed("candidate", "head", "solve")
    assert left.evaluator_version == right.evaluator_version == "gsm8k-det-v1"
    assert [item.item_id for item in left.items] == [item.item_id for item in right.items]
    assert left.evaluation_context != right.evaluation_context
    with pytest.raises(ValueError, match="same evaluation context"):
        validate_eval_comparison(left, right)


def test_normalized_gold_and_credentials_do_not_change_content_identity():
    first, second = Solver(), Solver()
    first.base_url = "https://user:secret@solver.example/v1/?api_key=old&api-version=v1"
    second.base_url = "https://other:new@solver.example/v1?api_key=new&api-version=v1"
    second.api_key = "rotated"
    items = dataset()
    items[0]["gold"] = 2.0
    assert GSM8KEvaluator(dataset(), first).evaluation_context == \
        GSM8KEvaluator(items, second).evaluation_context


@pytest.mark.parametrize("items", [[], [{"question": "", "gold": 1}],
                                      [{"question": "q", "gold": True}],
                                      [{"question": "q", "gold": float("inf")}],
                                      [{"question": "q", "gold": float("nan")}],
                                      [{"question": "q", "gold": "1"}]])
def test_invalid_dataset_is_rejected_before_solver_invocation(items):
    solver = Solver()
    with pytest.raises(ValueError):
        GSM8KEvaluator(items, solver)
    assert solver.calls == []


@pytest.mark.parametrize("setting", ["model", "temperature", "declared"])
def test_changed_solver_configuration_fails_before_paid_call(setting):
    solver = Solver()
    solver.evaluation_identity = {"decoding": {"mode": "original"}}
    evaluator = GSM8KEvaluator(dataset(), solver)
    if setting == "declared":
        solver.evaluation_identity["decoding"]["mode"] = "changed"
    else:
        setattr(solver, setting, 0.8 if setting == "temperature" else "changed")
    with pytest.raises(ValueError, match="configuration changed"):
        evaluator("candidate", "head", "solve")
    assert solver.calls == []
    assert evaluator.last_usage == {"total_tokens": 0}


def test_pure_custom_identity_hook_is_bound_and_incall_drift_keeps_usage():
    class CustomSolver(Solver):
        def evaluation_identity(self):
            return {"revision": self.revision}

        def __call__(self, prompt):
            output = super().__call__(prompt)
            self.revision += 1
            return output

    solver = CustomSolver()
    solver.revision = 1
    evaluator = GSM8KEvaluator(dataset(), solver)
    with pytest.raises(ValueError, match="configuration changed during"):
        evaluator("candidate", "head", "solve")
    assert len(solver.calls) == 1
    assert evaluator.last_usage == {"total_tokens": 5}


def test_cascade_preserves_full_dataset_context_for_shallow_evidence():
    base = GSM8KEvaluator(dataset(), Solver())
    cascade = CascadingEvaluator(base, shallow_items=1)
    full = cascade("good", "head", "solve")
    shallow = cascade("bad", "head", "fail")
    assert shallow.private["cascade_stopped"] is True
    assert shallow.evaluation_context == full.evaluation_context
    assert full.evaluation_context == cascade.evaluation_context == base.evaluation_context
    assert base("short", "head", "solve", item_limit=1).evaluation_context == \
        full.evaluation_context


@pytest.mark.parametrize("value", [None, 1, "v1", "sha256:" + "A" * 64])
def test_malformed_context_cannot_enter_comparison_or_restore(value):
    result = EvalResult("candidate", "head", [ItemResult("item", 1)],
                        evaluation_context=value)
    with pytest.raises(ValueError, match="evaluation_context"):
        validate_eval_result(result)
    with pytest.raises(ValueError, match="evaluation_context"):
        _restore_m0_result(asdict(result))


def test_native_restore_preserves_context_and_rejects_missing_or_mismatched_binding():
    result = GSM8KEvaluator(dataset(), Solver())("candidate", "head", "solve")
    payload = asdict(result)
    restored = _restore_m0_result(payload, evaluation_context=result.evaluation_context)
    assert restored == result
    with pytest.raises(ValueError, match="binding mismatch"):
        _restore_m0_result(payload, evaluation_context="sha256:" + "0" * 64)
    del payload["evaluation_context"]
    assert _restore_m0_result(payload).evaluation_context == ""
    with pytest.raises(ValueError, match="binding mismatch"):
        _restore_m0_result(payload, evaluation_context=result.evaluation_context)
    with pytest.raises(ValueError, match="same evaluation context"):
        validate_eval_comparison(result, replace(result, evaluation_context=""))


def test_batch_outcome_adoption_requires_the_original_evaluation_content(tmp_path):
    store = AppendOnlyStore(tmp_path / "journal.jsonl")
    result = GSM8KEvaluator(dataset(), Solver())("candidate", "head", "solve")
    context = {"cohort_id": "cohort", "proposal": {"proposal_id": "candidate"},
               "head_sha": "head", "generation": 1, "operator": "improve"}
    operation = _batch_evaluation_operation(context)
    store.append("m0_batch_evaluation_started", operation)
    store.append("m0_evaluation_outcome", {
        "schema_version": 1, "adapter": "in_process", "execution_ref": "cohort",
        "candidate_id": "candidate", "execution_id": operation["execution_id"],
        "generation": 1, "operator": "improve", "status": "ok", "detail": "done",
        "start_sha256": _marker_sha256(operation),
        "evaluation_sha256": _marker_sha256(context),
        "token_usage": {"total_tokens": 10}, "result": asdict(result)})
    kwargs = {"evaluator_version": result.evaluator_version,
              "evaluation_context": result.evaluation_context}
    assert inprocess_evaluation_operation_state(
        store, "cohort", {"candidate": context}, **kwargs)["missing"] == []
    kwargs["evaluation_context"] = "sha256:" + "0" * 64
    with pytest.raises(RuntimeError, match="differs from its start"):
        inprocess_evaluation_operation_state(store, "cohort", {"candidate": context}, **kwargs)


def test_external_live_and_recovered_results_preserve_configured_context(tmp_path):
    result = GSM8KEvaluator(dataset(), Solver())("candidate", "head", "solve")
    store = AppendOnlyStore(tmp_path / "journal.jsonl")
    adapter = ExternalCommandEvaluator(["unused"], tmp_path, store, sandbox=False,
                                       evaluation_context=result.evaluation_context)
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    request.write_text("{}")
    record = {"execution_id": "execution", "candidate_id": "candidate", "head_sha": "head",
              "request_path": str(request), "response_path": str(response)}
    response.write_text(json.dumps({"schema_version": 1, "result": asdict(result),
                                    "token_usage": {"total_tokens": 10}}))
    assert adapter._complete_process(record, {"timeout": False, "returncode": 0,
                                              "stderr": "", "stdout": ""}) == result
    assert adapter.outcome(record)["result"] == result
    clone = adapter.fork(tmp_path / "replay", AppendOnlyStore(tmp_path / "replay.jsonl"))
    assert clone.evaluation_context == result.evaluation_context
    adapter = ExternalCommandEvaluator(["unused"], tmp_path, store, sandbox=False,
                                       evaluation_context="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="binding mismatch"):
        adapter.outcome(record)
    with pytest.raises(ExternalEvaluatorError, match="binding mismatch"):
        adapter._complete_process(record, {"timeout": False, "returncode": 0,
                                           "stderr": "", "stdout": ""})
    assert adapter.last_usage == {"total_tokens": 10}


def test_external_legacy_result_requires_explicit_legacy_contract():
    result = EvalResult("candidate", "head", [ItemResult("item", 1)])
    payload = asdict(result)
    del payload["evaluation_context"]
    assert ExternalCommandEvaluator._result(payload, "candidate", "head", "") == result
    with pytest.raises(ValueError, match="binding mismatch"):
        ExternalCommandEvaluator._result(payload, "candidate", "head", "sha256:" + "0" * 64)


class Proposer(MockLLM):
    def __init__(self):
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        return super().__call__(prompt)


def framework_config(batch_size, **changes):
    options = {"max_generations": 3, "baseline_every": 1,
               "batch_size": batch_size, "max_inflight": batch_size}
    options.update(changes)
    return LoopConfig(**options)


@pytest.mark.parametrize("batch_size", [1, 2])
@pytest.mark.parametrize("changed", ["question", "gold", "order", "model"])
def test_framework_resume_rejects_changed_content_before_calls_or_journal_writes(
        tmp_path, batch_size, changed):
    run = tmp_path / "run"
    initial = Framework(Proposer(), GSM8KEvaluator(dataset(), Solver()),
                        framework_config(batch_size, stop_after_generation=1), str(run))
    assert initial.evolve("bound arithmetic task")["completed"] is False
    original_journal = (run / "x1.jsonl").read_bytes()
    original_checkpoint = (run / "checkpoint.json").read_bytes()
    items, solver, proposer = dataset(), Solver(), Proposer()
    if changed == "question":
        items[0]["question"] = "new content under the same index"
    elif changed == "gold":
        items[0]["gold"] = 10
    elif changed == "order":
        items.reverse()
    else:
        solver.model = "another model"
    resumed = Framework(proposer, GSM8KEvaluator(items, solver),
                        framework_config(batch_size, resume_from_checkpoint=True), str(run))
    with pytest.raises(ValueError, match="evaluation context.*resume"):
        resumed.evolve("bound arithmetic task")
    assert proposer.calls == solver.calls == []
    assert (run / "x1.jsonl").read_bytes() == original_journal
    assert (run / "checkpoint.json").read_bytes() == original_checkpoint


@pytest.mark.parametrize("batch_size", [1, 2])
def test_framework_same_content_resume_and_replay_keep_every_binding(tmp_path, batch_size):
    task = "bound arithmetic task"
    reference = Framework(Proposer(), GSM8KEvaluator(dataset(), Solver()),
                          framework_config(batch_size), str(tmp_path / "reference"))
    expected = reference.evolve(task)
    run = tmp_path / "resumed"
    Framework(Proposer(), GSM8KEvaluator(dataset(), Solver()),
              framework_config(batch_size, stop_after_generation=1), str(run)).evolve(task)
    proposer, solver = Proposer(), Solver()
    evaluator = GSM8KEvaluator(dataset(), solver)
    resumed = Framework(proposer, evaluator,
                        framework_config(batch_size, resume_from_checkpoint=True), str(run))
    actual = resumed.evolve(task)
    for key in ("best_prompt", "best_score", "accepted_candidate_ids", "main_scores",
                "baseline_scores", "ledger", "governance_audit", "governed_state"):
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    starts = list(resumed.store.read("run_start"))
    assert len(starts) == 1
    assert starts[0]["payload"]["evaluation_context"] == evaluator.evaluation_context
    outcomes = [row["payload"] for row in resumed.store.read("m0_evaluation_outcome")]
    assert outcomes and all(outcome["result"]["evaluation_context"] ==
                            evaluator.evaluation_context for outcome in outcomes)
    calls_before_replay = (list(proposer.calls), list(solver.calls))
    replayed = resumed.replay()
    assert replayed["best_prompt"] == expected["best_prompt"]
    assert resumed.inspect()["replay_certificate"]["passed"] is True
    assert (proposer.calls, solver.calls) == calls_before_replay


@pytest.mark.parametrize("cascade", [False, True])
@pytest.mark.parametrize("batch_size", [1, 2])
def test_resumed_evaluator_rejects_mutated_solver_before_proposal(tmp_path, batch_size, cascade):
    run = tmp_path / "run"
    solver = Solver()
    evaluator = GSM8KEvaluator(dataset(), solver)
    if cascade:
        evaluator = CascadingEvaluator(evaluator, shallow_items=1)
    initial = Framework(Proposer(), evaluator,
                        framework_config(batch_size, stop_after_generation=1), str(run))
    initial.evolve("bound arithmetic task")
    original_journal = (run / "x1.jsonl").read_bytes()
    calls_before = list(solver.calls)
    pinned_context = evaluator.evaluation_context
    solver.model = "mutated after construction"
    proposer = Proposer()
    resumed = Framework(proposer, evaluator,
                        framework_config(batch_size, resume_from_checkpoint=True), str(run))
    with pytest.raises(ValueError, match="configuration changed"):
        resumed.evolve("bound arithmetic task")
    assert evaluator.evaluation_context == pinned_context
    assert proposer.calls == [] and solver.calls == calls_before
    assert (run / "x1.jsonl").read_bytes() == original_journal
