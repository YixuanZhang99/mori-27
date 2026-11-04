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
             {'candidate_id': 'child-1', 'lane': 'main', 'phase': 'operator'}}}
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
