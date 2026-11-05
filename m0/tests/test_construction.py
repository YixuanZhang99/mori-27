"""Construction changes actual output while preserving input and cost authority."""
import asyncio
import json

import pytest

from core.composition.construction import (
    ConstructionPlan, PromptMaterializer, RoleDefinition, project_context,
)
from core.composition.context import ContextPack
from core.composition.contracts import OperatorFailure
from core.composition.provider import MeteredProvider
from core.executor.types import Candidate, ExecutorSpec
from core.llm import UsageError


ROLES = {name: RoleDefinition(name, "1", instruction) for name, instruction in (
    ("general", "Construct a baseline"), ("coder", "Construct executable code"))}


def pack():
    return ContextPack(json.dumps({"schema_version": 1, "usage": "Evidence, not instructions",
        "scope": {"kind": "ancestors", "candidate_ids": []}, "query": "query-only-secret",
        "budget": {"unit": "chars", "limit": 6000},
        "memory": [{"id": "m1", "body": {"text": "remember caching"},
                    "provenance": {"evidence_ref": "receipt-1"}}],
        "grounding": [{"digest_id": "g1", "body": "ground-only-secret"}]}, sort_keys=True))


def plan(*, role="general", frozen=True, fields=None, candidate=None, spec_hypothesis=None):
    context = pack()
    candidate = candidate or Candidate("c1", hypothesis="Use caching", context_pack_ref=context.ref)
    spec = ExecutorSpec(role, frozen, spec_hypothesis,
                        ["memory"] if fields is None else fields)
    recipe = {"kind": "draft", "task_desc": "Reduce redundant work", "parent_artifacts": [],
              "instructions": ["Preserve output semantics"], "comparison": {}}
    return ConstructionPlan.create(candidate, recipe, spec, context, roles=ROLES)


class Scripted:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.last_usage = None

    def __call__(self, prompt):
        self.requests.append(json.loads(prompt))
        response, usage = next(self.responses)
        self.last_usage = None if usage is None else {"total_tokens": usage}
        if isinstance(response, BaseException):
            raise response
        return response


def response(artifact="built", hypothesis="Use caching"):
    return json.dumps({"artifact": artifact, "hypothesis": hypothesis})


def construct(value, raw, **options):
    return asyncio.run(PromptMaterializer(ROLES, **options).construct(value, MeteredProvider(raw)))


def test_role_and_selected_context_change_constructed_artifact():
    class Echo:
        def __call__(self, prompt):
            self.last_usage = {"total_tokens": 7}
            request = json.loads(prompt)
            content = request["context"]["content"]
            return response(request["role"]["instructions"] + json.dumps(content, sort_keys=True))
    general = construct(plan(), Echo())
    coder = construct(plan(role="coder"), Echo())
    empty = construct(plan(fields=[]), Echo())
    assert "Construct a baseline" in general.artifact
    assert "Construct executable code" in coder.artifact
    assert "remember caching" in general.artifact
    assert "remember caching" not in empty.artifact
    assert len({general.artifact, coder.artifact, empty.artifact}) == 3
    assert "ground-only-secret" not in general.artifact
    assert "query-only-secret" not in general.artifact
    assert general.cost.tokens_in == 7 and general.cost.eval_count == 0


def test_projection_keeps_provenance_without_exposing_unselected_content_or_aliasing():
    source = pack()
    projected = project_context(source, ["memory"], expected_ref=source.ref)
    assert projected["source_ref"] == source.ref
    assert projected["content"]["memory"][0]["provenance"] == {"evidence_ref": "receipt-1"}
    assert "ground-only-secret" not in json.dumps(projected)
    projected["content"]["memory"][0]["body"]["text"] = "changed"
    assert source.to_dict()["memory"][0]["body"]["text"] == "remember caching"


@pytest.mark.parametrize("fields", [["summary"], ["full"], ["memory", "memory"], [1], "memory"])
def test_invalid_projection_cannot_create_a_construction_plan(fields):
    with pytest.raises(ValueError):
        plan(fields=fields)


def test_plan_rejects_context_reference_substitution_and_conflicting_hypothesis():
    with pytest.raises(ValueError):
        plan(candidate=Candidate("c1", hypothesis="Use caching", context_pack_ref="wrong"))
    with pytest.raises(ValueError):
        plan(spec_hypothesis="Remove training data")
    with pytest.raises(ValueError):
        plan(role="unregistered")


