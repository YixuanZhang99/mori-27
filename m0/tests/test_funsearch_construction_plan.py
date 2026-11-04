"""Construction-plan binding for ordered FunSearch prompt samples."""
import copy
import pytest
from core.composition.construction import ConstructionPlan
from core.executor.types import Candidate, ExecutorSpec
from core.x1.checkpoint import payload_digest
from test_construction import ROLES, pack


def fixture():
    context = pack()
    candidate = Candidate('child', parents=['p1'], hypothesis='Improve', context_pack_ref=context.ref)
    spec = ExecutorSpec('coder', True, 'Improve', [])
    prompt = 'def priority_v0(x):\n    return x\n\ndef priority_v1(x):\n    '
    selection = {'schema_version': 2, 'requested_island': 0, 'island': 0, 'epoch': 0,
                 'samples': ['p1', 'p1'], 'ancestry': ['p1'], 'eligible': ['p1'],
                 'state_before_ref': 'sha256:' + 'c' * 64, 'state_after_ref': 'sha256:' + 'd' * 64}
    binding = {'selection': selection, 'selection_ref': 'sha256:' + payload_digest(selection),
               'input_ref': 'sha256:' + 'a' * 64, 'prompt_ref': 'sha256:' + payload_digest(prompt),
               'evidence_refs': {'p1': 'sha256:' + 'b' * 64}}
    binding['binding_ref'] = 'sha256:' + payload_digest({k: binding[k] for k in
        ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs')})
    recipe = {'kind': 'funsearch', 'task_desc': 'Solve task',
              'parent_artifacts': [{'candidate_id': 'p1', 'artifact': 'def priority(x):\n    return x\n'}],
              'instructions': [prompt], 'comparison': {'p1': 0.5}, 'funsearch_binding': binding}
    return context, candidate, spec, recipe


def test_construction_plan_preserves_duplicate_samples_and_binds_prompt():
    context, candidate, spec, recipe = fixture()
    plan = ConstructionPlan.create(candidate, recipe, spec, context, roles=ROLES)
    assert plan.to_dict()['recipe']['funsearch_binding']['selection']['samples'] == ['p1', 'p1']
    assert plan.to_dict()['candidate']['parents'] == ['p1']


def test_construction_plan_rejects_prompt_selection_and_evidence_substitution():
    context, candidate, spec, recipe = fixture()
    changes = []
    value = copy.deepcopy(recipe); value['instructions'][0] += '# replaced'; changes.append(value)
    value = copy.deepcopy(recipe); value['funsearch_binding']['selection']['samples'][0] = 'foreign'; changes.append(value)
    value = copy.deepcopy(recipe); value['funsearch_binding']['evidence_refs']['p1'] = 'sha256:' + '0' * 64; changes.append(value)
    for value in changes:
        with pytest.raises(ValueError):
            ConstructionPlan.create(candidate, value, spec, context, roles=ROLES)
