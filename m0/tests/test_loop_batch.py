"""v21 opt-in M0 frozen-cohort scheduling through canonical BatchScheduler."""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator

TASK = "M0 frozen cohort integration"
COMPARE = ("best_prompt", "best_score", "self_attestation", "governance_audit",
           "main_scores", "baseline_scores",
           "accepted_candidate_ids", "generations", "ledger", "health",
           "governed_state")


def config(**kwargs):
    values = dict(max_generations=3, batch_size=3, max_inflight=3,
                  baseline_every=2)
    values.update(kwargs)
    return LoopConfig(**values)


def test_framework_executes_real_frozen_cohorts_and_resident_control(tmp_path):
    fw = Framework(MockLLM(), toy_evaluator, config(), str(tmp_path))
    out = fw.evolve(TASK)
    completed = list(fw.store.read("batch_cycle_completed"))
    assert len(completed) == 3
    assert all(len(record["payload"]["candidate_ids"]) == 3 for record in completed)
    assert len(list(fw.store.read("executor_pool_started"))) == 9
    improves = [f for f in out["funnels"] if f.operator == "improve"]
    assert [(f.proposed, f.applicable, f.runnable) for f in improves] == [(3, 3, 3)] * 3
    assert out["governed_state"]["frontier_nodes"] == 10
    assert out["governed_state"]["baseline_in_frontier"] is False
    assert len(out["baseline_scores"]) == 1
    assert fw.inspect()["accepted_receipt_coverage"] is True


class AdversarialEvaluator:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def __call__(self, candidate_id, head_sha, prompt):
        verdicts, score = self.outcomes[candidate_id]
        return EvalResult(candidate_id=candidate_id, head_sha=head_sha,
                          items=[ItemResult(f"i{index}", verdict)
                                 for index, verdict in enumerate(verdicts)],
                          combined_score=score, text_feedback="frozen cohort feedback",
                          reliability=ReliabilityMeta(n_trials=1))


def test_same_cohort_gate_uses_frozen_incumbent_and_never_score_rank(tmp_path):
    probe = Framework(MockLLM(), toy_evaluator, config(max_generations=1, batch_size=2),
                      str(tmp_path / "probe"))
    genesis = probe._proposal_id(TASK, "genesis")
    high_loss = probe._proposal_id(TASK, "improve:1:0")
    low_win = probe._proposal_id(TASK, "improve:1:1")
    evaluator = AdversarialEvaluator({
        genesis: ([1, 0], 0.5), high_loss: ([0, 1], 0.99), low_win: ([1, 1], 0.1)})
    fw = Framework(MockLLM(), evaluator, config(max_generations=1, batch_size=2),
                   str(tmp_path / "run"))
    out = fw.evolve(TASK)
    assert high_loss not in out["accepted_candidate_ids"]
    assert low_win in out["accepted_candidate_ids"]
    signals = {record["payload"]["candidate_id"]: record["payload"]["signals_snapshot"]
               for record in fw.store.read("gate_evidence")}
    assert signals[high_loss]["F"] == signals[high_loss]["B"] == 1
    assert signals[low_win]["F"] == 1 and signals[low_win]["B"] == 0
    assert out["best_score"] == 0.5


class MeteredLLM:
    def __init__(self):
        self.base = MockLLM()
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt):
        response = self.base(prompt)
        self.last_usage = {"total_tokens": 3}
        return response


class MeteredEvaluator:
    def __init__(self, fail_id=None):
        self.last_usage = {"total_tokens": 0}
        self.fail_id = fail_id
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, candidate_id, head_sha, prompt):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        if candidate_id == self.fail_id:
            with self.lock:
                self.active -= 1
            self.last_usage = {"total_tokens": 5}
            raise RuntimeError("injected evaluator failure")
        result = toy_evaluator(candidate_id, head_sha, prompt)
        self.last_usage = {"total_tokens": 5}
        with self.lock:
            self.active -= 1
        return result