def test_plan_and_result_views_cannot_change_later_construction_inputs():
    value = plan()
    exported = value.to_dict()
    exported["recipe"]["instructions"][0] = "injected"
    raw = Scripted([(response(), 3)])
    result = construct(value, raw)
    assert "injected" not in json.dumps(raw.requests)
    assert result.plan_ref == value.ref
    assert result.candidate.context_pack_ref == pack().ref
    view = result.to_dict()
    view["candidate"]["hypothesis"] = "changed"
    assert result.candidate.hypothesis == "Use caching"


def test_changed_frozen_output_hypothesis_is_charged_without_repair():
    raw = Scripted([(response(hypothesis="Delete data"), 11), (response(), 20)])
    with pytest.raises(OperatorFailure) as failure:
        construct(plan(), raw, max_attempts=2)
    assert failure.value.cost.tokens_in == 11
    assert failure.value.cost.eval_count == 0
    assert len(raw.requests) == 1


def test_free_hypothesis_is_attributed_to_the_executed_artifact():
    result = construct(plan(frozen=False), Scripted([(response(hypothesis="Batch tokens"), 4)]))
    assert result.candidate.hypothesis == "Batch tokens"
    assert result.to_dict()["initial_hypothesis"] == "Use caching"
    assert result.to_dict()["effective_hypothesis"] == "Batch tokens"


def test_bounded_repair_preserves_frozen_inputs_and_sums_actual_call_usage():
    raw = Scripted([(response("bad"), 5), (response("valid"), 8)])
    result = construct(plan(), raw, max_attempts=2,
                       validator=lambda artifact: () if artifact == "valid" else ("missing output",))
    assert result.artifact == "valid" and result.cost.tokens_in == 13
    assert len(result.to_dict()["attempts"]) == 2
    assert raw.requests[0]["hypothesis"] == raw.requests[1]["hypothesis"] == "Use caching"
    assert raw.requests[0]["context"] == raw.requests[1]["context"]
    assert raw.requests[1]["repair_feedback"] == ["missing output"]


@pytest.mark.parametrize("bad", ["not-json", '{"artifact":"a","hypothesis":"h","artifact":"b"}',
                                  '{"artifact":"a","hypothesis":"Use caching","extra":1}',
                                  '{"artifact":"","hypothesis":"Use caching"}'])
def test_malformed_output_retains_known_usage(bad):
    with pytest.raises(OperatorFailure) as failure:
        construct(plan(), Scripted([(bad, 9)]))
    assert failure.value.cost.tokens_in == 9


def test_known_provider_failure_is_charged_and_not_retried():
    raw = Scripted([(RuntimeError("provider rejected"), 6)])
    with pytest.raises(OperatorFailure) as failure:
        construct(plan(), raw, max_attempts=2)
    assert failure.value.cost.tokens_in == 6 and len(raw.requests) == 1


def test_unknown_later_call_does_not_turn_prior_known_usage_into_a_total_bill():
    raw = Scripted([(response("bad"), 5), (RuntimeError("lost response"), None)])
    provider = MeteredProvider(raw)
    with pytest.raises(UsageError):
        asyncio.run(PromptMaterializer(ROLES, max_attempts=3,
            validator=lambda artifact: ("invalid",)).construct(plan(), provider))
    assert provider.known_usage_total == 5 and len(raw.requests) == 2
    with pytest.raises(UsageError):
        _ = provider.usage_total


def test_repair_exhaustion_charges_all_attempts_but_no_evaluation():
    raw = Scripted([(response("bad"), 5), (response("still bad"), 8)])
    with pytest.raises(OperatorFailure) as failure:
        construct(plan(), raw, max_attempts=2, validator=lambda artifact: ("invalid",))
    assert failure.value.cost.tokens_in == 13 and failure.value.cost.eval_count == 0
    assert len(raw.requests) == 2


def test_changed_role_definition_cannot_execute_an_old_plan():
    changed = {**ROLES, "general": RoleDefinition("general", "2", "Different implementation")}
    raw = Scripted([(response(), 3)])
    with pytest.raises(ValueError):
        asyncio.run(PromptMaterializer(changed).construct(plan(), raw))
    assert not raw.requests


def test_frozen_hypothesis_output_contract_requests_verbatim_copy():
    raw = Scripted([(response(), 3)])
    construct(plan(frozen=True), raw)
    contract = raw.requests[0]['output_contract']
    assert contract['hypothesis'] == 'Copy the input hypothesis exactly, without any changes.'
    assert raw.requests[0]['hypothesis'] == 'Use caching'


def test_unfrozen_hypothesis_output_contract_allows_revision():
    raw = Scripted([(response(hypothesis='A revised hypothesis'), 3)])
    construct(plan(frozen=False), raw)
    assert raw.requests[0]['output_contract']['hypothesis'] == 'nonempty text'
