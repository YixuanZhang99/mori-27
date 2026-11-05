"""Strict external-provider ports, with no HTTP or currency-ledger access."""
import copy
import json

import pytest

from core.composition.governance import validate_factory_governance
from core.budget.ledger import BudgetError
from core.composition.registry import Registry
from core.executor.types import Candidate
from test_governed_budget import budget, settle
from test_governed_sessions import PROVIDER_BINDING


def capability():
    value = copy.deepcopy(PROVIDER_BINDING)
    value.update(schema_version=2, external_currency={"schema_version": 1, "bridge": "cny_invocation_v1"},
                 phase_call_limits={"operator": 2, "evaluation": 0})
    value["call_bound"]["units"]["token"] = 1052672
    return value


def context_data():
    from core.composition.external_provider import external_session_id
    value = {"schema_version": 1, "runtime_id": "composed-v8-governed-external",
        "logical_run_id": "a" * 32, "currency_run_id": "b" * 64, "campaign_id": "c" * 32,
        "policy_sha256": "d" * 64, "physical_plan_ref": "sha256:" + "e" * 64,
        "bridge_plan_ref": "sha256:" + "f" * 64, "lane": "control", "slot_id": "control-0000",
        "candidate_id": "candidate", "intent_id": "control:control-0000:operator",
        "physical_fingerprint": "sha256:" + "1" * 64, "account": "control", "operation": "operator",
        "phase": "operator", "ordinal": 0, "adapter_binding_sha256": "2" * 64,
        "argument_sha256": "3" * 64}
    value["session_id"] = external_session_id(value["logical_run_id"], value["lane"],
                                             value["slot_id"], value["adapter_binding_sha256"])
    return value


def outcome_data():
    return {"call_id": "a" * 64, "context_sha256": "b" * 64, "wire_request_sha256": "c" * 64,
        "response_sha256": "d" * 64, "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "result": "answer", "outcome": "returned", "currency_state": "settled", "integrity_reason": None,
        "outcome_ref": "sha256:" + "e" * 64, "provider_state": None}


class Bridge:
    def bind_run(self, context): pass
    def invoke(self, context, args, kwargs): pass
    def recover(self, context, argument_sha256): pass
    def finish_control(self, slot_id, terminal_ref): pass
    def audit(self): pass
    def replay_bundle(self): pass


def test_existing_v7_binding_and_serialization_are_unchanged():
    before = json.dumps(PROVIDER_BINDING, sort_keys=True, separators=(",", ":"))
    assert json.dumps(validate_factory_governance("provider", PROVIDER_BINDING),
                      sort_keys=True, separators=(",", ":")) == before
    with pytest.raises(ValueError):
        validate_factory_governance("provider", capability())


def test_external_capability_requires_explicit_registered_bridge():
    registry = Registry()
    with pytest.raises(ValueError):
        registry.install_external_bridge("cny_invocation_v1", object())
    registry.install_external_bridge("cny_invocation_v1", Bridge)
    first = registry.external_bridge("cny_invocation_v1")
    assert isinstance(first, Bridge)
    assert registry.external_bridge("cny_invocation_v1") is not first
    assert validate_factory_governance("provider", capability(),
        external_bridges=registry.external_bridge_names) == capability()
    with pytest.raises(ValueError):
        registry.install_external_bridge("cny_invocation_v1", Bridge)


@pytest.mark.parametrize("change", [
    lambda d: d["call_bound"].update(kind="estimate_only"),
    lambda d: d["phase_call_limits"].update(operator=True),
    lambda d: d["phase_call_limits"].update(operator=0),
    lambda d: d["phase_call_limits"].update(evaluation=-1),
    lambda d: d["phase_call_limits"].update(reflection=1),
    lambda d: d["phase_call_limits"].update(planning=-1),
    lambda d: d["phase_call_limits"].update(planning=True),
    lambda d: d["external_currency"].update(schema_version=True),
])
def test_estimate_only_or_ambiguous_external_capabilities_are_rejected(change):
    value = capability()
    change(value)
    with pytest.raises(ValueError):
        validate_factory_governance("provider", value, external_bridges=("cny_invocation_v1",))


def test_capacity_bound_does_not_fit_60000_tokens_or_one_call_of_a_two_call_phase():
    for token in (60000, 1052672):
        with pytest.raises(ValueError):
            validate_factory_governance("provider", capability(),
                reservation={"token": token, "node": 1, "eval_count": 0},
                external_bridges=("cny_invocation_v1",))
    assert validate_factory_governance("provider", capability(),
        reservation={"token": 2105344, "node": 1, "eval_count": 0},
        phase_reservations={"operator": {"token": 2105344}, "evaluation": {"token": 0}},
        external_bridges=("cny_invocation_v1",)) == capability()


