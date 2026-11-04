from dataclasses import replace
import pytest
from core.executor.types import EvidenceRecord, EvalResult, EvalStatus, CostVec
from core.executor.evaluation_contract import EvaluationBinding, EvaluationContract, ItemOutcome, PrivateEvaluationData
from core.funsearch_public_evidence import project_program_scores
from core.composition.evaluation import encode_evidence
from core.x1.checkpoint import payload_digest


def evidence():
    binding = EvaluationBinding('candidate-1', 'a' * 64, 'sha256:' + 'b' * 64, 'eval-v1', 'sha256:' + 'c' * 64, 'dev', 'dev')
    items = (ItemOutcome('a', metrics={'score': .1}, visibility='public'),
             ItemOutcome('b', metrics={'score': .7}, visibility='public'),
             ItemOutcome('secret', metrics={'score': .9}, visibility='private'))
    contract = EvaluationContract(binding, ('token', 'eval_count'),
        private=PrivateEvaluationData(data={'secret': 'PRIVATE_SENTINEL'}), items=items)
    result = EvalResult(EvalStatus.OK, {'dev/score': .7}, CostVec(eval_count=1),
                        text_feedback='PRIVATE_RAW_FEEDBACK', contract=contract)
    return EvidenceRecord('candidate-1', result)


def test_only_declared_public_metrics_cross_projection():
    projected = project_program_scores(evidence(), case_ids=['a', 'b'], metric='score', logical_run_id='run')
    assert projected['candidate_id'] == 'candidate-1'
    assert projected['scores'] == {'a': .1, 'b': .7}
    assert projected['evidence_ref'] == 'sha256:' + payload_digest({'logical_run_id': 'run', 'evidence': encode_evidence(evidence())})
    assert 'PRIVATE_' not in repr(projected) and 'secret' not in repr(projected)


def test_rejects_missing_private_extra_seeded_and_non_development_scores():
    original = evidence()
    result, contract = original.eval_result, original.eval_result.contract
    cases = [
        replace(contract, items=(contract.items[0],)),
        replace(contract, items=(contract.items[0], replace(contract.items[1], visibility='private'))),
        replace(contract, items=contract.items + (ItemOutcome('extra', metrics={'score': 0}, visibility='public'),)),
        replace(contract, items=(contract.items[0], replace(contract.items[1], seed=4))),
        replace(contract, binding=replace(contract.binding, split_id='test')),
    ]
    for altered in cases:
        with pytest.raises(ValueError):
            project_program_scores(replace(original, eval_result=replace(result, contract=altered)),
                                   case_ids=['a', 'b'], metric='score', logical_run_id='run')
    with pytest.raises(ValueError):
        project_program_scores(original, case_ids=['a', 'b'], metric='missing', logical_run_id='run')


def test_evidence_reference_binds_full_original_without_revealing_private_data():
    original = evidence()
    first = project_program_scores(original, case_ids=['a', 'b'], metric='score', logical_run_id='run')
    altered_contract = replace(original.eval_result.contract,
        private=PrivateEvaluationData(data={'secret': 'DIFFERENT_PRIVATE'}))
    altered = replace(original, eval_result=replace(original.eval_result, contract=altered_contract))
    second = project_program_scores(altered, case_ids=['a', 'b'], metric='score', logical_run_id='run')
    assert first['scores'] == second['scores']
    assert first['evidence_ref'] != second['evidence_ref']
    assert 'PRIVATE' not in repr(first) + repr(second)
    with pytest.raises(ValueError):
        project_program_scores(replace(original, candidate_id='different'),
                               case_ids=['a', 'b'], metric='score', logical_run_id='run')


def test_candidate_program_identity_is_bound_without_exposing_source():
    import hashlib
    from core.funsearch_public_evidence import project_program_candidate
    original = evidence()
    source = 'def fn():\n    return "PRIVATE_SOURCE_SENTINEL"\n'
    binding = replace(original.eval_result.contract.binding, artifact_sha256=hashlib.sha256(source.encode()).hexdigest())
    contract = replace(original.eval_result.contract, binding=binding)
    bound = replace(original, eval_result=replace(original.eval_result, contract=contract))
    projection = project_program_candidate(bound, source, case_ids=['a', 'b'], metric='score', logical_run_id='run')
    assert projection['program_ref'] == 'sha256:' + binding.artifact_sha256
    assert projection['program_length'] == len(source)
    assert 'PRIVATE_SOURCE_SENTINEL' not in repr(projection)
    with pytest.raises(ValueError, match='artifact'):
        project_program_candidate(bound, source + 'x', case_ids=['a', 'b'], metric='score', logical_run_id='run')
