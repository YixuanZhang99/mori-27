"""Policy lifecycle checks; no Framework or benchmark claim."""
import asyncio
from types import SimpleNamespace
import pytest
from core.memory.types import ScopeContext
from core.composition.funsearch_policy import FunSearchPolicy


def projection(name, score):
    return {'candidate_id': name, 'program_ref': 'sha256:' + name[0] * 64,
            'program_length': 20, 'scores': {'a': score, 'b': score},
            'evidence_ref': 'sha256:' + 'f' * 64}


def build():
    return FunSearchPolicy(ScopeContext('run', 'task', 'domain'), case_ids=['a', 'b'],
        islands=2, seed=4, prompt_size=2, temperature=1, temperature_period=10)


def frontier(*names):
    return SimpleNamespace(nodes={name: SimpleNamespace(id=name, status='done', eval_status='ok', score=1)
                                  for name in names})


def test_policy_selection_binds_island_and_recovers_pending_without_source():
    policy = build()
    assert asyncio.run(policy.select(frontier(), {})) == []
    policy.record_evaluated(projection('a', 0))
    parents = asyncio.run(policy.select(frontier('a'), {}))
    pending = policy.pending_selection()
    assert parents == ['a'] and pending['receipt']['samples'] == ['a']
    assert 'program' not in repr(pending['before']['candidates']['a']).replace('program_ref', '').replace('program_length', '')
    saved = policy.checkpoint_state()
    restored = build(); restored.restore_state(saved)
    assert restored.pending_selection() == pending
    assert restored.checkpoint_state() == saved
    restored.record_evaluated(projection('b', 1))
    assert restored.pending_selection() is None
    target = pending['receipt']['island']
    assert restored.population.inspect_island(target)['best'] == 'b'
    with pytest.raises(ValueError, match='already'):
        restored.record_evaluated(projection('b', 1))


def test_policy_blocks_overlapping_selection_and_rejects_tampered_pending():
    policy = build(); policy.record_evaluated(projection('a', 0))
    asyncio.run(policy.select(frontier('a'), {}))
    with pytest.raises(ValueError, match='pending'):
        asyncio.run(policy.select(frontier('a'), {}))
    with pytest.raises(ValueError, match='pending'):
        policy.reset_weaker_half()
    saved = policy.checkpoint_state()
    saved['pending']['receipt']['samples'][0] = 'tampered'
    with pytest.raises(ValueError):
        build().restore_state(saved)
    abandoned = policy.abandon_selection('evaluation_failed')
    assert abandoned['receipt']['samples'] == ['a'] and policy.pending_selection() is None
    assert asyncio.run(policy.select(frontier('a'), {})) == ['a']


def test_restored_policy_audits_all_records_against_original_evidence():
    import hashlib
    from dataclasses import replace
    from core.composition.evaluation import encode_evidence
    from core.funsearch_public_evidence import project_program_candidate
    from test_funsearch_public_evidence import evidence
    source = 'def priority(x):\n    return x\n'
    original = evidence()
    binding = replace(original.eval_result.contract.binding, artifact_sha256=hashlib.sha256(source.encode()).hexdigest())
    original = replace(original, eval_result=replace(original.eval_result,
        contract=replace(original.eval_result.contract, binding=binding)))
    projected = project_program_candidate(original, source, case_ids=['a', 'b'], metric='score', logical_run_id='run')
    policy = build(); policy.record_evaluated(projected)
    row = {'cycle': 0, 'proposal': {'candidate': {'id': 'candidate-1'}, 'artifact': source},
           'evidence_ref': projected['evidence_ref'], 'evidence': encode_evidence(original)['evidence']}
    args = dict(metric='score', logical_run_id='run', evaluator_version='eval-v1', evaluation_context='sha256:' + 'c' * 64)
    assert policy.audit_original_evidence([row], **args)
    tampered = policy.checkpoint_state(); tampered['evidence_refs']['candidate-1'] = 'sha256:' + '0' * 64
    restored = build(); restored.restore_state(tampered)
    with pytest.raises(ValueError):
        restored.audit_original_evidence([row], **args)
