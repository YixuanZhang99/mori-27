"""Canonical producer identity, explicit measurements and visibility boundaries."""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.contracts import Proposal
from core.composition.defaults import InProcessExecutor, LegacyPromptDomain, MetricAdmission
from core.composition.evaluation import (EvaluationContract, ItemOutcome, PrivateEvaluationData,
    PublicEvaluationData, binding_for, comparison_projection, decode_evidence, encode_evidence,
    measured_costs, public_projection, request_digest, validate_evidence, validate_request, validate_result)
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.llm import UsageError
from examples.toy_gepa import MockLLM, toy_evaluator


def evidence(candidate="candidate", *, request=None, cost=None):
    request = request or EvalRequest("dev")
    binding = binding_for(Proposal(Candidate(candidate), "artifact"), request,
                          evaluator_version="native-v1", evaluation_context="sha256:" + "b" * 64)
    contract = EvaluationContract(binding, ("token", "eval_count"),
        public=PublicEvaluationData({"source": "visible"}),
        private=PrivateEvaluationData({"holdout/score": 0.25}, {"secret": {"answer": "hidden"}}),
        items=(ItemOutcome("visible", 1, visibility="public"), ItemOutcome("secret", 0)))
    return EvidenceRecord(candidate, EvalResult(EvalStatus.OK, {"dev/score": 0.5},
        cost=cost or CostVec(tokens_in=3, tokens_out=2, eval_count=1),
        fidelity=request.fidelity, uncertainty=0.1, text_feedback="public feedback", contract=contract))


def test_versioned_codec_roundtrip_restores_typed_contract_without_aliasing():
    source = evidence(request=EvalRequest("cheap", seed_set=[2, 4], split_id="admission"))
    encoded = encode_evidence(source)
    restored = decode_evidence(encoded, expected_binding=source.eval_result.contract.binding)
    assert restored == source
    assert isinstance(restored.eval_result.contract.items[0], ItemOutcome)
    encoded["evidence"]["eval_result"]["contract"]["private"]["data"]["secret"]["answer"] = "changed"
    assert restored.eval_result.contract.private.data["secret"]["answer"] == "hidden"


@pytest.mark.parametrize("field,value", [
    ("candidate_id", "other"), ("artifact_sha256", "a" * 64),
    ("request_sha256", "sha256:" + "a" * 64), ("evaluator_version", "native-v2"),
    ("evaluation_context", "sha256:" + "c" * 64), ("split_id", "final_audit"),
    ("fidelity", "expensive"), ("seed_set", (3,)),
])
def test_each_producer_identity_dimension_is_compared_to_independent_expectation(field, value):
    source = evidence()
    expected = source.eval_result.contract.binding
    changed = replace(source, eval_result=replace(source.eval_result,
        contract=replace(source.eval_result.contract, binding=replace(expected, **{field: value}))))
    # Invalid identity does not erase independently valid measured charges.
    assert measured_costs(changed.eval_result) == {"token": 5, "eval_count": 1}
    with pytest.raises(ValueError, match="binding mismatch"):
        validate_evidence(changed, expected_binding=expected)


def test_result_fidelity_cannot_disagree_with_its_own_returned_binding():
    changed = replace(evidence(), eval_result=replace(evidence().eval_result, fidelity="full"))
    with pytest.raises(ValueError, match="fidelity differs"):
        validate_evidence(changed)


@pytest.mark.parametrize("cost", [CostVec(tokens_in=True), CostVec(tokens_out=1.0),
    CostVec(eval_count=-1), CostVec(wall_seconds=float("nan")), CostVec(usd=float("inf")),
    CostVec(gpu_hours=-0.1), CostVec(node_count=1.5)])
def test_malformed_physical_usage_is_unknown_and_cannot_settle(cost):
    with pytest.raises(UsageError):
        measured_costs(evidence(cost=cost).eval_result)


@pytest.mark.parametrize("coverage", [(), ("token",), ("token", "token", "eval_count"),
                                      ("tokens", "eval_count"), ["token", "eval_count"]])
def test_default_zero_never_substitutes_for_missing_measurement_coverage(coverage):
    source = evidence(cost=CostVec())
    result = replace(source.eval_result, contract=replace(source.eval_result.contract,
                                                         measured_cost_units=coverage))
    with pytest.raises(UsageError):
        measured_costs(result)


def test_zero_is_valid_only_when_explicitly_measured_and_each_physical_unit_is_covered():
    source = evidence(cost=CostVec())
    assert measured_costs(source.eval_result) == {"token": 0, "eval_count": 0}
    with pytest.raises(UsageError, match="every required"):
        measured_costs(source.eval_result, ("token", "gpu_hours"))
    result = replace(source.eval_result, cost=CostVec(gpu_hours=2),
        contract=replace(source.eval_result.contract, measured_cost_units=("token", "eval_count", "gpu_hours")))
    assert measured_costs(result, ("token", "gpu_hours")) == {"token": 0, "gpu_hours": 2}
    with pytest.raises(UsageError, match="nonzero"):
        measured_costs(replace(source.eval_result, cost=CostVec(gpu_hours=2)))


