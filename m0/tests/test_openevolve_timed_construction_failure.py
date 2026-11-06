"""A failed construction is not an evaluated candidate."""
from dataclasses import asdict
from copy import deepcopy

import pytest

from core.executor.types import CostVec
from core.x1.checkpoint import payload_digest


def failed_record():
    candidate = {'id': 'candidate', 'parents': ['parent'], 'hypothesis': 'initial',
                 'operator': 'openevolve', 'context_pack_ref': 'context', 'created_cycle': 3}
    plan = {'candidate': candidate, 'recipe': {'kind': 'reflective'}}
    ref = 'sha256:' + payload_digest(plan)
    identity = {'plan_ref': ref, 'materializer': {'kind': 'openevolve_diff_materializer_v1'},
                'operation': {'run_id': 'run', 'cycle': 3, 'lane': 'main', 'slot_id': None, 'phase': 'operator'}}
    cost = asdict(CostVec(tokens_in=14, node_count=1))
    terminal = {'identity': identity, 'outcome': {'kind': 'failed', 'failure_type': 'OperatorFailure',
                'detail': 'patch failed', 'cost': cost, 'measured_cost_units': ['token', 'node', 'eval_count']}}
    rows = [{'kind': 'openevolve_construction_plan', 'payload': {'candidate_id': 'candidate', 'plan': plan, 'plan_ref': ref}},
            {'kind': 'construction_started', 'payload': {'identity': identity}},
            {'kind': 'construction_outcome', 'payload': terminal}]
    proposal = {'candidate': {**candidate, 'hypothesis': None}, 'artifact': '', 'cost': dict(cost),
                'measured_cost_units': ['token', 'node', 'eval_count']}
    evidence = {'candidate_id': 'candidate', 'executor_status': 'failed_to_run', 'result_text': 'patch failed',
                'eval_result': {'status': 'failed_to_run', 'metrics': {}, 'cost': asdict(CostVec()),
                                'text_feedback': 'patch failed', 'contract': {'binding': {'candidate_id': 'candidate'}}}}
    return rows, {'cycle': 3, 'proposal': proposal, 'evidence': evidence}


def test_known_construction_failure_uses_original_terminal_evidence():
    from zoo.mle_bench_lite.governed_currency import _verify_failed_construction_cycle
    rows, event = failed_record()
    _verify_failed_construction_cycle(rows, event, 'run')


@pytest.mark.parametrize('mutation', ['missing_start', 'wrong_plan', 'wrong_run', 'wrong_cost', 'wrong_detail',
                                      'success', 'wrong_candidate', 'duplicate_terminal', 'zero_cost_bool', 'failure_type', 'late_start'])
def test_construction_failure_cannot_replace_missing_physical_evidence(mutation):
    from zoo.mle_bench_lite.governed_currency import _verify_failed_construction_cycle
    rows, event = deepcopy(failed_record())
    if mutation == 'missing_start': rows.pop(1)
    elif mutation == 'wrong_plan': rows[0]['payload']['plan']['candidate']['id'] = 'other'
    elif mutation == 'wrong_run': rows[-1]['payload']['identity']['operation']['run_id'] = 'other'
    elif mutation == 'wrong_cost': event['proposal']['cost']['tokens_in'] += 1
    elif mutation == 'wrong_detail': event['evidence']['result_text'] = 'other'
    elif mutation == 'success': event['evidence']['eval_result']['status'] = 'ok'
    elif mutation == 'wrong_candidate': event['evidence']['candidate_id'] = 'other'
    elif mutation == 'zero_cost_bool': event['evidence']['eval_result']['cost']['tokens_in'] = False
    elif mutation == 'failure_type': rows[-1]['payload']['outcome']['failure_type'] = 'OperatorBudgetExhausted'
    elif mutation == 'late_start': rows[1], rows[2] = rows[2], rows[1]
    else: rows.append(deepcopy(rows[-1]))
    with pytest.raises(ValueError):
        _verify_failed_construction_cycle(rows, event, 'run')
