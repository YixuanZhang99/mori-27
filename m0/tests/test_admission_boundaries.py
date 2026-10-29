"""Native execution and recovery preserve evidence identities and measured costs."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.types import EvalResult, ItemResult
from core.executor.m0 import (_batch_evaluation_operation, _marker_sha256,
                              inprocess_evaluation_operation_state)
from core.llm import UsageError
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import RunCheckpoint
from core.x1.store import AppendOnlyStore


class MeteredLLM:
    supplier = "offline-test"
    model = "boundary-test-v1"

    def __init__(self, usage=0):
        self.usage = usage

    def __call__(self, _prompt):
        if self.usage is not None:
            self.last_usage = {"total_tokens": self.usage}
        return "candidate prompt"


class MeteredEvaluator:
    evaluator_version = "boundary-test-v1"

    def __init__(self, mutation=None, *, mutate_after=0, usage=0, unknown_after=None):
        self.mutation = mutation
        self.mutate_after = mutate_after
        self.usage = usage
        self.unknown_after = unknown_after
        self.calls = 0

    def __call__(self, candidate_id, head_sha, _prompt):
        self.calls += 1
        if self.unknown_after is None or self.calls <= self.unknown_after:
            self.last_usage = {"total_tokens": self.usage}
        result = EvalResult(candidate_id, head_sha, [ItemResult("item", 1)],
                            text_feedback="feedback", evaluator_version=self.evaluator_version)
        if self.mutation is not None and self.calls > self.mutate_after:
            self.mutation(result)
        return result


MUTATIONS = [
    lambda result: setattr(result, "candidate_id", "foreign-candidate"),
    lambda result: setattr(result, "head_sha", "foreign-head"),
    lambda result: setattr(result, "evaluator_version", "undeclared-version"),
    lambda result: result.items.append(ItemResult("item", 1)),
]
MUTATION_IDS = ["candidate", "head", "version", "duplicate-item"]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=MUTATION_IDS)
def test_sequential_evaluator_result_is_bound_before_genesis_admission(tmp_path, mutation):
    framework = Framework(MeteredLLM(), MeteredEvaluator(mutation),
                          LoopConfig(max_generations=0), str(tmp_path))
    with pytest.raises(RuntimeError, match="genesis proposal failed"):
        framework.evolve("boundary test")
    assert not list(framework.store.read("receipt"))
    outcome = list(framework.store.read("m0_evaluation_outcome"))[-1]["payload"]
    assert outcome["status"] == "failed_to_run"
    assert outcome["result"] is None


@pytest.mark.parametrize("mutation", MUTATIONS, ids=MUTATION_IDS)
def test_batch_evaluator_result_is_bound_before_admission(tmp_path, mutation):
    framework = Framework(MeteredLLM(), MeteredEvaluator(mutation, mutate_after=1),
                          LoopConfig(max_generations=1, batch_size=2), str(tmp_path))
    result = framework.evolve("boundary test")
    assert len(result["accepted_candidate_ids"]) == 1
    settled = list(framework.store.read("batch_execution_settled"))
    assert len(settled) == 2
    assert all(row["payload"]["status"] == "failed_to_run" for row in settled)
    assert len(list(framework.store.read("receipt"))) == 1


@pytest.mark.parametrize("batch_size", [1, 2])
def test_explicit_zero_cost_remains_zero_in_execution_and_resume(tmp_path, batch_size):
    config = LoopConfig(max_generations=1, batch_size=batch_size, stop_after_generation=0)
    first = Framework(MeteredLLM(), MeteredEvaluator(), config, str(tmp_path))
    assert sum(first.evolve("zero cost")["ledger"]["spent"].values()) == 0
    resumed = Framework(MeteredLLM(), MeteredEvaluator(),
                        LoopConfig(max_generations=1, batch_size=batch_size,
                                   resume_from_checkpoint=True), str(tmp_path))
    assert sum(resumed.evolve("zero cost")["ledger"]["spent"].values()) == 0
    settlements = [row["payload"] for row in resumed.store.read("ledger")
                   if row["payload"].get("entry_kind") == "settle"]
    assert settlements and all(row["settled"] == 0 for row in settlements)


@pytest.mark.parametrize("batch_size", [1, 2])
def test_failed_apply_charges_only_the_proposer_without_consuming_pending_evaluator(tmp_path,
                                                                                   batch_size):
    class ApplyFailureLLM(MeteredLLM):
        def __call__(self, prompt):
            self.last_usage = {"total_tokens": 3}
            if prompt.startswith("[draft"):
                return "<EVOLVE-BLOCK>original</EVOLVE-BLOCK>"
            return ""  # The deterministic patcher rejects an empty block.

    evaluator = MeteredEvaluator()
    framework = Framework(ApplyFailureLLM(), evaluator,
                          LoopConfig(max_generations=1, batch_size=batch_size),
                          str(tmp_path), improve_impl="llm_evolve_block")
    framework.evolve("failed apply")
    assert evaluator.calls == 1
    settlements = [row["payload"] for row in framework.store.read("ledger")
                   if row["payload"].get("entry_kind") == "settle"]
    assert len(settlements) == 1 + batch_size
    assert all(row["settled"] == 3 for row in settlements)


@pytest.mark.parametrize("batch_size", [1, 2])
def test_shared_llm_evaluator_usage_is_consumed_once(tmp_path, batch_size):
    llm = MeteredLLM(3)

    class SharedLLMEvaluator(MeteredEvaluator):
        def __call__(self, candidate_id, head_sha, prompt):
            llm("evaluate candidate")
            # The shared LLM owns the provider meter; this local wrapper costs 0.
            return super().__call__(candidate_id, head_sha, prompt)

    framework = Framework(llm, SharedLLMEvaluator(),
                          LoopConfig(max_generations=1, batch_size=batch_size), str(tmp_path))
    framework.evolve("shared llm")
    settlements = [row["payload"] for row in framework.store.read("ledger")
                   if row["payload"].get("entry_kind") == "settle"]
    assert len(settlements) == 1 + batch_size
    assert all(row["settled"] == 6 for row in settlements)


@pytest.mark.parametrize("source", ["proposer", "evaluator"])
def test_unknown_sequential_usage_leaves_reserve_open(tmp_path, source):
    llm = MeteredLLM(None if source == "proposer" else 0)
    evaluator = MeteredEvaluator(unknown_after=0 if source == "evaluator" else None)
    framework = Framework(llm, evaluator, LoopConfig(max_generations=0), str(tmp_path))
    with pytest.raises(UsageError):
        framework.evolve("unknown cost")
    rows = [row["payload"] for row in framework.store.read("ledger")]
    assert [row["entry_kind"] for row in rows] == ["reserve"]
    assert not list(framework.store.read("receipt"))


def test_unknown_batch_usage_is_not_converted_into_zero_cost_failure(tmp_path):
    framework = Framework(MeteredLLM(), MeteredEvaluator(unknown_after=1),
                          LoopConfig(max_generations=1, batch_size=2), str(tmp_path))
    with pytest.raises(UsageError):
        framework.evolve("unknown batch cost")
    assert not list(framework.store.read("batch_execution_settled"))
    rows = [row["payload"] for row in framework.store.read("ledger")]
    assert sum(row["entry_kind"] == "settle" for row in rows) == 1  # genesis only
    assert not any(row["entry_kind"] == "reserve_released" for row in rows)
    assert len(list(framework.store.read("receipt"))) == 1


@pytest.mark.parametrize("mutation", MUTATIONS, ids=MUTATION_IDS)
def test_checkpoint_native_result_is_validated_and_bound_on_restore(tmp_path, mutation):
    config = LoopConfig(max_generations=1, stop_after_generation=0)
    Framework(MeteredLLM(), MeteredEvaluator(), config, str(tmp_path)).evolve("restore")
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = RunCheckpoint.load(checkpoint_path)
    data = checkpoint.payload["pool"][0]["result"]
    native = EvalResult(**{**data, "items": [ItemResult(**item) for item in data["items"]]})
    mutation(native)
    checkpoint.payload["pool"][0]["result"] = asdict(native)
    RunCheckpoint.create(checkpoint.payload).save(checkpoint_path)
    restored = Framework(MeteredLLM(), MeteredEvaluator(),
                         LoopConfig(max_generations=1, resume_from_checkpoint=True),
                         str(tmp_path))
    with pytest.raises(ValueError, match="binding mismatch|unique"):
        restored.evolve("restore")


@pytest.mark.parametrize("case", ["wrong-version", "duplicate-item", "unknown-cost"])
def test_restored_batch_native_outcome_cannot_bypass_validation(tmp_path, case):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    context = {"cohort_id": "cohort", "proposal": {"proposal_id": "candidate"},
               "head_sha": "head", "generation": 1, "operator": "improve"}
    operation = _batch_evaluation_operation(context)
    native = EvalResult("candidate", "head", [ItemResult("item", 1)],
                        evaluator_version="version-1")
    if case == "duplicate-item":
        native.items.append(ItemResult("item", 1))
    store.append("m0_batch_evaluation_started", operation)
    store.append("m0_evaluation_outcome", {
        "schema_version": 1, "adapter": "in_process", "execution_ref": "cohort",
        "execution_id": operation["execution_id"], "candidate_id": "candidate",
        "generation": 1, "operator": "improve", "status": "ok", "detail": "done",
        "start_sha256": _marker_sha256(operation),
        "evaluation_sha256": _marker_sha256(context), "result": asdict(native),
        "token_usage": None if case == "unknown-cost" else {"total_tokens": 0}})
    with pytest.raises(UsageError if case == "unknown-cost" else RuntimeError):
        inprocess_evaluation_operation_state(
            store, "cohort", {"candidate": context},
            evaluator_version="version-2" if case == "wrong-version" else "version-1")
