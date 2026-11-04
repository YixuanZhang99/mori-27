"""Bridge a validated program selection into the construction contract."""
import copy
from types import SimpleNamespace
import pytest
from core.composition.contracts import OperatorRequest, Proposal
from core.executor.types import Candidate
from core.composition.construction import ConstructionPlan
from core.composition.construction_recipes import FunSearchRecipeOperator
from test_construction import ROLES
from test_funsearch_construction_plan import fixture


def request():
    context, candidate, spec, recipe = fixture()
    selection = recipe['funsearch_binding']['selection']
    result = {key: recipe['funsearch_binding'][key] for key in
              ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs', 'binding_ref')}
    result.update(prompt=recipe['instructions'][0], samples=selection['samples'])
    parent = Proposal(Candidate('p1'), recipe['parent_artifacts'][0]['artifact'])
    evidence = SimpleNamespace(candidate_id='p1', eval_result=SimpleNamespace(metrics={'dev/score': .5}))
    request = OperatorRequest('Solve task', 'child', 1, (parent,), (evidence,), {},
                              {'funsearch': {'selection': selection, 'materialization': result}})
    return context, candidate, spec, recipe, request


def test_recipe_preserves_duplicate_program_samples_and_binds_construction_plan():
    context, candidate, spec, expected, request_value = request()
    recipe = FunSearchRecipeOperator().recipe(request_value)
    assert recipe == expected
    assert ConstructionPlan.create(candidate, recipe, spec, context, roles=ROLES).to_dict()['recipe'] == expected


def test_recipe_rejects_missing_or_changed_selection_and_parent_evidence():
    _, _, _, _, value = request()
    corrupt = copy.deepcopy(value.strategy)
    corrupt['funsearch']['materialization']['samples'] = ['p1']
    with pytest.raises(ValueError):
        FunSearchRecipeOperator().recipe(OperatorRequest(value.task_desc, value.candidate_id, 1,
            value.parents, value.evidence, value.context, corrupt))
    with pytest.raises(ValueError):
        FunSearchRecipeOperator().recipe(OperatorRequest(value.task_desc, value.candidate_id, 1,
            value.parents, (), value.context, value.strategy))