def test_total_only_token_storage_convention_does_not_claim_measured_input_output_split():
    source = evidence(cost=CostVec(tokens_in=7, eval_count=1))
    total = replace(source.eval_result, contract=replace(source.eval_result.contract, token_accounting="total_only"))
    assert measured_costs(total)["token"] == 7
    with pytest.raises(UsageError, match="total-only"):
        measured_costs(replace(total, cost=CostVec(tokens_in=7, tokens_out=1, eval_count=1)))


@pytest.mark.parametrize("metrics", [{"x": True}, {"x": float("nan")}, {"x": float("inf")}, {"x": "0.5"}, {}])
def test_public_objective_requires_finite_numeric_values(metrics):
    with pytest.raises(ValueError):
        validate_result(replace(evidence().eval_result, metrics=metrics))


@pytest.mark.parametrize("uncertainty", [True, -0.1, float("nan"), "unknown"])
def test_uncertainty_is_optional_or_nonnegative_finite(uncertainty):
    with pytest.raises(ValueError, match="uncertainty"):
        validate_result(replace(evidence().eval_result, uncertainty=uncertainty))


@pytest.mark.parametrize("change", [
    {"executor_status": "timeout"}, {"candidate_id": "other"}, {"attempt": True}, {"attempt": 0},
])
def test_executor_envelope_cannot_relabel_evaluator_evidence(change):
    with pytest.raises(ValueError):
        validate_evidence(replace(evidence(), **change))


def test_public_projection_removes_private_data_metrics_and_items_and_detaches_mutable_maps():
    original = evidence()
    visible = public_projection(original)
    validate_evidence(visible, require_full=False)
    assert visible.eval_result.contract.visibility == "public"
    assert visible.eval_result.contract.private == PrivateEvaluationData()
    assert [item.item_id for item in visible.eval_result.contract.items] == ["visible"]
    assert "hidden" not in json.dumps(asdict(visible)) and "holdout/score" not in json.dumps(asdict(visible))
    visible.eval_result.metrics["dev/score"] = 99
    visible.eval_result.contract.public.data["source"] = "changed"
    assert original.eval_result.metrics["dev/score"] == 0.5
    assert original.eval_result.contract.public.data["source"] == "visible"
    with pytest.raises(ValueError, match="full producer"):
        encode_evidence(visible)


def test_admission_view_has_no_cost_or_private_feedback_channel_and_checks_same_context():
    old, new = evidence("old"), evidence("new")
    new = replace(new, eval_result=replace(new.eval_result, metrics={"dev/score": 0.6}))
    view = comparison_projection(new)
    assert not hasattr(view.eval_result, "cost") and not hasattr(view.eval_result, "contract")
    assert not hasattr(view.eval_result, "text_feedback") and not hasattr(view, "result_text")
    assert MetricAdmission().judge(view, comparison_projection(old)).admit
    changed = replace(old, eval_result=replace(old.eval_result, contract=replace(old.eval_result.contract,
        binding=replace(old.eval_result.contract.binding, evaluation_context="sha256:" + "a" * 64))))
    with pytest.raises(ValueError, match="same evaluator"):
        MetricAdmission().judge(view, comparison_projection(changed))


def test_per_item_data_has_strict_typed_outcomes_and_unique_trial_identity():
    source = evidence()
    for items in ((ItemOutcome("x", True),), (ItemOutcome("x", 1), ItemOutcome("x", 0)),
                  (ItemOutcome("x", metrics={"loss": float("nan")}),), (ItemOutcome("x"),)):
        with pytest.raises(ValueError):
            validate_result(replace(source.eval_result, contract=replace(source.eval_result.contract, items=items)))


def test_failure_invocation_binding_does_not_claim_successful_producer_attestation():
    result = replace(evidence().eval_result, contract=replace(evidence().eval_result.contract,
                                                             binding_source="invocation"))
    with pytest.raises(ValueError, match="producer binding"):
        validate_result(result)
    validate_evidence(replace(evidence(), executor_status="failed_to_run",
        eval_result=replace(result, status=EvalStatus.FAILED_TO_RUN, metrics={})))


@pytest.mark.parametrize("eval_request", [EvalRequest("dev", time_limit=True), EvalRequest("dev", budget_token=1.5),
    EvalRequest("dev", seed_set=[True]), EvalRequest("dev", seed_set=[1, 1]), EvalRequest("dev", split_id=""),
    EvalRequest("dev", resume_from="")])
def test_invalid_requests_are_rejected_before_evaluation(eval_request):
    with pytest.raises(ValueError):
        validate_request(eval_request)


