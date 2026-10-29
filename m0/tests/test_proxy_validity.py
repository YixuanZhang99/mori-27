"""Real paired receipts, heterogeneous ranks, fail-closed state and recovery."""
import copy
import json
from dataclasses import replace

import pytest

from core.composition.contracts import Proposal
from core.composition.evaluation import (EvaluationContract, PrivateEvaluationData,
    binding_for, encode_evidence)
from core.composition.proxy import (JOURNAL_KIND, ProxyValidityController,
    proxy_options, spearman_rank_correlation)
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.x1.store import AppendOnlyStore


def options(**changes):
    return {"every_n_cycles": 1,
            "anchor_request": {"fidelity": "full", "split_id": "calibration", "seed_set": [7, 19]},
            "proxy_metric": "dev/surrogate", "true_metric": "calibration/quality",
            "proxy_direction": "maximize", "true_direction": "maximize",
            "min_pairs": 3, "window": 4, "min_rank_correlation": 0.5, **changes}


def controller(tmp_path, config=None, *, run_id="logical-run"):
    return ProxyValidityController(options() if config is None else config,
                                   AppendOnlyStore(tmp_path / "proxy.jsonl"), run_id=run_id)


def evidence(proposal, request, score, *, context=None, status=EvalStatus.OK):
    metric = "dev/surrogate" if request.split_id == "dev" else "calibration/quality"
    binding = binding_for(proposal, request, evaluator_version="offline-domain-v1",
                          evaluation_context=context or "sha256:" + ("a" if request.split_id == "dev" else "b") * 64)
    result = EvalResult(status, {metric: score} if status is EvalStatus.OK else {},
        CostVec(eval_count=1), fidelity=request.fidelity, text_feedback="DO_NOT_EXPORT_RAW_FEEDBACK",
        contract=EvaluationContract(binding, ("token", "eval_count"),
            private=PrivateEvaluationData(data={"secret": "DO_NOT_EXPORT_PRIVATE"})))
    return EvidenceRecord(proposal.candidate.id, result,
                          executor_status="scored" if status is EvalStatus.OK else "failed_to_run")


def inputs(monitor, cycle, proxy_score=1, true_score=1, *, name=None, dev_request=None):
    proposal = Proposal(Candidate(name or f"c{cycle}", created_cycle=cycle), f"artifact-{name or cycle}", CostVec())
    proxy = evidence(proposal, dev_request or EvalRequest("proxy", split_id="dev", seed_set=[1]), proxy_score)
    anchor = evidence(proposal, monitor.anchor_request, true_score)
    return proposal, proxy, anchor


def observe(monitor, cycle, proxy_score, true_score, *, role="candidate", force=False, **kwargs):
    proposal, proxy, anchor = inputs(monitor, cycle, proxy_score, true_score, **kwargs)
    plan = monitor.plan(proposal, proxy, cycle, anchor_binding=anchor.eval_result.contract.binding,
                        role=role, force=force)
    assert plan is not None
    monitor.begin(plan)
    return monitor.record(plan, anchor), plan, anchor


@pytest.mark.parametrize("change", [
    {"extra": True}, {"min_pairs": 2}, {"min_pairs": True}, {"window": 2},
    {"every_n_cycles": 0}, {"every_n_cycles": 1.5}, {"proxy_metric": ""},
    {"true_direction": "sideways"}, {"proxy_direction": []},
    {"min_rank_correlation": float("nan")}, {"min_rank_correlation": True},
    {"min_rank_correlation": 1.1}, {"anchor_request": {"fidelity": "full", "split_id": "admission"}},
    {"anchor_request": {"fidelity": "full", "split_id": "final_audit"}},
    {"anchor_request": {"fidelity": "full", "split_id": "calibration", "seed_set": [1, 1]}},
    {"anchor_request": {"fidelity": "full", "split_id": "calibration", "unknown": 3}},
])
def test_configuration_rejects_unknown_ambiguous_or_held_out_authority_before_io(tmp_path, change):
    with pytest.raises(ValueError):
        controller(tmp_path, options(**change))
    assert not (tmp_path / "proxy.jsonl").exists()


