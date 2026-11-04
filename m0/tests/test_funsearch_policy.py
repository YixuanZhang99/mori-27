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


def audited_seed(policy, name='a', score=0):
    import hashlib
    from dataclasses import replace
    from core.composition.evaluation import encode_evidence
    from core.funsearch_public_evidence import project_program_candidate
    from core.executor.evaluation_contract import ItemOutcome
    from test_funsearch_public_evidence import evidence
    source = f'def priority(x):\n    return x + {score}\n'
    original = evidence()
    binding = replace(original.eval_result.contract.binding, candidate_id=name,
                      artifact_sha256=hashlib.sha256(source.encode()).hexdigest())
    items = tuple(ItemOutcome(case, metrics={'score': score}, visibility='public') for case in ('a', 'b'))
    contract = replace(original.eval_result.contract, binding=binding, items=items)
    original = replace(original, candidate_id=name, eval_result=replace(original.eval_result, contract=contract))
    projected = project_program_candidate(original, source, case_ids=['a', 'b'], metric='score', logical_run_id='run')
    policy.record_evaluated(projected)
    row = {'cycle': 0, 'proposal': {'candidate': {'id': name}, 'artifact': source},
           'evidence_ref': projected['evidence_ref'], 'evidence': encode_evidence(original)['evidence']}
    args = dict(metric='score', logical_run_id='run', evaluator_version='eval-v1',
                evaluation_context='sha256:' + 'c' * 64)
    policy.audit_original_evidence([row], **args)
    return row, args


def frontier(*names):
    return SimpleNamespace(nodes={name: SimpleNamespace(id=name, status='done', eval_status='ok', score=1)
                                  for name in names})


def test_policy_selection_binds_island_and_recovers_pending_without_source():
    policy = build()
    assert asyncio.run(policy.select(frontier(), {})) == []
    row, audit_args = audited_seed(policy)
    parents = asyncio.run(policy.select(frontier('a'), {}))
    pending = policy.pending_selection()
    assert parents == ['a'] and pending['receipt']['samples'] == ['a']
    assert 'program' not in repr(pending['before']['candidates']['a']).replace('program_ref', '').replace('program_length', '')
    saved = policy.checkpoint_state()
    restored = build(); restored.restore_state(saved)
    assert restored.pending_selection() == pending
    assert restored.checkpoint_state() == saved
    with pytest.raises(ValueError, match='journal'):
        restored.audit_original_evidence([row], **audit_args)
    restored.audit_original_evidence([row], selection_rows=[pending], **audit_args)
    restored.record_evaluated(projection('b', 1))
    assert restored.pending_selection() is None
    target = pending['receipt']['island']
    assert restored.population.inspect_island(target)['best'] == 'b'
    with pytest.raises(ValueError, match='already'):
        restored.record_evaluated(projection('b', 1))


def test_policy_blocks_overlapping_selection_and_rejects_tampered_pending():
    policy = build(); row, args = audited_seed(policy)
    asyncio.run(policy.select(frontier('a'), {}))
    with pytest.raises(ValueError, match='pending'):
        asyncio.run(policy.select(frontier('a'), {}))
    with pytest.raises(ValueError, match='pending'):
        policy.reset_weaker_half()
    saved = policy.checkpoint_state()
    saved['pending']['receipt']['samples'][0] = 'tampered'
    with pytest.raises(ValueError):
        build().restore_state(saved)
    selection = policy.pending_selection()
    policy.audit_original_evidence([row], selection_rows=[selection], **args)
    abandoned = policy.abandon_selection('evaluation_failed')
    assert abandoned['reason'] == 'evaluation_failed' and policy.pending_selection() == selection
    policy.audit_original_evidence([row], selection_rows=[selection], abandonment_rows=[abandoned], **args)
    assert policy.pending_selection() is None
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


def test_selection_is_blocked_until_original_evidence_is_audited():
    policy = build(); policy.record_evaluated(projection('a', 0))
    with pytest.raises(ValueError, match='audit'):
        asyncio.run(policy.select(frontier('a'), {}))


def test_pending_selection_must_be_audited_against_journal_before_settlement():
    policy = build(); row, args = audited_seed(policy)
    asyncio.run(policy.select(frontier('a'), {}))
    pending = policy.pending_selection()
    with pytest.raises(ValueError, match='audit'):
        policy.record_evaluated(projection('b', 1))
    with pytest.raises(ValueError, match='journal'):
        policy.audit_original_evidence([row], **args)
    policy.audit_original_evidence([row], selection_rows=[pending], **args)
    policy.record_evaluated(projection('b', 1))


def test_island_reset_requires_replay_and_original_journal_before_further_selection():
    policy = build(); row, args = audited_seed(policy)
    events = policy.reset_weaker_half()
    pending = policy.pending_reset()
    assert pending['events'] == events
    with pytest.raises(ValueError, match='reset'):
        asyncio.run(policy.select(frontier('a'), {}))
    restored = build(); restored.restore_state(policy.checkpoint_state())
    with pytest.raises(ValueError, match='reset'):
        restored.audit_original_evidence([row], **args)
    restored.audit_original_evidence([row], reset_rows=[pending], **args)
    assert restored.pending_reset() is None
    assert asyncio.run(restored.select(frontier('a'), {})) == ['a']
    corrupted = policy.checkpoint_state()
    corrupted['pending_reset']['events'][0]['founder'] = 'tampered'
    with pytest.raises(ValueError):
        build().restore_state(corrupted)


def test_failed_selection_disposition_must_survive_recovery_before_retry():
    policy = build(); row, args = audited_seed(policy)
    asyncio.run(policy.select(frontier('a'), {}))
    selection = policy.pending_selection()
    policy.audit_original_evidence([row], selection_rows=[selection], **args)
    failure = policy.abandon_selection('evaluation_failed')
    assert policy.pending_selection() == selection
    restored = build(); restored.restore_state(policy.checkpoint_state())
    with pytest.raises(ValueError, match='abandon'):
        restored.audit_original_evidence([row], selection_rows=[selection], **args)
    restored.audit_original_evidence([row], selection_rows=[selection], abandonment_rows=[failure], **args)
    assert restored.pending_selection() is None
    assert asyncio.run(restored.select(frontier('a'), {})) == ['a']


def test_funsearch_profile_options_freeze_template_metric_and_reset_policy():
    import hashlib
    from core.composition.funsearch_policy import funsearch_policy_options
    template = 'def priority(x):\n    return x\n'
    options = {'case_ids': ['a', 'b'], 'islands': 2, 'seed': 4, 'prompt_size': 2,
               'temperature': 1.0, 'temperature_period': 10, 'metric': 'score',
               'template': template, 'template_ref': 'sha256:' + hashlib.sha256(template.encode()).hexdigest(),
               'function_name': 'priority', 'reset_interval': 4}
    funsearch_policy_options(options)
    for field, value in [('template_ref', 'sha256:' + '0' * 64), ('metric', ''),
                         ('function_name', 'missing'), ('reset_interval', 0), ('prompt_size', 3)]:
        invalid = {**options, field: value}
        with pytest.raises(ValueError): funsearch_policy_options(invalid)
    with pytest.raises(ValueError): funsearch_policy_options({**options, 'unexpected': True})
