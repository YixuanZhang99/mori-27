"""Layered admission pays for real calls and never learns from final audit."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, replace

import pytest

from core.composition.admission import (LayeredAdmissionController, layered_options,
                                        validate_layered_receipt)
from core.composition.contracts import Proposal
from core.composition.evaluation import (EvaluationContract, PrivateEvaluationData, binding_for,
                                         comparison_projection, measured_costs)
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.llm import UsageError
from core.x1.store import AppendOnlyStore


class Domain:
    evaluator_version = "domain-v1"

    def __init__(self):
        self.dataset = "frozen-dataset"
        self.calls = []

    def validate_request(self, request):
        request.validate()
        assert request.split_id in {"dev", "admission", "final_audit"}

    def evaluation_context_for(self, request):
        return "sha256:" + hashlib.sha256((self.dataset + ":" + request.split_id).encode()).hexdigest()

    def result(self, proposal, request, score, *, tokens=7, status=EvalStatus.OK, private="secret"):
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context_for(request))
        return EvidenceRecord(proposal.candidate.id, EvalResult(status,
            {"dev/score": score} if status is EvalStatus.OK else {},
            cost=CostVec(tokens_in=tokens, eval_count=1), fidelity=request.fidelity,
            contract=EvaluationContract(binding, ("token", "eval_count"),
                private=PrivateEvaluationData({"hidden/score": 0.1}, {"answer": private}))),
            executor_status="scored" if status is EvalStatus.OK else "failed_to_run")


def proposal(name):
    return Proposal(Candidate(name), "artifact for " + name)


def dev(domain, item, score):
    return domain.result(item, EvalRequest("dev"), score)


def execute(controller, plan, domain, scores, **kwargs):
    records = {}
    for call in plan.calls:
        controller.before_call(call)
        domain.calls.append((call.proposal.candidate.id, call.request.split_id))
        record = domain.result(call.proposal, call.request, scores[call.proposal.candidate.id], **kwargs)
        controller.record(call, record)
        records[call.proposal.candidate.id] = record
    return records


def select_first(controller, domain, score=0.8):
    item = proposal("base")
    development = dev(domain, item, 0.5)
    plan = controller.prepare(item, development, None, None, domain)
    records = execute(controller, plan, domain, {"base": score})
    assert controller.judge(plan).admit
    return item, development, records["base"]


def test_dev_winner_can_fail_admission_and_selected_best_only_moves_monotonically():
    domain, controller = Domain(), LayeredAdmissionController(call_budget=3)
    baseline, baseline_dev, _ = select_first(controller, domain)
    overfit = proposal("overfit")
    plan = controller.prepare(overfit, dev(domain, overfit, 0.95), baseline, baseline_dev, domain)
    assert [call.proposal.candidate.id for call in plan.calls] == ["overfit"]
    execute(controller, plan, domain, {"overfit": 0.7})
    assert not controller.judge(plan).admit
    assert controller.report()["dev_best"]["candidate_id"] == "overfit"
    assert controller.report()["gate_selected"]["candidate_id"] == "base"
    improved = proposal("improved")
    plan = controller.prepare(improved, dev(domain, improved, 0.9), baseline, baseline_dev, domain)
    execute(controller, plan, domain, {"improved": 0.85})
    assert controller.judge(plan).admit and controller.gate_calls == 3
    assert controller.report()["gate_selected"]["candidate_id"] == "improved"


def test_call_budget_counts_baseline_and_candidate_and_refuses_incomplete_pair_up_front():
    domain = Domain()
    old, new = proposal("old"), proposal("new")
    for budget in (0, 1):
        controller = LayeredAdmissionController(call_budget=budget)
        plan = controller.prepare(new, dev(domain, new, 0.9), old, dev(domain, old, 0.5), domain)
        assert not plan.triggered and plan.calls == ()
        assert not controller.judge(plan).admit and controller.gate_calls == 0
    controller = LayeredAdmissionController(call_budget=2)
    plan = controller.prepare(new, dev(domain, new, 0.9), old, dev(domain, old, 0.5), domain)
    assert [call.proposal.candidate.id for call in plan.calls] == ["old", "new"]
    execute(controller, plan, domain, {"old": 0.5, "new": 0.6})
    assert controller.judge(plan).admit and controller.remaining_calls == 0


def test_development_trigger_and_global_budget_decline_make_zero_admission_calls():
    domain, controller = Domain(), LayeredAdmissionController(trigger={"min_dev_gain": 0.1})
    old, new = proposal("old"), proposal("new")
    plan = controller.prepare(new, dev(domain, new, 0.55), old, dev(domain, old, 0.5), domain)
    assert not plan.triggered and not plan.calls
    assert not controller.judge(plan).admit
    fresh = LayeredAdmissionController()
    plan = fresh.prepare(new, dev(domain, new, 0.9), old, dev(domain, old, 0.5), domain)
    assert len(plan.calls) == 2
    receipt = fresh.decline(plan, "global physical budget unavailable")
    assert not receipt.admit and fresh.gate_calls == 0 and domain.calls == []
    with pytest.raises(ValueError, match="not authorized"):
        fresh.before_call(plan.calls[0])


def test_bootstrap_report_includes_the_supplied_incumbent_development_evidence():
    domain, controller = Domain(), LayeredAdmissionController()
    old, worse = proposal("old"), proposal("worse")
    plan = controller.prepare(worse, dev(domain, worse, 0.3), old, dev(domain, old, 0.7), domain)
    assert not plan.calls and not controller.judge(plan).admit
    assert controller.report()["dev_best"]["candidate_id"] == "old"


def test_failed_invocations_consume_call_budget_and_never_get_a_free_retry():
    domain, controller = Domain(), LayeredAdmissionController(call_budget=1)
    item = proposal("candidate")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    execute(controller, plan, domain, {"candidate": 0}, status=EvalStatus.FAILED_TO_RUN)
    assert not controller.judge(plan).admit and controller.gate_calls == 1
    same = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    assert same.calls == () and not controller.judge(same).admit
    with pytest.raises(ValueError):
        controller.before_call(plan.calls[0])


def test_unknown_failure_is_durably_counted_but_cannot_be_reexecuted_or_used_as_evidence():
    domain, controller = Domain(), LayeredAdmissionController(call_budget=2)
    item = proposal("candidate")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    controller.before_call(plan.calls[0])
    controller.mark_failed(plan.calls[0])
    restored = LayeredAdmissionController(call_budget=2)
    restored.restore_state(controller.checkpoint_state())
    retry = restored.prepare(item, dev(domain, item, 0.8), None, None, domain)
    assert not retry.triggered and not retry.calls and restored.gate_calls == 1
    with pytest.raises(ValueError, match="required evidence"):
        controller.judge(plan)


@pytest.mark.parametrize("field,value", [("artifact_sha256", "f" * 64),
    ("evaluation_context", "sha256:" + "f" * 64), ("seed_set", (99,)),
    ("evaluator_version", "other"), ("split_id", "dev")])
def test_record_requires_actual_producer_binding_and_keeps_known_cost_visible_on_rejection(field, value):
    domain, controller = Domain(), LayeredAdmissionController()
    item = proposal("candidate")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    call = plan.calls[0]
    controller.before_call(call)
    actual = domain.result(item, call.request, 0.9)
    actual = replace(actual, eval_result=replace(actual.eval_result, contract=replace(actual.eval_result.contract,
        binding=replace(actual.eval_result.contract.binding, **{field: value}))))
    assert measured_costs(actual.eval_result)["token"] == 7
    with pytest.raises(ValueError, match="binding mismatch"):
        controller.record(call, actual)
    assert controller.gate_calls == 1 and controller.checkpoint_state()["cache"] == {}


def test_missing_cost_coverage_is_unknown_and_cannot_enter_gate_cache():
    domain, controller = Domain(), LayeredAdmissionController()
    item = proposal("candidate")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    call = plan.calls[0]
    controller.before_call(call)
    result = domain.result(item, call.request, 0.9)
    result = replace(result, eval_result=replace(result.eval_result, contract=None))
    with pytest.raises(UsageError):
        controller.record(call, result)
    assert controller.gate_calls == 1


def test_cache_identity_changes_with_dataset_evaluator_request_seeds_and_artifact():
    domain, controller = Domain(), LayeredAdmissionController()
    item = proposal("candidate")
    first = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    execute(controller, first, domain, {"candidate": 0.9})
    reused = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    assert reused.calls == () and reused.candidate_key == first.candidate_key
    domain.evaluator_version = "domain-v2"
    # Existing dev evidence is still explicitly v1; admission is separately bound.
    changed = controller.prepare(item, first_dev := dev(Domain(), item, 0.8), None, None, domain)
    assert len(changed.calls) == 1 and changed.candidate_key != first.candidate_key
    domain = Domain(); domain.dataset = "new-split"
    changed = controller.prepare(item, first_dev, None, None, domain)
    assert len(changed.calls) == 1 and changed.candidate_key != first.candidate_key
    seeded = LayeredAdmissionController(admission_seeds=[1, 2])
    assert seeded.prepare(item, first_dev, None, None, Domain()).candidate_key != first.candidate_key
    changed_item = replace(item, artifact="another artifact")
    assert controller.prepare(changed_item, dev(Domain(), changed_item, 0.8), None, None, Domain()).candidate_key != first.candidate_key


def test_receipt_is_cost_private_independent_and_recomputed_from_real_records():
    receipts, records = [], []
    for tokens, secret in ((1, "first secret"), (9999, "different secret")):
        controller, domain = LayeredAdmissionController(), Domain()
        old, new = proposal("old"), proposal("new")
        plan = controller.prepare(new, dev(domain, new, 0.8), old, dev(domain, old, 0.5), domain)
        actual = execute(controller, plan, domain, {"old": 0.5, "new": 0.9}, tokens=tokens, private=secret)
        receipt = controller.judge(plan)
        receipts.append(receipt); records.append(actual)
        payload = json.dumps(asdict(receipt))
        assert "cost" not in payload and "private" not in payload and secret not in payload
        validate_layered_receipt(receipt, candidate_evidence=actual["new"], incumbent_evidence=actual["old"],
                                 candidate_dev=dev(domain, new, 0.8), incumbent_dev=dev(domain, old, 0.5))
        with pytest.raises(ValueError, match="actual evaluation records"):
            validate_layered_receipt(receipt)
    assert receipts[0] == receipts[1]
    changed_context = copy.deepcopy(receipts[0].decision_context)
    changed_context["decision"]["admit"] = False
    raw = json.dumps(changed_context, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    forged = replace(receipts[0], admit=False, decision_context=changed_context,
                     receipt_id="sha256:" + hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError, match="not reproducible"):
        validate_layered_receipt(forged, candidate_evidence=records[0]["new"], incumbent_evidence=records[0]["old"],
                                 candidate_dev=dev(domain, new, 0.8), incumbent_dev=dev(domain, old, 0.5))


def test_final_audit_runs_once_after_freeze_and_cannot_change_selected_or_search_state():
    controller, domain = LayeredAdmissionController(call_budget=1), Domain()
    item, development, _ = select_first(controller, domain)
    before = controller.report()
    final = controller.freeze(item, domain)
    assert len(final.calls) == 1 and final.calls[0].request.split_id == "final_audit"
    assert controller.freeze(item, domain) == final
    execute(controller, final, domain, {"base": 0.0})
    report = controller.report()
    assert report["dev_best"] == before["dev_best"] and report["gate_selected"] == before["gate_selected"]
    assert report["final_audit"]["evidence"]["eval_result"]["metrics"]["dev/score"] == 0.0
    assert controller.gate_calls == 1 and controller.final_calls == 1
    assert controller.freeze(item, domain).calls == ()
    with pytest.raises(ValueError):
        controller.before_call(final.calls[0])
    with pytest.raises(ValueError, match="frozen"):
        controller.prepare(proposal("later"), dev(domain, proposal("later"), 1.0), item, development, domain)
    restored = LayeredAdmissionController(call_budget=1)
    restored.restore_state(controller.checkpoint_state())
    assert restored.report() == report and restored.freeze(item, domain).calls == ()


def test_two_layer_protocol_and_missing_final_budget_are_explicitly_reported():
    domain = Domain()
    controller = LayeredAdmissionController(layers=["dev", "admission"])
    item, _, _ = select_first(controller, domain)
    assert not controller.freeze(item, domain).enabled
    assert controller.final_report()["state"] == "disabled" and controller.final_calls == 0
    controller = LayeredAdmissionController()
    item, _, _ = select_first(controller, domain)
    final = controller.freeze(item, domain)
    controller.skip_final("global physical budget unavailable")
    assert controller.final_report()["state"] == "not_run"
    assert controller.final_calls == 0
    with pytest.raises(ValueError):
        controller.before_call(final.calls[0])


def test_checkpoint_and_append_only_journal_cannot_forget_started_paid_calls(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    controller, domain = LayeredAdmissionController(store=store), Domain()
    item = proposal("candidate")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    before = controller.checkpoint_state()
    controller.before_call(plan.calls[0])
    after = controller.checkpoint_state()
    fresh = LayeredAdmissionController(store=store)
    with pytest.raises(ValueError, match="durable admission history"):
        fresh.restore_state(before)
    fresh.restore_state(after)
    assert fresh.gate_calls == 1
    plan = fresh.prepare(item, dev(domain, item, 0.8), None, None, domain)
    assert not plan.calls and not plan.triggered
    assert any(row["payload"]["event"] == "call_started" for row in store.read("layered_admission_state"))


def test_checkpoint_cache_and_selection_require_real_recorded_invocations():
    controller, domain = LayeredAdmissionController(), Domain()
    select_first(controller, domain)
    checkpoint = controller.checkpoint_state()
    variants = []
    changed = copy.deepcopy(checkpoint); changed["calls"] = {}; variants.append(changed)
    changed = copy.deepcopy(checkpoint); changed["cache"] = {}; variants.append(changed)
    changed = copy.deepcopy(checkpoint); changed["options"]["call_budget"] += 1; variants.append(changed)
    changed = copy.deepcopy(checkpoint); changed["selected"]["evidence"]["eval_result"]["metrics"]["dev/score"] = 99; variants.append(changed)
    for state in variants:
        with pytest.raises(ValueError):
            LayeredAdmissionController().restore_state(state)


def test_integrity_checks_block_canaries_and_explicit_sources_before_evaluation_planning():
    controller = LayeredAdmissionController(blocked_patterns=["HOLDOUT_CANARY"], blocked_sources=["source://held-out"],
        integrity_hooks=["hash_check", "canary_scan", "source_blocklist"])
    domain, item = Domain(), proposal("candidate")
    poisoned = replace(item, artifact="HOLDOUT_CANARY")
    with pytest.raises(ValueError, match="canary"):
        controller.prepare(poisoned, dev(domain, poisoned, 0.8), None, None, domain)
    with pytest.raises(ValueError, match="blocked source"):
        controller.prepare(item, dev(domain, item, 0.8), None, None, domain, source_refs=["source://held-out"])
    assert controller.gate_calls == 0


@pytest.mark.parametrize("options", [
    {"selection": "top_k"}, {"monotonicity": False}, {"call_budget": True}, {"call_budget": -1},
    {"trigger": {"min_dev_gain": float("nan")}}, {"trigger": {"x": 1}},
    {"trigger": {"min_dev_gain": 1}, "min_dev_gain": 1},
    {"final_audit": {"isolation": False, "runs": 1}}, {"final_audit": {"isolation": True, "runs": 2}},
    {"layers": ["dev", "final_audit"]}, {"admission_seeds": [True]}, {"final_seeds": []},
    {"integrity_hooks": ["human_approval"]}, {"blocked_patterns": [""]}, {"unknown": True},
])
def test_unsupported_options_are_explicitly_rejected(options):
    with pytest.raises(ValueError):
        layered_options(options)


def test_domain_preflight_requires_declared_distinct_split_content_and_support():
    domain, controller = Domain(), LayeredAdmissionController()
    contexts = controller.validate_domain(domain)
    assert contexts["admission"] != contexts["final_audit"] and domain.calls == []
    class Opaque(Domain):
        def evaluation_context_for(self, request):
            return ""
    with pytest.raises(ValueError, match="content-bound"):
        controller.validate_domain(Opaque())


def test_mutated_plan_or_stale_incumbent_cannot_override_gate_selection():
    controller, domain = LayeredAdmissionController(), Domain()
    item = proposal("first")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    with pytest.raises(ValueError, match="plan"):
        controller.judge(replace(plan, triggered=False))
    execute(controller, plan, domain, {"first": 0.9})
    controller.judge(plan)
    with pytest.raises(ValueError, match="current gate-selected"):
        controller.prepare(proposal("next"), dev(domain, proposal("next"), 0.9), None, None, domain)


@pytest.mark.parametrize("before,after,margin,accepted", [(0.5, 0.4, 0.05, True),
    (0.5, 0.45, 0.1, False), (0.5, 0.5, 0.0, False)])
def test_minimization_and_strict_margin_are_recomputable(before, after, margin, accepted):
    controller, domain = LayeredAdmissionController(direction="minimize", margin=margin), Domain()
    old, new = proposal("old"), proposal("new")
    plan = controller.prepare(new, dev(domain, new, 0.2), old, dev(domain, old, 0.8), domain)
    actual = execute(controller, plan, domain, {"old": before, "new": after})
    receipt = controller.judge(plan)
    assert receipt.admit is accepted
    validate_layered_receipt(receipt, candidate_evidence=actual["new"], incumbent_evidence=actual["old"],
                             candidate_dev=dev(domain, new, 0.2), incumbent_dev=dev(domain, old, 0.8))


def test_identical_dataset_contexts_cannot_be_presented_as_isolated_splits():
    class Reused(Domain):
        def evaluation_context_for(self, request):
            return "sha256:" + "f" * 64
    controller, domain = LayeredAdmissionController(), Reused()
    with pytest.raises(ValueError, match="distinct"):
        controller.validate_domain(domain)
    item = proposal("candidate")
    with pytest.raises(ValueError, match="development dataset"):
        controller.prepare(item, dev(domain, item, 0.8), None, None, domain)


def test_final_call_crash_cannot_be_forgotten_by_restoring_prefinal_checkpoint(tmp_path):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    controller, domain = LayeredAdmissionController(store=store), Domain()
    item, _, _ = select_first(controller, domain)
    plan = controller.freeze(item, domain)
    before = controller.checkpoint_state()
    controller.before_call(plan.calls[0])
    pending = controller.checkpoint_state()
    with pytest.raises(ValueError, match="durable admission history"):
        LayeredAdmissionController(store=store).restore_state(before)
    restored = LayeredAdmissionController(store=store)
    restored.restore_state(pending)
    assert restored.final_calls == 1 and restored.freeze(item, domain).calls == ()
    with pytest.raises(ValueError, match="not completed"):
        restored.final_report()


def test_receipt_rejects_hidden_or_cost_fields_even_if_attacker_recomputes_its_hash():
    controller, domain = LayeredAdmissionController(), Domain()
    item = proposal("candidate")
    plan = controller.prepare(item, dev(domain, item, 0.8), None, None, domain)
    actual = execute(controller, plan, domain, {"candidate": 0.9})
    receipt = controller.judge(plan)
    context = copy.deepcopy(receipt.decision_context)
    context["development"]["candidate"]["eval_result"]["private"] = {"answer": "leaked"}
    raw = json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    forged = replace(receipt, decision_context=context,
                     receipt_id="sha256:" + hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError, match="unauthorized fields"):
        validate_layered_receipt(forged, candidate_evidence=actual["candidate"], candidate_dev=dev(domain, item, 0.8))


def test_receipt_requires_actual_development_records_and_recomputes_trigger_after_rehash():
    controller, domain = LayeredAdmissionController(trigger={"min_dev_gain": 0.1}), Domain()
    old, new = proposal("old"), proposal("new")
    old_dev, new_dev = dev(domain, old, 0.5), dev(domain, new, 0.8)
    plan = controller.prepare(new, new_dev, old, old_dev, domain)
    actual = execute(controller, plan, domain, {"old": 0.5, "new": 0.9})
    receipt = controller.judge(plan)
    with pytest.raises(ValueError, match="development trigger"):
        validate_layered_receipt(receipt, candidate_evidence=actual["new"], incumbent_evidence=actual["old"])
    for mutation, message in (("dev_score", "actual development"), ("trigger", "trigger is not reproducible")):
        context = copy.deepcopy(receipt.decision_context)
        if mutation == "dev_score":
            context["development"]["candidate"]["eval_result"]["metrics"]["dev/score"] = 1.0
        else:
            context["rules"]["min_dev_gain"] = 0.5
        raw = json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        forged = replace(receipt, decision_context=context,
                         receipt_id="sha256:" + hashlib.sha256(raw.encode()).hexdigest())
        with pytest.raises(ValueError, match=message):
            validate_layered_receipt(forged, candidate_evidence=actual["new"], incumbent_evidence=actual["old"],
                                     candidate_dev=new_dev, incumbent_dev=old_dev)
    state = controller.checkpoint_state()
    state["development_records"] = {}
    with pytest.raises(ValueError):
        LayeredAdmissionController(trigger={"min_dev_gain": 0.1}).restore_state(state)


def test_receipt_cannot_mix_development_and_admission_for_different_artifacts():
    controller, domain = LayeredAdmissionController(), Domain()
    item = proposal("candidate")
    development = dev(domain, item, 0.8)
    plan = controller.prepare(item, development, None, None, domain)
    actual = execute(controller, plan, domain, {"candidate": 0.9})["candidate"]
    receipt = controller.judge(plan)
    mismatched = replace(actual, eval_result=replace(actual.eval_result, contract=replace(actual.eval_result.contract,
        binding=replace(actual.eval_result.contract.binding, artifact_sha256="f" * 64))))
    context = copy.deepcopy(receipt.decision_context)
    context["admission"]["candidate"] = json.loads(json.dumps(asdict(comparison_projection(mismatched))))
    raw = json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    forged = replace(receipt, decision_context=context,
                     receipt_id="sha256:" + hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError, match="same artifact"):
        validate_layered_receipt(forged, candidate_evidence=mismatched, candidate_dev=development)


def test_restore_cannot_promote_successful_but_rejected_gate_evidence():
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, baseline_dev, _ = select_first(controller, domain)
    loser = proposal("loser")
    plan = controller.prepare(loser, dev(domain, loser, 0.9), baseline, baseline_dev, domain)
    execute(controller, plan, domain, {"loser": 0.6})
    assert not controller.judge(plan).admit
    state = controller.checkpoint_state()
    state["selected"] = copy.deepcopy(state["cache"][plan.candidate_key])
    with pytest.raises(ValueError, match="accepted decision"):
        LayeredAdmissionController().restore_state(state)


def dev_rung(domain, item, score, *, fidelity="high", seeds=(3, 5)):
    return domain.result(item, EvalRequest(fidelity, seed_set=list(seeds), split_id="dev"), score)


def test_explicit_development_basis_advancement_uses_real_incumbent_and_preserves_old_receipts():
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, original_dev, baseline_gate = select_first(controller, domain)
    overfit = proposal("overfit")
    overfit_dev = dev(domain, overfit, 0.95)
    old_plan = controller.prepare(overfit, overfit_dev, baseline, original_dev, domain)
    old_gate = execute(controller, old_plan, domain, {"overfit": 0.7})["overfit"]
    old_receipt = controller.judge(old_plan)
    assert not old_receipt.admit
    old_state = controller.checkpoint_state()
    new_baseline = dev_rung(domain, baseline, 0.2)
    controller.advance_development_basis(new_baseline)
    report = controller.report()
    assert report["dev_best"]["candidate_id"] == "base"
    assert report["dev_best"]["eval_result"]["metrics"]["dev/score"] == 0.2
    assert controller.gate_calls == 2
    state = controller.checkpoint_state()
    assert state["decisions"] == old_state["decisions"]
    assert set(old_state["development_records"]) < set(state["development_records"])
    validate_layered_receipt(old_receipt, candidate_evidence=old_gate, incumbent_evidence=baseline_gate,
                             candidate_dev=overfit_dev, incumbent_dev=original_dev)
    improved = proposal("improved")
    improved_dev = dev_rung(domain, improved, 0.3)
    new_plan = controller.prepare(improved, improved_dev, baseline, new_baseline, domain)
    assert new_plan.triggered and [call.proposal.candidate.id for call in new_plan.calls] == ["improved"]
    execute(controller, new_plan, domain, {"improved": 0.9})
    assert controller.judge(new_plan).admit
    restored = LayeredAdmissionController()
    restored.restore_state(controller.checkpoint_state())
    assert restored.report() == controller.report()
    assert restored.development_basis["fidelity"] == "high"
    assert restored.development_basis["seed_set"] == [3, 5]
    exposed = restored.development_basis
    exposed["seed_set"].append(999)
    assert restored.development_basis["seed_set"] == [3, 5]


def test_new_development_rung_cannot_mix_with_old_baseline_or_skip_explicit_advancement():
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, old_dev, _ = select_first(controller, domain)
    item = proposal("next")
    candidate = dev_rung(domain, item, 0.3)
    new_baseline = dev_rung(domain, baseline, 0.2)
    before = controller.checkpoint_state()
    with pytest.raises(ValueError, match="identical evaluator"):
        controller.prepare(item, candidate, baseline, old_dev, domain)
    with pytest.raises(ValueError, match="explicitly advancing"):
        controller.prepare(item, candidate, baseline, new_baseline, domain)
    assert controller.checkpoint_state() == before
    controller.advance_development_basis(new_baseline)
    with pytest.raises(ValueError, match="identical evaluator"):
        controller.prepare(item, candidate, baseline, old_dev, domain)


@pytest.mark.parametrize("case", ["candidate", "artifact", "evaluator", "dataset", "failed", "admission", "unknown_cost"])
def test_basis_advancement_rejects_unproven_or_wrong_incumbent_evidence(case):
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, _, _ = select_first(controller, domain)
    actual = dev_rung(domain, baseline, 0.2)
    if case == "candidate":
        actual = dev_rung(domain, proposal("other"), 0.2)
    elif case == "artifact":
        actual = dev_rung(domain, replace(baseline, artifact="different artifact"), 0.2)
    elif case == "evaluator":
        domain.evaluator_version = "different-version"
        actual = dev_rung(domain, baseline, 0.2)
    elif case == "dataset":
        domain.dataset = "different-dev-dataset"
        actual = dev_rung(domain, baseline, 0.2)
    elif case == "failed":
        actual = replace(actual, executor_status="failed_to_run",
            eval_result=replace(actual.eval_result, status=EvalStatus.FAILED_TO_RUN, metrics={}))
    elif case == "admission":
        actual = domain.result(baseline, EvalRequest("admission", split_id="admission"), 0.2)
    else:
        actual = replace(actual, eval_result=replace(actual.eval_result, contract=None))
    before = controller.checkpoint_state()
    with pytest.raises(ValueError):
        controller.advance_development_basis(actual)
    assert controller.checkpoint_state() == before


def test_without_gate_selection_new_basis_resets_current_ranking_and_explains_the_change(tmp_path):
    store = AppendOnlyStore(tmp_path / "basis.jsonl")
    controller, domain = LayeredAdmissionController(store=store), Domain()
    old = proposal("old-high-number")
    plan = controller.prepare(old, dev(domain, old, 0.99), None, None, domain)
    execute(controller, plan, domain, {old.candidate.id: 0}, status=EvalStatus.FAILED_TO_RUN)
    assert not controller.judge(plan).admit
    old_state = controller.checkpoint_state()
    new = proposal("new-low-number")
    plan = controller.prepare(new, dev_rung(domain, new, 0.2), None, None, domain)
    assert controller.report()["dev_best"]["candidate_id"] == new.candidate.id
    assert controller.report()["development_basis"]["fidelity"] == "high"
    assert set(old_state["development_records"]) < set(controller.checkpoint_state()["development_records"])
    events = [row["payload"] for row in store.read("layered_admission_state")]
    advanced = [event for event in events if event["event"] == "development_basis_advanced"]
    assert "no gate-selected incumbent" in advanced[-1]["details"]["reason"]
    assert advanced[-1]["details"]["previous"]["fidelity"] == "dev"
    assert advanced[-1]["details"]["current"]["fidelity"] == "high"
    execute(controller, plan, domain, {new.candidate.id: 0.4})
    controller.judge(plan)
    restored = LayeredAdmissionController(store=store)
    restored.restore_state(controller.checkpoint_state())
    assert restored.report() == controller.report()


def test_basis_change_revokes_unstarted_old_plans_and_refuses_pending_or_frozen_work():
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, old_dev, _ = select_first(controller, domain)
    item = proposal("old-plan")
    plan = controller.prepare(item, dev(domain, item, 0.8), baseline, old_dev, domain)
    controller.advance_development_basis(dev_rung(domain, baseline, 0.2))
    with pytest.raises(ValueError, match="not authorized"):
        controller.before_call(plan.calls[0])
    with pytest.raises(ValueError, match="stale development basis"):
        controller.judge(plan)
    pending = controller.prepare(item, dev_rung(domain, item, 0.3), baseline, dev_rung(domain, baseline, 0.2), domain)
    controller.before_call(pending.calls[0])
    with pytest.raises(ValueError, match="pending"):
        controller.advance_development_basis(dev_rung(domain, baseline, 0.2, fidelity="highest", seeds=(3, 5, 7)))
    controller.mark_failed(pending.calls[0])
    controller.freeze(baseline, domain)
    with pytest.raises(ValueError, match="unfrozen"):
        controller.advance_development_basis(dev_rung(domain, baseline, 0.2, fidelity="highest", seeds=(3, 5, 7)))


def test_idempotent_same_basis_does_not_reset_a_better_development_candidate():
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, original, _ = select_first(controller, domain)
    item = proposal("overfit")
    plan = controller.prepare(item, dev(domain, item, 0.9), baseline, original, domain)
    execute(controller, plan, domain, {"overfit": 0.7})
    controller.judge(plan)
    state = controller.checkpoint_state()
    controller.advance_development_basis(original)
    assert controller.checkpoint_state() == state


def test_restore_requires_current_basis_and_best_to_match_actual_records():
    controller, domain = LayeredAdmissionController(), Domain()
    baseline, original, _ = select_first(controller, domain)
    controller.advance_development_basis(dev_rung(domain, baseline, 0.2))
    state = controller.checkpoint_state()
    variants = []
    changed = copy.deepcopy(state); changed["development_basis"]["fidelity"] = "unrecorded"; variants.append(changed)
    changed = copy.deepcopy(state); changed["development_basis"] = None; variants.append(changed)
    changed = copy.deepcopy(state)
    changed["dev_best"] = next(record for record in changed["development_records"].values()
                               if record["evidence"]["eval_result"]["fidelity"] == "dev")
    variants.append(changed)
    for value in variants:
        with pytest.raises(ValueError):
            LayeredAdmissionController().restore_state(value)