def test_configuration_requires_explicit_metrics_directions_and_is_detached(tmp_path):
    config = options()
    del config["true_metric"]
    with pytest.raises(ValueError):
        proxy_options(config)
    config = options()
    monitor = controller(tmp_path, config)
    config["anchor_request"]["seed_set"].append(99)
    exposed = monitor.options
    exposed["anchor_request"]["seed_set"].append(88)
    monitor.anchor_request.seed_set.append(77)
    assert monitor.anchor_request.seed_set == [7, 19]
    assert not monitor.store.path.exists()


def test_average_rank_spearman_handles_ties_and_undefined_values_without_false_precision():
    assert spearman_rank_correlation([1, 2, 2, 4], [1, 2, 3, 4]) == pytest.approx(0.9486832980505138)
    assert spearman_rank_correlation([1, 2, 2, 4], [4, 2, 2, 1]) == -1
    assert spearman_rank_correlation([1, 1, 1], [1, 2, 3]) is None
    assert spearman_rank_correlation([1], [2]) is None
    assert spearman_rank_correlation([], []) is None
    with pytest.raises(ValueError):
        spearman_rank_correlation([1], [1, 2])
    with pytest.raises(ValueError):
        spearman_rank_correlation([False, 1], [2, 3])


def test_first_and_periodic_anchors_with_low_sample_and_monitoring_states(tmp_path):
    monitor = controller(tmp_path, options(every_n_cycles=3))
    assert monitor.needs_anchor(0)
    first, _, _ = observe(monitor, 0, 1, 1)
    assert first.mode == "warmup" and first.rank_correlation is None and first.true_improved
    assert not monitor.needs_anchor(1)
    proposal, proxy, anchor = inputs(monitor, 1)
    before = monitor.checkpoint_state()
    assert monitor.plan(proposal, proxy, 1, anchor_binding=anchor.eval_result.contract.binding) is None
    assert monitor.checkpoint_state() == before
    second, _, _ = observe(monitor, 3, 2, 2)
    assert second.mode == "warmup" and second.rank_correlation == 1
    third, _, _ = observe(monitor, 6, 3, 3)
    assert third.mode == "monitoring" and third.valid_pairs == 3
    assert monitor.state()["statistical"] is False
    with pytest.raises(ValueError, match="rolled back"):
        monitor.needs_anchor(6)


def test_false_proxy_gain_is_bound_to_previous_comparable_true_best_and_sticky(tmp_path):
    monitor = controller(tmp_path, options(every_n_cycles=10))
    first, _, _ = observe(monitor, 0, 1, 10)
    second, _, _ = observe(monitor, 10, 3, 8)
    assert second.mode == "degraded" and second.rank_correlation == -1
    assert "proxy_improved_true_regressed" in second.alerts
    assert not second.true_improved and not monitor.allows_advancement(second.pair_id)
    feedback = second.negative_feedback
    assert feedback["baseline"]["pair_id"] == first.pair_id
    assert feedback["comparison"] == "previous_comparable_true_best"
    assert feedback["current"]["proxy_receipt_ref"] != feedback["current"]["anchor_receipt_ref"]
    assert monitor.needs_anchor(11)
    third, _, _ = observe(monitor, 11, 4, 12)
    assert third.mode == "degraded" and third.true_improved
    assert monitor.allows_advancement(third.pair_id)
    assert monitor.state()["advancement_rule"] == "true_best_only"


def test_negative_feedback_is_recomputed_from_authoritative_receipts_and_exposes_only_declared_metrics(tmp_path):
    monitor = controller(tmp_path)
    observe(monitor, 0, 1, 10)
    result, _, _ = observe(monitor, 1, 2, 9)
    feedback = result.negative_feedback
    assert monitor.validate_feedback(feedback) == feedback
    serialized = json.dumps(feedback)
    assert "DO_NOT_EXPORT" not in serialized and "secret" not in serialized
    records = monitor.feedback_records(feedback)
    assert set(records) == {"current_proxy", "current_anchor", "baseline_proxy", "baseline_anchor"}
    assert records["current_anchor"]["evidence"]["eval_result"]["contract"]["binding"]["split_id"] == "calibration"
    forged = copy.deepcopy(feedback)
    forged["current"]["true_score"] = 0
    with pytest.raises(ValueError, match="differs"):
        monitor.validate_feedback(forged)
    unknown = copy.deepcopy(feedback)
    unknown["pair_id"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="authoritative"):
        monitor.feedback_records(unknown)
    records["current_anchor"]["evidence"]["eval_result"]["metrics"]["calibration/quality"] = -99
    assert monitor.validate_feedback(feedback) == feedback