def test_ordinal_identity_binds_phase_account_candidate_and_wire_request():
    from core.composition.external_provider import GovernedCallContext, external_call_id
    original = context_data()
    context = GovernedCallContext(**original)
    identifier = external_call_id(context, "4" * 64)
    assert external_call_id(context, "5" * 64) != identifier
    for key, value in (("ordinal", 1), ("candidate_id", "other")):
        changed = dict(original, **{key: value})
        assert external_call_id(GovernedCallContext(**changed), "4" * 64) != identifier
    for change in ({"account": "explore"}, {"phase": "evaluation"}, {"ordinal": True},
                   {"session_id": "0" * 64}, {"extra": "ignored"}):
        with pytest.raises(ValueError):
            GovernedCallContext(**dict(original, **change))


def test_outcome_is_deeply_detached_and_rejects_false_settlement():
    from core.composition.external_provider import ExternalCallOutcome
    source = outcome_data()
    outcome = ExternalCallOutcome(**source)
    source["usage"]["total_tokens"] = 999
    returned = outcome.usage
    returned["total_tokens"] = 1000
    assert outcome.to_dict()["usage"]["total_tokens"] == 5
    for change in ({"currency_state": "pending"}, {"usage": None}, {"response_sha256": None},
                   {"integrity_reason": "provider said secret text"}):
        with pytest.raises(ValueError):
            ExternalCallOutcome(**dict(outcome_data(), **change))
    refusal = dict(outcome_data(), outcome="known_refused", currency_state="not_admitted",
                   result=None, response_sha256=None, usage={"total_tokens": 0}, integrity_reason="capacity_refused")
    assert ExternalCallOutcome(**refusal).usage == {"total_tokens": 0}
    with pytest.raises(ValueError):
        ExternalCallOutcome(**dict(refusal, usage=None))


def test_run_context_excludes_trusted_capabilities_from_serialized_identity():
    from core.composition.external_provider import ExternalRunContext
    store, session = object(), lambda prompt: prompt
    controls = {"control-0000": capability()}
    value = ExternalRunContext(logical_run_id="a" * 32, runtime_id="composed-v8-governed-external",
        workdir="/tmp/unused", physical_plan={"plan_ref": "sha256:" + "b" * 64},
        main_provider_binding=capability(), control_provider_bindings=controls,
        mode="live", recorded_bundle=None, store=store,
        physical_identity_lookup=lambda intent, fingerprint: {},
        provider_sessions={"main": session, "control-0000": session})
    controls["control-0000"]["phase_call_limits"]["operator"] = 99
    assert value.control_provider_bindings["control-0000"]["phase_call_limits"]["operator"] == 2
    assert value.store is store and value.provider_sessions["main"] is session
    assert not {"store", "physical_identity_lookup", "provider_sessions"}.intersection(value.to_dict())
    with pytest.raises(ValueError):
        ExternalRunContext(**{**value.to_dict(), "recorded_bundle": {}, "store": store,
            "physical_identity_lookup": lambda *_: {}, "provider_sessions": dict(value.provider_sessions)})


def test_physical_identity_is_read_only_started_and_derives_account(tmp_path):
    controller = budget(tmp_path)
    candidate = Candidate("main")
    receipt = controller.reserve_operation("main-op", candidate, "main", "operator")
    with pytest.raises(BudgetError):
        controller.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
    controller.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    before = controller.store.path.read_bytes()
    value = controller.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
    assert value["account"] == "explore" and value["candidate_id"] == "main"
    assert value["phase"] == "operator" and value["lane"] == "main" and value["slot_id"] is None
    value["amounts"]["token"] = 999
    assert controller.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)["amounts"]["token"] == 50
    assert controller.store.path.read_bytes() == before
    with pytest.raises(BudgetError):
        controller.invocation_identity(receipt.intent_id, fingerprint="sha256:" + "0" * 64)
    settle(controller, receipt)
    with pytest.raises(BudgetError):
        controller.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)


def test_bridge_factory_cannot_reuse_live_run_authority_instance():
    shared = Bridge()
    registry = Registry()
    registry.install_external_bridge("cny_invocation_v1", lambda: shared)
    assert registry.external_bridge("cny_invocation_v1") is shared
    with pytest.raises(ValueError, match="reused"):
        registry.external_bridge("cny_invocation_v1")


def test_context_identity_attributes_cannot_be_mutated():
    from core.composition.external_provider import GovernedCallContext
    value = GovernedCallContext(**context_data())
    with pytest.raises(AttributeError):
        value.ordinal = 7


def test_zero_token_calls_still_consume_finite_ordinal():
    from core.composition.external_provider import validate_external_ordinal
    for ordinal in (0, 1):
        validate_external_ordinal(capability(), "operator", ordinal)
    with pytest.raises(ValueError, match="ordinal"):
        validate_external_ordinal(capability(), "operator", 2)
    with pytest.raises(ValueError, match="ordinal"):
        validate_external_ordinal(capability(), "evaluation", 0)


