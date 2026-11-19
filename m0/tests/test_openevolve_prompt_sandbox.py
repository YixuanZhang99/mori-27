"""Build vendor prompts only from real source-bound development evidence."""
import asyncio
import copy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from core.composition.contracts import Proposal
from core.composition.evaluation import encode_evidence
from core.executor.evaluation_contract import PrivateEvaluationData
from core.executor.types import Candidate, EvalRequest, EvidenceRecord
from core.x1.checkpoint import payload_digest
from test_circle_packing_sandbox import GRID
from test_openevolve_state import new_adapter
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.composed_domain import SandboxRunner


def setup_material(tmp_path):
    domain = CirclePackingDomain(tmp_path, runner=SandboxRunner())
    adapter = new_adapter(num_islands=1, migration_interval=50)
    rows = []
    for i, name in enumerate(('root', 'child')):
        source = GRID + f'\n# {name}\n'
        proposal = Proposal(Candidate(name, parents=[] if i == 0 else ['root'], hypothesis='fixed'), source)
        result = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
        private = replace(result.contract.private, data={**result.contract.private.data,
                                                           'sentinel': 'PRIVATE_SENTINEL_81'})
        result = replace(result, contract=replace(result.contract, private=private))
        evidence = EvidenceRecord(name, result)
        encoded = encode_evidence(evidence)
        ref = 'sha256:' + payload_digest({'logical_run_id': 'run', 'evidence': encoded})
        row = {'cycle': i, 'proposal': asdict(proposal), 'evidence_ref': ref, 'evidence': encoded['evidence']}
        rows.append(row)
        selection = None if i == 0 else adapter.select(name, {'root'})
        adapter.register(name, source, {'combined_score': result.metrics['dev/score']}, ref,
                         iteration=i, selection=selection)
    selection = adapter.select('next', {'root', 'child'})
    return domain, adapter, rows, selection


def test_actual_vendor_prompt_is_bound_to_parent_inspirations_and_original_dev_evidence(tmp_path):
    from core.composition.openevolve_prompt import build_bound_prompt
    domain, adapter, rows, selection = setup_material(tmp_path)
    built = build_bound_prompt(selection, adapter.events, rows, logical_run_id='run',
                               evaluator_version=domain.evaluator_version,
                               evaluation_context=domain.evaluation_contexts['dev'])
    assert built['selection']['source_candidate_id'] in {'root', 'child'}
    assert built['system'] and built['user'] and 'run_packing' in built['user']
    assert 'SEARCH' in built['user'] and 'PRIVATE_SENTINEL_81' not in repr(built)
    assert built['input_ref'].startswith('sha256:') and built['prompt_ref'].startswith('sha256:')
    assert built['primary']['candidate_id'] != built['inspirations'][0]['candidate_id']
    assert built == build_bound_prompt(selection, adapter.events, rows, logical_run_id='run',
                                       evaluator_version=domain.evaluator_version,
                                       evaluation_context=domain.evaluation_contexts['dev'])


def test_prompt_rejects_forged_selection_parent_or_original_evidence(tmp_path):
    from core.composition.openevolve_prompt import build_bound_prompt
    domain, adapter, rows, selection = setup_material(tmp_path)
    def build(choice, events, source_rows):
        return build_bound_prompt(choice, events, source_rows, logical_run_id='run',
                                  evaluator_version=domain.evaluator_version,
                                  evaluation_context=domain.evaluation_contexts['dev'])
    forged = copy.deepcopy(selection)
    forged['evidence_ref'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError): build(forged, adapter.events, rows)
    altered = copy.deepcopy(rows)
    altered[0]['proposal']['artifact'] += '\n# forged'
    with pytest.raises(ValueError): build(selection, adapter.events, altered)
    with pytest.raises(ValueError): build(selection, adapter.events[:-1], rows)
    with pytest.raises(ValueError): build(selection, adapter.events, rows + [copy.deepcopy(rows[0])])


def test_prompt_refuses_drifted_pinned_configuration(tmp_path, monkeypatch):
    import core.composition.openevolve_prompt as module
    domain, adapter, rows, selection = setup_material(tmp_path)
    altered = tmp_path / 'modified.yaml'
    altered.write_bytes(module._CONFIG.read_bytes() + b'\n# changed\n')
    monkeypatch.setattr(module, '_CONFIG', altered)
    with pytest.raises(ValueError, match='source'):
        module.build_bound_prompt(selection, adapter.events, rows, logical_run_id='run',
                                  evaluator_version=domain.evaluator_version,
                                  evaluation_context=domain.evaluation_contexts['dev'])


def test_prompt_rejects_rehashed_wrong_development_request(tmp_path):
    from core.composition.openevolve_prompt import build_bound_prompt
    domain, adapter, rows, selection = setup_material(tmp_path)
    rows, selection, events = copy.deepcopy(rows), copy.deepcopy(selection), adapter.events
    source = selection['source_candidate_id']
    row = next(item for item in rows if item['proposal']['candidate']['id'] == source)
    row['evidence']['eval_result']['contract']['binding']['request_sha256'] = 'sha256:' + '0' * 64
    ref = 'sha256:' + payload_digest({'logical_run_id': 'run',
        'evidence': {'schema_version': 1, 'evidence': row['evidence']}})
    row['evidence_ref'] = ref
    selection['evidence_ref'] = ref
    for item in selection['inspirations']:
        if item['source_candidate_id'] == source: item['evidence_ref'] = ref
    events[-1]['result'] = copy.deepcopy(selection)
    with pytest.raises(ValueError):
        build_bound_prompt(selection, events, rows, logical_run_id='run',
                           evaluator_version=domain.evaluator_version,
                           evaluation_context=domain.evaluation_contexts['dev'])