def test_independent_metric_directions_are_applied_before_rank_and_true_gain(tmp_path):
    monitor = controller(tmp_path, options(proxy_direction="minimize", true_direction="maximize"))
    observe(monitor, 0, 30, 1)
    observe(monitor, 1, 20, 2)
    result, _, _ = observe(monitor, 2, 10, 3)
    assert result.mode == "monitoring" and result.rank_correlation == 1
    assert result.negative_feedback is None and result.true_improved


@pytest.mark.parametrize("series,rule", [
    ([(3, 1), (2, 2), (1, 3)], "rank_correlation_below_threshold"),
    ([(1, 1), (1, 2), (1, 3)], "rank_correlation_undefined"),
])
def test_rank_drift_and_constant_proxy_degrade_only_after_configured_sample_floor(tmp_path, series, rule):
    monitor = controller(tmp_path)
    for cycle, (proxy, anchor) in enumerate(series):
        result, _, _ = observe(monitor, cycle, proxy, anchor)
        if cycle < 2:
            assert result.mode == "warmup"
    assert result.mode == "degraded" and rule in result.alerts
    assert result.negative_feedback is None


def test_request_change_resets_effective_rank_window_without_erasing_drift_history(tmp_path):
    monitor = controller(tmp_path)
    observe(monitor, 0, 1, 3)
    observe(monitor, 1, 2, 2)
    changed = EvalRequest("different-proxy", split_id="dev", seed_set=[2])
    result, _, _ = observe(monitor, 2, 50, 1, dev_request=changed)
    assert result.mode == "degraded" and result.valid_pairs == 1 and result.rank_correlation is None
    assert result.negative_feedback is None
    assert not monitor.allows_advancement(result.pair_id)  # True request is still comparable.


def test_baseline_can_follow_candidate_in_same_cycle_without_double_counting_or_false_feedback(tmp_path):
    monitor = controller(tmp_path)
    candidate, _, _ = observe(monitor, 0, 1, 5)
    baseline, _, _ = observe(monitor, 0, 2, 10, role="baseline", name="incumbent")
    assert baseline.valid_pairs == 1 and baseline.negative_feedback is None
    assert monitor.state()["mode"] == "warmup"
    assert not monitor.allows_advancement(candidate.pair_id)
    result, _, _ = observe(monitor, 1, 3, 9)
    assert result.negative_feedback["baseline"]["pair_id"] == baseline.pair_id
    assert result.valid_pairs == 2


def test_baseline_different_proxy_basis_never_resets_candidate_rank_window(tmp_path):
    monitor = controller(tmp_path)
    observe(monitor, 0, 1, 1)
    observe(monitor, 1, 2, 2)
    baseline, _, _ = observe(monitor, 1, 100, 100, role="baseline", name="old-incumbent",
                             dev_request=EvalRequest("old-proxy", split_id="dev"))
    assert baseline.valid_pairs == 2 and baseline.rank_correlation == 1
    result, _, _ = observe(monitor, 2, 3, 3)
    assert result.valid_pairs == 3 and result.mode == "monitoring"
    assert not monitor.allows_advancement(result.pair_id)


def test_exact_cache_returns_detached_evidence_and_never_rebinds_different_proxy_receipt(tmp_path):
    monitor = controller(tmp_path)
    _, plan, anchor = observe(monitor, 0, 1, 2)
    cached = monitor.cached_anchor(plan.proposal, plan.proxy_evidence, anchor_binding=plan.binding)
    assert cached == anchor
    cached.eval_result.metrics["calibration/quality"] = -1
    assert monitor.cached_anchor(plan.proposal, plan.proxy_evidence, anchor_binding=plan.binding) == anchor
    changed = replace(plan.proxy_evidence, attempt=2)
    assert monitor.cached_anchor(plan.proposal, changed, anchor_binding=plan.binding) is None