def test_request_digest_includes_split_fidelity_seeds_limits_and_resume_reference():
    baseline = EvalRequest("dev")
    variants = [replace(baseline, split_id="admission"), replace(baseline, fidelity="cheap"),
                replace(baseline, seed_set=[3]), replace(baseline, time_limit=1),
                replace(baseline, budget_token=2), replace(baseline, resume_from="artifact://x")]
    assert len({request_digest(baseline), *(request_digest(request) for request in variants)}) == 7


@pytest.mark.parametrize("eval_request", [EvalRequest("cheap"), EvalRequest("dev", split_id="admission"),
    EvalRequest("dev", seed_set=[]), EvalRequest("dev", time_limit=1), EvalRequest("dev", budget_token=1),
    EvalRequest("dev", resume_from="artifact://x")])
def test_legacy_adapter_does_not_echo_unsupported_requests_as_producer_claims(eval_request):
    class Uncalled:
        def __call__(self, *args):
            raise AssertionError("unsupported request reached producer")
    domain = LegacyPromptDomain(Uncalled(), MockLLM())
    with pytest.raises(ValueError, match="unconstrained dev"):
        asyncio.run(domain.evaluate(Proposal(Candidate("candidate"), "artifact"), eval_request))


def test_legacy_adapter_returns_bound_typed_canonical_result_and_preserves_executor_return():
    proposal, request = Proposal(Candidate("candidate"), "artifact"), EvalRequest("dev")
    domain = LegacyPromptDomain(toy_evaluator, MockLLM())
    result = asyncio.run(InProcessExecutor().execute(proposal, request, domain))
    expected = binding_for(proposal, request, evaluator_version="det-v1", evaluation_context="")
    validate_evidence(result, expected_binding=expected)
    assert result.eval_result.contract.binding.evaluation_context == ""  # explicitly legacy opaque
    assert result.eval_result.contract.token_accounting == "total_only"
    assert len(result.eval_result.contract.items) == 12
    assert result.eval_result.contract.binding_source == "producer"
    metadata = result.eval_result.contract.public.metadata
    assert metadata == {"adapter": "legacy_prompt", "reliability": {
        "n_trials": 1, "ci95": None, "noise_floor": 0.0}}
    assert decode_evidence(encode_evidence(result)).eval_result.contract.public.metadata == metadata
    visible = public_projection(result)
    visible.eval_result.contract.public.metadata["reliability"]["n_trials"] = 99
    assert metadata["reliability"]["n_trials"] == 1


def test_public_metadata_requires_finite_json_and_preserves_caller_public_data():
    source = evidence()
    result = replace(source.eval_result, contract=replace(source.eval_result.contract,
        public=PublicEvaluationData({"adapter": "producer-owned"}, {"reliability": {"variance": float("nan")}})))
    with pytest.raises(ValueError, match="finite JSON"):
        validate_result(result)


def test_executor_preserves_invalid_identity_for_driver_to_settle_known_cost_before_rejecting():
    returned = evidence("wrong").eval_result
    class Domain:
        async def evaluate(self, proposal, request):
            return returned
    actual = asyncio.run(InProcessExecutor().execute(Proposal(Candidate("candidate"), "artifact"),
                                                   EvalRequest("dev"), Domain()))
    assert actual.eval_result is returned and measured_costs(returned)["token"] == 5
    with pytest.raises(ValueError, match="candidate binding"):
        validate_evidence(actual)


def test_codec_rejects_unknown_schema_extra_fields_private_type_and_tampering():
    encoded = encode_evidence(evidence())
    variants = []
    changed = copy.deepcopy(encoded); changed["schema_version"] = True; variants.append(changed)
    changed = copy.deepcopy(encoded); changed["evidence"]["eval_result"]["extra"] = 1; variants.append(changed)
    changed = copy.deepcopy(encoded); changed["evidence"]["eval_result"]["contract"]["private"] = {}; variants.append(changed)
    changed = copy.deepcopy(encoded); changed["evidence"]["eval_result"]["contract"]["binding"]["artifact_sha256"] = "bad"; variants.append(changed)
    for value in variants:
        with pytest.raises(ValueError):
            decode_evidence(value)


def test_old_m0_canonical_construction_and_explicit_legacy_restore_do_not_invent_contract():
    old = EvidenceRecord("old", EvalResult(EvalStatus.OK, {"dev/score": 1}))
    raw = json.loads(json.dumps(asdict(old)))
    raw["eval_result"].pop("contract")
    restored = decode_evidence({"schema_version": 1, "evidence": raw}, allow_legacy=True)
    assert restored == old and restored.eval_result.contract is None
    with pytest.raises(UsageError):
        validate_evidence(restored)
    with pytest.raises(ValueError, match="cannot certify"):
        decode_evidence({"schema_version": 1, "evidence": raw}, allow_legacy=True,
                        expected_binding=evidence().eval_result.contract.binding)
