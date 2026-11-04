"""Durable selection coordination; fixture performs no provider calls."""
import asyncio
import hashlib
from dataclasses import replace
from types import SimpleNamespace
import pytest
from core.composition.evaluation import encode_evidence
from core.composition.funsearch_coordinator import FunSearchCoordinator
from core.composition.funsearch_policy import FunSearchPolicy
from core.composition.recovery import ContinuationStore
from core.funsearch_public_evidence import project_program_candidate
from core.memory.types import ScopeContext
from test_funsearch_public_evidence import evidence

SOURCE = 'def priority(x):\n    return x\n'
FROZEN = dict(case_ids=['a', 'b'], metric='score', logical_run_id='run', evaluator_version='eval-v1',
              evaluation_context='sha256:' + 'c' * 64,
              template_ref='sha256:' + hashlib.sha256(SOURCE.encode()).hexdigest(), function_name='priority')


def policy():
    return FunSearchPolicy(ScopeContext('run', 'task', 'domain'), case_ids=['a', 'b'], islands=2,
        seed=4, prompt_size=2, temperature=1, temperature_period=10)


def original_row(candidate='candidate-1', artifact=SOURCE):
    item = evidence()
    binding = replace(item.eval_result.contract.binding, candidate_id=candidate,
                      artifact_sha256=hashlib.sha256(artifact.encode()).hexdigest())
    item = replace(item, candidate_id=candidate, eval_result=replace(item.eval_result,
        contract=replace(item.eval_result.contract, binding=binding)))
    projection = project_program_candidate(item, artifact, case_ids=['a', 'b'], metric='score', logical_run_id='run')
    return {'cycle': 0, 'proposal': {'candidate': {'id': candidate}, 'artifact': artifact},
            'evidence_ref': projection['evidence_ref'], 'evidence': encode_evidence(item)['evidence']}


def frontier(*names):
    return SimpleNamespace(nodes={name: SimpleNamespace(id=name, status='done', eval_status='ok', score=1)
                                  for name in names})


def test_durable_selection_and_materialization_resume_without_extra_calls(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    p = policy(); coord = FunSearchCoordinator(p, store, **FROZEN)
    coord.record_evaluated('candidate-1')
    assert asyncio.run(coord.select('child-1', frontier('candidate-1'), {})) == ['candidate-1']
    expected = coord.materialize('child-1', SOURCE, 'priority')
    saved = p.checkpoint_state()
    restarted = policy(); restarted.restore_state(saved)
    replayed = FunSearchCoordinator(restarted, store, **FROZEN).materialize('child-1', SOURCE, 'priority')
    assert expected == replayed
    assert 'PRIVATE_SENTINEL' not in repr(expected)
    assert len(list(store.read('funsearch_selection'))) == 1
    with pytest.raises(ValueError):
        coord.materialize('different-child', SOURCE, 'priority')


def test_failed_selection_journal_write_cannot_be_materialized(tmp_path, monkeypatch):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    p = policy(); coord = FunSearchCoordinator(p, store, **FROZEN)
    coord.record_evaluated('candidate-1')
    append = store.append
    def fail(kind, payload):
        if kind == 'funsearch_selection':
            raise OSError('simulated journal failure')
        return append(kind, payload)
    monkeypatch.setattr(store, 'append', fail)
    with pytest.raises(OSError):
        asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    with pytest.raises(ValueError):
        coord.materialize('child-1', SOURCE, 'priority')


def test_failed_candidate_journal_write_blocks_subsequent_selection(tmp_path, monkeypatch):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    append = store.append
    def fail(kind, payload):
        if kind == 'funsearch_public_candidate':
            raise OSError('simulated candidate journal failure')
        return append(kind, payload)
    monkeypatch.setattr(store, 'append', fail)
    with pytest.raises(OSError):
        coord.record_evaluated('candidate-1')
    with pytest.raises(ValueError, match='candidate journal'):
        asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))


def test_crash_after_selection_journal_append_replays_same_event_once(tmp_path, monkeypatch):
    from core.x1.checkpoint import RunCheckpoint
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    p = policy(); coord = FunSearchCoordinator(p, store, **FROZEN)
    coord.record_evaluated('candidate-1')
    saved = p.checkpoint_state()
    checkpoint = RunCheckpoint.create({'git_state': {}, 'inflight_executor': [], 'messages': [], 'policy': saved})
    store.append('composed_checkpoint', {'sha256': checkpoint.payload_sha256})
    append = store.append
    def crash_after_write(kind, payload):
        append(kind, payload)
        if kind == 'funsearch_selection':
            raise OSError('simulated post-write crash')
    monkeypatch.setattr(store, 'append', crash_after_write)
    with pytest.raises(OSError):
        asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    restored_policy = policy(); restored_policy.restore_state(saved)
    restored_store = ContinuationStore(store.path, checkpoint); restored_store.resume()
    restored = FunSearchCoordinator(restored_policy, restored_store, **FROZEN)
    assert asyncio.run(restored.select('child-1', frontier('candidate-1'), {})) == ['candidate-1']
    assert len(list(restored_store.read('funsearch_selection'))) == 1
    assert 'priority_v0' in restored.materialize('child-1', SOURCE, 'priority')['prompt']