@pytest.mark.parametrize("fault", ["gate_proxy", "opaque", "same_context", "other_artifact", "other_candidate", "other_request"])
def test_pairing_rejects_held_out_opaque_or_mismatched_evidence_before_call(tmp_path, fault):
    monitor = controller(tmp_path)
    proposal, proxy, anchor = inputs(monitor, 0)
    binding = anchor.eval_result.contract.binding
    if fault == "gate_proxy":
        proxy = evidence(proposal, EvalRequest("gate", split_id="admission"), 1)
    elif fault == "opaque":
        proxy = replace(proxy, eval_result=replace(proxy.eval_result, contract=replace(proxy.eval_result.contract,
            binding=replace(proxy.eval_result.contract.binding, evaluation_context=""))))
    elif fault == "same_context":
        binding = replace(binding, evaluation_context=proxy.eval_result.contract.binding.evaluation_context)
    elif fault == "other_artifact":
        proposal = replace(proposal, artifact="different")
    elif fault == "other_candidate":
        binding = replace(binding, candidate_id="different")
    else:
        binding = replace(binding, request_sha256="sha256:" + "c" * 64)
    with pytest.raises(ValueError):
        monitor.plan(proposal, proxy, 0, anchor_binding=binding)
    assert not monitor.store.path.exists()


def test_mutated_plan_and_wrong_anchor_cannot_be_recorded_or_release_original_call(tmp_path):
    monitor = controller(tmp_path)
    proposal, proxy, anchor = inputs(monitor, 0)
    plan = monitor.plan(proposal, proxy, 0, anchor_binding=anchor.eval_result.contract.binding)
    changed = copy.deepcopy(plan)
    changed.proxy_evidence.eval_result.metrics["dev/surrogate"] = 9
    with pytest.raises(ValueError, match="identity"):
        monitor.begin(changed)
    monitor.begin(plan)
    with pytest.raises(ValueError, match="unfinished|reused"):
        monitor.begin(plan)
    foreign = replace(anchor, eval_result=replace(anchor.eval_result, contract=replace(anchor.eval_result.contract,
        binding=replace(anchor.eval_result.contract.binding, split_id="final_audit"))))
    with pytest.raises(ValueError, match="binding"):
        monitor.record(plan, foreign)
    assert monitor.state()["open_calls"] == [plan.key]
    monitor.record(plan, anchor)
    before = monitor.checkpoint_state()
    monitor.record(plan, anchor)
    assert monitor.checkpoint_state() == before
    changed = replace(anchor, attempt=2)
    with pytest.raises(ValueError, match="rebound"):
        monitor.record(plan, changed)


@pytest.mark.parametrize("explicit_evidence", [True, False])
def test_failed_anchor_degrades_and_never_becomes_a_valid_rank_sample(tmp_path, explicit_evidence):
    monitor = controller(tmp_path)
    proposal, proxy, anchor = inputs(monitor, 0)
    plan = monitor.plan(proposal, proxy, 0, anchor_binding=anchor.eval_result.contract.binding)
    monitor.begin(plan)
    if explicit_evidence:
        failed = evidence(proposal, monitor.anchor_request, 0, status=EvalStatus.FAILED_TO_RUN)
        result = monitor.record(plan, failed)
        assert not result.true_improved and result.negative_feedback is None
    else:
        monitor.mark_failed(plan, "native execution failed with unknown usage")
    assert monitor.state()["mode"] == "degraded" and monitor.state()["valid_pairs"] == 0
    assert monitor.needs_anchor(1)
    assert not monitor.allows_advancement(plan.key)


def test_checkpoint_rebuild_is_exact_read_only_and_revalidates_feedback(tmp_path):
    monitor = controller(tmp_path)
    observe(monitor, 0, 1, 5)
    result, _, _ = observe(monitor, 1, 2, 4)
    checkpoint, journal = monitor.checkpoint_state(), monitor.store.path.read_bytes()
    restored = controller(tmp_path)
    restored.restore_state(checkpoint)
    assert restored.checkpoint_state() == checkpoint
    assert restored.validate_feedback(result.negative_feedback) == result.negative_feedback
    assert restored.feedback_records(result.negative_feedback) == monitor.feedback_records(result.negative_feedback)
    assert monitor.store.path.read_bytes() == journal
    with pytest.raises(ValueError, match="fresh"):
        restored.restore_state(checkpoint)


