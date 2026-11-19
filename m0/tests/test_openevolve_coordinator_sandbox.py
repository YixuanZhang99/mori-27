"""Coordinator decisions must be anchored in the immutable run journal."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

from core.composition.openevolve_policy import OpenEvolvePolicy
from core.composition.recovery import ContinuationStore
from core.memory.types import ScopeContext
from test_openevolve_prompt_sandbox import setup_material
from test_openevolve_state import new_adapter


def make_policy():
    return OpenEvolvePolicy(ScopeContext('run', 'task', 'domain'), adapter=new_adapter(num_islands=1, migration_interval=50))


def frontier(*ids):
    return SimpleNamespace(nodes={name: SimpleNamespace(id=name, status='done', eval_status='ok', score=.5)
                                  for name in ids})


def test_original_journal_anchors_host_selection_prompt_and_resume(tmp_path):
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    p = make_policy()
    coord = OpenEvolveCoordinator(p, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0])
    coord.record_evaluated('root')
    assert asyncio.run(coord.select('child', frontier('root'), {})) == ['root']
    first = coord.materialize('child', evolution_round=1)
    store.append('composed_evidence', rows[1])
    coord.record_evaluated('child')
    parents = asyncio.run(coord.select('next', frontier('root', 'child'), {}))
    prompt = coord.materialize('next', evolution_round=2)
    assert len(parents) == 1 and parents[0] in {'root', 'child'}
    assert prompt['primary']['candidate_id'] == parents[0]
    assert 'PRIVATE_SENTINEL_81' not in repr(prompt)
    saved = p.checkpoint_state()
    restored = make_policy()
    restored.restore_state(saved, [r['payload'] for r in store.read('openevolve_host_event')])
    resumed = OpenEvolveCoordinator(restored, store, logical_run_id='run', domain=domain)
    assert resumed.materialize('next', evolution_round=2) == prompt
    assert first['prompt_ref'] != prompt['prompt_ref']
    assert len(list(store.read('openevolve_prompt'))) == 2


def test_failed_host_journal_append_stops_prompt_and_future_dispatch(tmp_path, monkeypatch):
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    p = make_policy(); coord = OpenEvolveCoordinator(p, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0]); coord.record_evaluated('root')
    append = store.append
    def fail(kind, payload):
        if kind == 'openevolve_host_event': raise OSError('journal failure')
        return append(kind, payload)
    monkeypatch.setattr(store, 'append', fail)
    with pytest.raises(OSError):
        asyncio.run(coord.select('child', frontier('root'), {}))
    with pytest.raises(ValueError): coord.materialize('child', evolution_round=1)
    with pytest.raises(ValueError): asyncio.run(coord.select('later', frontier('root'), {}))


def test_substituted_original_artifact_is_rejected_before_host_selection(tmp_path, monkeypatch):
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    p = make_policy(); coord = OpenEvolveCoordinator(p, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0]); coord.record_evaluated('root')
    read = coord._rows
    def forged(kind):
        result = copy.deepcopy(read(kind))
        if kind == 'composed_evidence': result[0]['proposal']['artifact'] += '\n# forged'
        return result
    monkeypatch.setattr(coord, '_rows', forged)
    before = p.adapter.checkpoint_state()
    with pytest.raises(ValueError): asyncio.run(coord.select('child', frontier('root'), {}))
    assert p.adapter.checkpoint_state() == before


def test_crash_after_host_selection_replays_original_uuid_and_timestamp(tmp_path, monkeypatch):
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    from core.x1.checkpoint import RunCheckpoint
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    def two_island_policy():
        return OpenEvolvePolicy(ScopeContext('run', 'task', 'domain'),
                                adapter=new_adapter(num_islands=2, migration_interval=50))
    p = two_island_policy(); coord = OpenEvolveCoordinator(p, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0]); coord.record_evaluated('root')
    asyncio.run(coord.select('child', frontier('root'), {})); coord.materialize('child', evolution_round=1)
    store.append('composed_evidence', rows[1]); coord.record_evaluated('child')
    saved = p.checkpoint_state()
    checkpoint = RunCheckpoint.create({'git_state': {}, 'inflight_executor': [], 'messages': [], 'policy': saved})
    store.append('composed_checkpoint', {'sha256': checkpoint.payload_sha256})
    append = store.append
    def crash_after_write(kind, payload):
        append(kind, payload)
        if kind == 'openevolve_host_event' and payload['kind'] == 'select':
            raise OSError('simulated crash after host event is durable')
    monkeypatch.setattr(store, 'append', crash_after_write)
    with pytest.raises(OSError):
        asyncio.run(coord.select('next', frontier('root', 'child'), {}))
    terminal_event = [r['payload'] for r in store.read('openevolve_host_event')][-1]
    assert any(item[0] == 'uuid' for item in terminal_event['tape'])
    restored_store = ContinuationStore(store.path, checkpoint)
    restored = two_island_policy()
    restored.restore_state(saved, [r['payload'] for r in restored_store.read('openevolve_host_event')])
    restored_store.resume()
    resumed = OpenEvolveCoordinator(restored, restored_store, logical_run_id='run', domain=domain)
    parents = asyncio.run(resumed.select('next', frontier('root', 'child'), {}))
    assert parents == [terminal_event['result']['source_candidate_id']]
    assert restored.adapter.events[-1] == terminal_event
    assert len(list(restored_store.read('openevolve_host_event'))) == len(p.adapter.events)
    assert resumed.materialize('next', evolution_round=2)['selection']['host_parent_id'] == terminal_event['result']['host_parent_id']


def test_failed_construction_can_be_abandoned_without_fabricating_execution(tmp_path):
    from dataclasses import asdict
    from core.composition.contracts import Proposal
    from core.composition.evaluation import binding_for, encode_evidence
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    from core.executor.evaluation_contract import EvaluationContract
    from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
    from core.x1.checkpoint import payload_digest
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    policy = make_policy(); coord = OpenEvolveCoordinator(policy, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0]); coord.record_evaluated('root')
    asyncio.run(coord.select('child', frontier('root'), {})); coord.materialize('child', evolution_round=1)
    proposal = Proposal(Candidate('child', parents=['root'], hypothesis='fixed'), '')
    request = EvalRequest(fidelity='dev', split_id='dev')
    binding = binding_for(proposal, request, evaluator_version=domain.evaluator_version,
                          evaluation_context=domain.evaluation_contexts['dev'])
    result = EvalResult(EvalStatus.FAILED_TO_RUN, cost=CostVec(), fidelity='dev',
                        contract=EvaluationContract(binding, ('token', 'eval_count'), binding_source='invocation'))
    encoded = encode_evidence(EvidenceRecord('child', result, executor_status='failed_to_run'))
    ref = 'sha256:' + payload_digest({'logical_run_id': 'run', 'evidence': encoded})
    store.append('composed_evidence', {'cycle': 1, 'proposal': asdict(proposal),
                                      'evidence_ref': ref, 'evidence': encoded['evidence']})
    coord.abandon('child', 'patch_exhausted')
    assert policy.adapter.database.get('child') is None
    assert policy.adapter.events[-1]['kind'] == 'abandon'
    assert asyncio.run(coord.select('next', frontier('root'), {})) == ['root']


def test_original_prompt_tampering_stops_later_host_selection(tmp_path, monkeypatch):
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    policy = make_policy(); coord = OpenEvolveCoordinator(policy, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0]); coord.record_evaluated('root')
    asyncio.run(coord.select('child', frontier('root'), {})); coord.materialize('child', evolution_round=1)
    store.append('composed_evidence', rows[1]); coord.record_evaluated('child')
    original = coord._rows
    def changed(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'openevolve_prompt': rows[0]['prompt_ref'] = 'sha256:' + '0' * 64
        return rows
    monkeypatch.setattr(coord, '_rows', changed)
    before = policy.adapter.checkpoint_state()
    with pytest.raises(ValueError):
        asyncio.run(coord.select('next', frontier('root', 'child'), {}))
    assert policy.adapter.checkpoint_state() == before


def test_registration_rejects_rehashed_wrong_evaluation_request(tmp_path):
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    from core.x1.checkpoint import payload_digest
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    row = copy.deepcopy(rows[0])
    row['evidence']['eval_result']['contract']['binding']['request_sha256'] = 'sha256:' + '0' * 64
    row['evidence_ref'] = 'sha256:' + payload_digest({'logical_run_id': 'run',
        'evidence': {'schema_version': 1, 'evidence': row['evidence']}})
    store = ContinuationStore(tmp_path / 'journal.jsonl'); store.append('composed_evidence', row)
    policy = make_policy(); coord = OpenEvolveCoordinator(policy, store, logical_run_id='run', domain=domain)
    with pytest.raises(ValueError): coord.record_evaluated('root')
    assert policy.adapter.events == []


def test_failed_physical_evaluation_is_abandoned_with_original_measured_evidence(tmp_path):
    from dataclasses import asdict
    from core.composition.contracts import Proposal
    from core.composition.evaluation import encode_evidence
    from core.composition.openevolve_runtime import OpenEvolveCoordinator
    from core.executor.types import Candidate, EvalRequest, EvalStatus, EvidenceRecord
    from core.x1.checkpoint import payload_digest
    domain, _, rows, _ = setup_material(tmp_path / 'geometry')
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    policy = make_policy(); coord = OpenEvolveCoordinator(policy, store, logical_run_id='run', domain=domain)
    store.append('composed_evidence', rows[0]); coord.record_evaluated('root')
    asyncio.run(coord.select('bad', frontier('root'), {})); coord.materialize('bad', evolution_round=1)
    proposal = Proposal(Candidate('bad', parents=['root'], hypothesis='fixed'),
                        'def run_packing():\n    raise RuntimeError("failed")\n')
    result = asyncio.run(domain.evaluate(proposal, EvalRequest(fidelity='dev', split_id='dev')))
    assert result.status is EvalStatus.FAILED_TO_RUN and result.cost.eval_count == 1
    encoded = encode_evidence(EvidenceRecord('bad', result, executor_status='failed_to_run'))
    ref = 'sha256:' + payload_digest({'logical_run_id': 'run', 'evidence': encoded})
    store.append('composed_evidence', {'cycle': 1, 'proposal': asdict(proposal),
                                      'evidence_ref': ref, 'evidence': encoded['evidence']})
    coord.abandon('bad', 'evaluation_failed')
    assert policy.adapter.database.get('bad') is None
    assert asyncio.run(coord.select('later', frontier('root'), {})) == ['root']
