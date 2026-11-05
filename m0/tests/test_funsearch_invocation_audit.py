"""Join selected evidence and constructed prompts to original provider starts."""
import asyncio
import copy
import json
import pytest
from core.composition.recovery import ContinuationStore
from core.composition.funsearch_coordinator import FunSearchCoordinator
from core.funsearch_invocation_audit import audit_funsearch_invocation
from test_funsearch_coordinator import SOURCE, FROZEN, policy, original_row, frontier


def fixture(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    result = coord.materialize('child-1', SOURCE, 'priority')
    pending = coord.policy.pending_selection()
    binding = {'selection': pending['receipt'], **{key: result[key] for key in
        ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs', 'binding_ref')}}
    recipe = {'kind': 'funsearch', 'task_desc': 'task',
              'parent_artifacts': [{'candidate_id': 'candidate-1', 'artifact': SOURCE}],
              'instructions': [result['prompt']], 'comparison': {'candidate-1': .7}, 'funsearch_binding': binding}
    request = {'recipe': recipe}
    start = {'binding': 'fake-fixture-only', 'invocation': {'external_context':
             {'candidate_id': 'child-1', 'lane': 'main', 'phase': 'operator', 'logical_run_id': 'run'}}}
    store.append('composed_provider_started', start)
    rows = list(store.read())
    return rows, request, len(rows) - 1


def audit(rows, request, index):
    return audit_funsearch_invocation(rows, index, request, **FROZEN)


def test_original_selection_and_program_prompt_are_bound_before_provider_start(tmp_path):
    rows, request, index = fixture(tmp_path)
    report = audit(rows, request, index)
    assert report['candidate_id'] == 'child-1' and report['samples'] == 1
    assert report['external_provider_requests'] == 0
    assert 'PRIVATE_SENTINEL' not in json.dumps(report)


def test_forged_prompt_evidence_or_wrong_order_is_rejected(tmp_path):
    rows, request, index = fixture(tmp_path)
    altered = copy.deepcopy(request); altered['recipe']['instructions'][0] += '# injection'
    with pytest.raises(ValueError): audit(rows, altered, index)
    altered = copy.deepcopy(rows)
    next(row for row in altered if row['kind'] == 'funsearch_materialization')['payload']['prompt_ref'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError): audit(altered, request, index)
    altered = copy.deepcopy(rows)
    selection = next(i for i, row in enumerate(altered) if row['kind'] == 'funsearch_selection')
    evidence = next(i for i, row in enumerate(altered) if row['kind'] == 'composed_evidence')
    altered[selection], altered[evidence] = altered[evidence], altered[selection]
    with pytest.raises(ValueError): audit(altered, request, index)
    altered = copy.deepcopy(rows); altered[index]['payload']['invocation']['external_context']['lane'] = 'control'
    with pytest.raises(ValueError): audit(altered, request, index)


def test_manifest_binding_requires_explicit_funsearch_policy_and_frozen_task(tmp_path):
    from core.composition.construction_audit import audit_funsearch_policy_binding
    rows, request, index = fixture(tmp_path)
    manifest = {'assembly': {'policy': {'name': 'funsearch', 'options': {
        'case_ids': FROZEN['case_ids'], 'metric': FROZEN['metric'], 'template': SOURCE,
        'template_ref': FROZEN['template_ref'], 'function_name': 'priority'}}},
        'domain_version': FROZEN['evaluator_version'],
        'evaluation_contexts': {'dev': FROZEN['evaluation_context']}}
    assert audit_funsearch_policy_binding(rows, index, request, manifest, 'run')['candidate_id'] == 'child-1'
    altered = copy.deepcopy(manifest); altered['assembly']['policy']['name'] = 'greedy'
    with pytest.raises(ValueError): audit_funsearch_policy_binding(rows, index, request, altered, 'run')
    altered = copy.deepcopy(manifest); altered['assembly']['policy']['options']['template'] += '# changed'
    with pytest.raises(ValueError): audit_funsearch_policy_binding(rows, index, request, altered, 'run')
    altered = copy.deepcopy(rows); altered[index]['payload']['invocation']['external_context']['logical_run_id'] = 'other'
    with pytest.raises(ValueError): audit_funsearch_policy_binding(altered, index, request, manifest, 'run')


def test_coherently_rehashed_forged_prompt_still_fails_original_reconstruction(tmp_path):
    from core.x1.checkpoint import payload_digest
    rows, request, index = fixture(tmp_path)
    altered = copy.deepcopy(request)
    recipe = altered['recipe']; binding = recipe['funsearch_binding']
    recipe['instructions'][0] += '# attacker replacement'
    binding['prompt_ref'] = 'sha256:' + payload_digest(recipe['instructions'][0])
    binding['binding_ref'] = 'sha256:' + payload_digest({key: binding[key] for key in
        ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs')})
    events = copy.deepcopy(rows)
    materialization = next(row['payload'] for row in events if row['kind'] == 'funsearch_materialization')
    materialization['prompt_ref'] = binding['prompt_ref']
    materialization['binding_ref'] = binding['binding_ref']
    with pytest.raises(ValueError, match='original materialization'):
        audit(events, altered, index)