def test_failed_candidate_and_reset_are_journaled_before_future_selection(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    assert len(coord.reset_weaker_half()) == 1
    assert len(list(store.read('funsearch_reset'))) == 1
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    coord.abandon('child-1', 'evaluation_failed')
    assert len(list(store.read('funsearch_abandonment'))) == 1
    assert asyncio.run(coord.select('child-2', frontier('candidate-1'), {})) == ['candidate-1']


def test_failed_reset_journal_write_blocks_selection(tmp_path, monkeypatch):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    append = store.append
    def fail(kind, payload):
        if kind == 'funsearch_reset':
            raise OSError('simulated reset journal failure')
        return append(kind, payload)
    monkeypatch.setattr(store, 'append', fail)
    with pytest.raises(OSError):
        coord.reset_weaker_half()
    with pytest.raises(ValueError, match='reset'):
        asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))


def test_crash_after_reset_journal_append_replays_same_reset_once(tmp_path, monkeypatch):
    from core.x1.checkpoint import RunCheckpoint
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    p = policy(); coord = FunSearchCoordinator(p, store, **FROZEN)
    coord.record_evaluated('candidate-1')
    saved = p.checkpoint_state()
    checkpoint = RunCheckpoint.create({'git_state': {}, 'inflight_executor': [], 'messages': [], 'policy': saved})
    store.append('composed_checkpoint', {'sha256': checkpoint.payload_sha256})
    append = store.append
    def crash_after_write(kind, payload):
        append(kind, payload)
        if kind == 'funsearch_reset':
            raise OSError('simulated post-write crash')
    monkeypatch.setattr(store, 'append', crash_after_write)
    with pytest.raises(OSError):
        coord.reset_weaker_half()
    restored_policy = policy(); restored_policy.restore_state(saved)
    restored_store = ContinuationStore(store.path, checkpoint); restored_store.resume()
    restored = FunSearchCoordinator(restored_policy, restored_store, **FROZEN)
    assert len(restored.reset_weaker_half()) == 1
    assert len(list(restored_store.read('funsearch_reset'))) == 1
    assert asyncio.run(restored.select('child-1', frontier('candidate-1'), {})) == ['candidate-1']


def test_invalid_frozen_evaluator_identity_is_rejected_before_any_action(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    for key in ('metric', 'logical_run_id', 'evaluator_version', 'evaluation_context'):
        invalid = {**FROZEN, key: ''}
        with pytest.raises(ValueError):
            FunSearchCoordinator(policy(), store, **invalid)
    assert not list(store.read())


def test_materialization_journal_rejects_template_substitution_and_is_idempotent(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    first = coord.materialize('child-1', SOURCE, 'priority')
    second = coord.materialize('child-1', SOURCE, 'priority')
    assert first == second and len(list(store.read('funsearch_materialization'))) == 1
    with pytest.raises(ValueError, match='template'):
        coord.materialize('child-1', '# changed\n' + SOURCE, 'priority')
    assert len(list(store.read('funsearch_materialization'))) == 1


def test_materialization_write_failure_stops_before_returning_prompt(tmp_path, monkeypatch):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    append = store.append
    def fail(kind, payload):
        if kind == 'funsearch_materialization':
            raise OSError('simulated prompt journal failure')
        return append(kind, payload)
    monkeypatch.setattr(store, 'append', fail)
    with pytest.raises(OSError):
        coord.materialize('child-1', SOURCE, 'priority')
    assert not list(store.read('funsearch_materialization'))


def test_crash_after_materialization_journal_replays_same_prompt_once(tmp_path, monkeypatch):
    from core.x1.checkpoint import RunCheckpoint
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    p = policy(); coord = FunSearchCoordinator(p, store, **FROZEN)
    coord.record_evaluated('candidate-1')
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    saved = p.checkpoint_state()
    checkpoint = RunCheckpoint.create({'git_state': {}, 'inflight_executor': [], 'messages': [], 'policy': saved})
    store.append('composed_checkpoint', {'sha256': checkpoint.payload_sha256})
    append = store.append
    def crash_after_write(kind, payload):
        append(kind, payload)
        if kind == 'funsearch_materialization':
            raise OSError('simulated post-write crash')
    monkeypatch.setattr(store, 'append', crash_after_write)
    with pytest.raises(OSError):
        coord.materialize('child-1', SOURCE, 'priority')
    restored_policy = policy(); restored_policy.restore_state(saved)
    restored_store = ContinuationStore(store.path, checkpoint); restored_store.resume()
    restored = FunSearchCoordinator(restored_policy, restored_store, **FROZEN)
    result = restored.materialize('child-1', SOURCE, 'priority')
    assert 'priority_v0' in result['prompt']
    assert len(list(restored_store.read('funsearch_materialization'))) == 1


def test_evaluated_child_requires_durable_materialization_first(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    store.append('composed_evidence', original_row('child-1'))
    with pytest.raises(ValueError, match='materialization'):
        coord.record_evaluated('child-1')
    coord.materialize('child-1', SOURCE, 'priority')
    coord.record_evaluated('child-1')
    assert len(list(store.read('funsearch_public_candidate'))) == 2


def test_changed_template_is_rejected_before_first_materialization(tmp_path):
    store = ContinuationStore(tmp_path / 'journal.jsonl')
    store.append('composed_evidence', original_row())
    coord = FunSearchCoordinator(policy(), store, **FROZEN)
    coord.record_evaluated('candidate-1')
    asyncio.run(coord.select('child-1', frontier('candidate-1'), {}))
    with pytest.raises(ValueError, match='template'):
        coord.materialize('child-1', '# changed\n' + SOURCE, 'priority')
    assert not list(store.read('funsearch_materialization'))