def test_supplier_unverified_sampling_is_explicit_and_external_only():
    value = capability()
    value["sampling"]["method"] = "supplier_unverified"
    assert validate_factory_governance("provider", value,
        external_bridges=("cny_invocation_v1",))["sampling"]["method"] == "supplier_unverified"
    legacy = copy.deepcopy(PROVIDER_BINDING)
    legacy["sampling"]["method"] = "supplier_unverified"
    with pytest.raises(ValueError):
        validate_factory_governance("provider", legacy)


def test_external_preflight_rejects_malformed_token_bound_before_multiplication():
    value = capability()
    value["call_bound"]["units"]["token"] = "1052672"
    with pytest.raises(ValueError):
        validate_factory_governance("provider", value, external_bridges=("cny_invocation_v1",),
                                   reservation={"token": 2105344},
                                   phase_reservations={"operator": {"token": 2105344}, "evaluation": {"token": 0}})


@pytest.mark.parametrize("usage", [
    {"total_tokens": 0, "prompt_tokens": 1},
    {"total_tokens": 5, "authorization": "must_not_be_persisted"},
    {"total_tokens": 5, "completion_tokens_details": {"reasoning_tokens": 6}},
])
def test_external_outcome_usage_cannot_embed_unknown_fields_or_inconsistent_counts(usage):
    from core.composition.external_provider import ExternalCallOutcome
    with pytest.raises(ValueError):
        ExternalCallOutcome(**dict(outcome_data(), usage=usage))


def test_external_plan_binding_is_immutable_and_keeps_authority_fields_opaque():
    from core.composition.external_provider import ExternalPlanBinding
    source = {"schema_version": 1, "runtime_id": "composed-v8-governed-external",
        "logical_run_id": "a" * 32, "physical_plan_ref": "sha256:" + "b" * 64,
        "bridge_plan_ref": "sha256:" + "c" * 64, "authority_binding": {"opaque": [1]}}
    value = ExternalPlanBinding(**source)
    source["authority_binding"]["opaque"].append(2)
    assert value.authority_binding == {"opaque": [1]}
    with pytest.raises(AttributeError):
        value.authority_binding = {}
    assert ExternalPlanBinding.from_dict(value.to_dict()) == value


def test_native_dev_identity_derives_evaluation_phase(tmp_path):
    from core.executor.types import EvalRequest
    controller = budget(tmp_path)
    request = controller.allocate(Candidate("native"))
    receipt = controller.reserve_operation("native-dev", Candidate("native"), "native", "dev", request=request)
    controller.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    identity = controller.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
    assert identity["operation"] == "dev" and identity["phase"] == "evaluation"


def test_external_bridge_name_is_resolved_before_construction(tmp_path):
    from test_governed_sessions import setup
    registry, _, _, config = setup(tmp_path)
    assert registry.external_bridge_name(config) is None
    built = []
    registry.install_external_bridge("cny_invocation_v1", lambda: built.append(True))
    declared = capability()
    declared["call_bound"]["units"]["token"] = 10
    declared["phase_call_limits"]["operator"] = 1
    registry.register("provider", "external_fixture", lambda *_: built.append(True), governance=declared)
    data = config.to_dict()
    data["governance"]["controls"]["provider"] = {"name": "external_fixture"}
    assert registry.external_bridge_name(data) == "cny_invocation_v1"
    assert built == []


def test_external_zero_hard_bound_fails_pure_preflight():
    declaration = capability()
    declaration['call_bound']['units']['token'] = 0
    with pytest.raises(ValueError, match='positive'):
        validate_factory_governance('provider', declaration, external_bridges=('cny_invocation_v1',))
    legacy = copy.deepcopy(PROVIDER_BINDING)
    legacy['call_bound']['units']['token'] = 0
    assert validate_factory_governance('provider', legacy)['call_bound']['units']['token'] == 0


def test_optional_planning_cap_is_finite_and_cannot_bypass_physical_reservation():
    from core.composition.external_provider import validate_external_ordinal
    declared = capability()
    declared['phase_call_limits']['planning'] = 4
    assert validate_factory_governance('provider', declared,
        external_bridges=('cny_invocation_v1',)) == declared
    for ordinal in range(4):
        validate_external_ordinal(declared, 'planning', ordinal)
    with pytest.raises(ValueError, match='ordinal'):
        validate_external_ordinal(declared, 'planning', 4)
    with pytest.raises(ValueError, match='reservations'):
        validate_factory_governance('provider', declared, external_bridges=('cny_invocation_v1',),
            phase_reservations={'planning': {'token': 3 * 1052672},
                                'operator': {'token': 2 * 1052672}, 'evaluation': {'token': 0}})