def test_shared_global_meter_is_serialized_and_settled_exactly(tmp_path):
    evaluator = MeteredEvaluator()
    fw = Framework(MeteredLLM(), evaluator, config(max_generations=2), str(tmp_path))
    fw.evolve(TASK)
    settled = list(fw.store.read("batch_execution_settled"))
    assert len(settled) == 6
    assert {record["payload"]["actual_token_cost"] for record in settled} == {8}
    assert evaluator.max_active == 1
    intents = [record["payload"]["intent_id"] for record in settled]
    assert len(set(intents)) == 6
    assert not list(fw.store.read("batch_budget_rejected"))


def test_failed_candidate_is_settled_pruned_and_excluded_from_funnel_runnable(tmp_path):
    probe = Framework(MockLLM(), toy_evaluator, config(max_generations=1),
                      str(tmp_path / "probe"))
    failed = probe._proposal_id(TASK, "improve:1:1")
    evaluator = MeteredEvaluator(fail_id=failed)
    fw = Framework(MeteredLLM(), evaluator, config(max_generations=1), str(tmp_path / "run"))
    out = fw.evolve(TASK)
    improve = next(f for f in out["funnels"] if f.operator == "improve")
    assert (improve.proposed, improve.applicable, improve.runnable) == (3, 3, 2)
    assert failed in out["governed_state"]["pruned_ids"]
    assert failed not in out["accepted_candidate_ids"]
    evidence = [record["payload"] for record in fw.store.read("batch_execution_settled")
                if record["payload"]["candidate_id"] == failed]
    assert len(evidence) == 1 and evidence[0]["status"] == "failed_to_run"
    assert evidence[0]["actual_token_cost"] == 8
    assert failed not in {record["payload"]["candidate_id"]
                          for record in fw.store.read("gate_evidence")}


def test_batch_checkpoint_resume_and_replay_match_uninterrupted_control(tmp_path):
    reference = Framework(MockLLM(), toy_evaluator,
                          config(max_generations=4), str(tmp_path / "reference"))
    expected = reference.evolve(TASK)
    partial = Framework(MockLLM(), toy_evaluator,
                        config(max_generations=4, stop_after_generation=1),
                        str(tmp_path / "resumed"))
    partial.evolve(TASK)
    resumed_fw = Framework(MockLLM(), toy_evaluator,
                           config(max_generations=4, resume_from_checkpoint=True),
                           str(tmp_path / "resumed"))
    actual = resumed_fw.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert len(list(resumed_fw.store.read("batch_cycle_completed"))) == 4
    assert len(list(resumed_fw.store.read("executor_pool_started"))) == 12
    replay = resumed_fw.replay()
    for key in COMPARE:
        assert replay[key] == expected[key], key


def test_budget_shrinks_cohort_atomically_and_legacy_path_stays_unchanged(tmp_path):
    fw = Framework(MockLLM(), toy_evaluator,
                   config(total_budget=3_000, intent_cost=1_000, reeval_floor=100,
                          max_generations=4, batch_size=3), str(tmp_path / "budget"))
    out = fw.evolve(TASK)
    started = list(fw.store.read("batch_cycle_started"))
    assert len(started) == 1 and len(started[0]["payload"]["candidate_ids"]) == 1
    assert sum(out["ledger"]["spent"].values()) <= 3_000
    assert not list(fw.store.read("batch_budget_rejected"))

    legacy = Framework(MockLLM(), toy_evaluator,
                       LoopConfig(max_generations=2, batch_size=1),
                       str(tmp_path / "legacy"))
    legacy.evolve(TASK)
    assert not list(legacy.store.read("batch_cycle_started"))


@pytest.mark.parametrize("field", ["batch_size", "max_inflight"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_batch_configuration_validation(tmp_path, field, value):
    cfg = LoopConfig(**{field: value})
    with pytest.raises(ValueError, match="positive integer"):
        Framework(MockLLM(), toy_evaluator, cfg, str(tmp_path)).evolve(TASK)