def test_stale_checkpoint_config_run_or_chain_cannot_roll_back_history(tmp_path):
    monitor = controller(tmp_path)
    observe(monitor, 0, 1, 1)
    stale = monitor.checkpoint_state()
    observe(monitor, 1, 2, 2)
    with pytest.raises(ValueError, match="differs"):
        controller(tmp_path).restore_state(stale)
    with pytest.raises(ValueError, match="configuration"):
        controller(tmp_path, options(window=5)).restore_from_journal()
    with pytest.raises(ValueError, match="run"):
        controller(tmp_path, run_id="other-run").restore_from_journal()
    rows = [json.loads(line) for line in monitor.store.path.read_text().splitlines()]
    rows[1]["payload"]["data"]["anchor"]["evidence"]["eval_result"]["metrics"]["calibration/quality"] = 99
    monitor.store.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(ValueError, match="integrity"):
        controller(tmp_path).restore_from_journal()


def test_unfinished_call_survives_restore_and_cannot_be_repeated(tmp_path):
    monitor = controller(tmp_path)
    proposal, proxy, anchor = inputs(monitor, 0)
    plan = monitor.plan(proposal, proxy, 0, anchor_binding=anchor.eval_result.contract.binding)
    monitor.begin(plan)
    restored = controller(tmp_path)
    restored.restore_state(monitor.checkpoint_state())
    with pytest.raises(ValueError, match="unfinished"):
        restored.needs_anchor(1)
    with pytest.raises(ValueError, match="unfinished"):
        restored.plan(proposal, proxy, 1, anchor_binding=plan.binding, force=True, role="baseline")
    assert restored.state()["open_calls"] == [plan.key]
    assert len(list(monitor.store.read(JOURNAL_KIND))) == 1


def test_window_is_bounded_and_older_best_still_prevents_false_true_improvement(tmp_path):
    monitor = controller(tmp_path, options(window=3))
    for cycle, score in enumerate([10, 8, 7, 6]):
        observe(monitor, cycle, score, score)
    result, _, _ = observe(monitor, 4, 9, 9)
    assert result.valid_pairs == 3 and result.rank_correlation == 1
    assert not result.true_improved and not monitor.allows_advancement(result.pair_id)


def test_store_failure_does_not_publish_undurable_controller_state(tmp_path, monkeypatch):
    monitor = controller(tmp_path)
    proposal, proxy, anchor = inputs(monitor, 0)
    plan = monitor.plan(proposal, proxy, 0, anchor_binding=anchor.eval_result.contract.binding)
    before = monitor.checkpoint_state()
    def fail(*args):
        raise OSError("disk write failed")
    monkeypatch.setattr(monitor.store, "append", fail)
    with pytest.raises(OSError):
        monitor.begin(plan)
    assert monitor.checkpoint_state() == before


def test_repeated_candidate_is_not_an_independent_rank_sample_and_artifact_identity_is_frozen(tmp_path):
    monitor = controller(tmp_path)
    _, first, _ = observe(monitor, 0, 1, 1)
    repeated = monitor.plan(first.proposal, first.proxy_evidence, 1, anchor_binding=first.binding, force=True)
    with pytest.raises(ValueError, match="repeated rank"):
        monitor.begin(repeated)
    altered = replace(first.proposal, artifact="new artifact under same identity")
    proxy = evidence(altered, EvalRequest("proxy", seed_set=[1]), 2)
    anchor = evidence(altered, monitor.anchor_request, 2)
    rebound = monitor.plan(altered, proxy, 1, anchor_binding=anchor.eval_result.contract.binding, role="baseline")
    with pytest.raises(ValueError, match="rebound"):
        monitor.begin(rebound)
    assert monitor.state()["valid_pairs"] == 1


def test_large_exact_integer_metrics_do_not_become_false_ties_from_float_conversion(tmp_path):
    monitor = controller(tmp_path)
    origin = 10 ** 40
    for cycle in range(3):
        result, _, _ = observe(monitor, cycle, origin + cycle, origin + cycle)
        assert result.true_improved
    assert result.rank_correlation == 1 and result.mode == "monitoring"
