"""A failed construction is not an evaluated candidate."""
from dataclasses import asdict
from copy import deepcopy
import json

import pytest

from core.executor.types import CostVec
from core.x1.checkpoint import payload_digest


@pytest.fixture(autouse=True)
def fake_decoder(monkeypatch):
    class Decoder:
        max_attempts = 2
        def build_request(self, plan, *, hypothesis, attempt, feedback):
            return {'attempt': attempt, 'feedback': feedback}
        def decode_output(self, raw, plan):
            if raw == 'valid':
                return {'artifact': 'valid program'}
            raise ValueError('bad patch')
    from core.composition import openevolve_registration
    monkeypatch.setattr(openevolve_registration, 'constructor_factory', lambda *_: Decoder())


def failed_record():
    candidate = {'id': 'candidate', 'parents': ['parent'], 'hypothesis': 'initial',
                 'operator': 'openevolve', 'context_pack_ref': 'context', 'created_cycle': 3}
    plan = {'candidate': candidate, 'recipe': {'kind': 'reflective'}}
    ref = 'sha256:' + payload_digest(plan)
    identity = {'plan_ref': ref, 'materializer': {'kind': 'openevolve_diff_materializer_v1'},
                'operation': {'run_id': 'run', 'cycle': 3, 'lane': 'main', 'slot_id': None, 'phase': 'operator',
                              'intent_id': 'intent', 'fingerprint': 'fingerprint'}}
    cost = asdict(CostVec(tokens_in=14, node_count=1))
    terminal = {'identity': identity, 'outcome': {'kind': 'failed', 'failure_type': 'OperatorFailure',
                'detail': 'construction attempts exhausted: bad patch', 'cost': cost, 'measured_cost_units': ['token', 'node', 'eval_count']}}
    rows = [
        {'kind': 'hierarchical_budget', 'payload': {'event': 'reserve', 'data': {'fingerprint': 'fingerprint',
            'intent': {'intent_id': 'intent', 'candidate': {'id': 'candidate'}, 'operation': 'operator',
                       'lane': 'main', 'control_slot': None}}}},
        {'kind': 'hierarchical_budget', 'payload': {'event': 'start', 'data': {'intent_id': 'intent', 'fingerprint': 'fingerprint'}}},
        {'kind': 'openevolve_construction_plan', 'payload': {'candidate_id': 'candidate', 'plan': plan, 'plan_ref': ref}},
        {'kind': 'construction_started', 'payload': {'identity': identity}},
        {'kind': 'composed_provider_started', 'payload': {'binding': 'call', 'invocation': {'intent_id': 'intent', 'ordinal': 0, 'fingerprint': 'fingerprint', 'run_id': 'run', 'lane': 'main', 'slot_id': None}, 'request_sha256': payload_digest({'args': (json.dumps({'attempt': 1, 'feedback': []}, sort_keys=True, separators=(',', ':')),), 'kwargs': {}})}},
        {'kind': 'composed_provider_completed', 'payload': {'binding': 'call', 'tokens': 7, 'result': 'bad'}},
        {'kind': 'composed_provider_started', 'payload': {'binding': 'call2', 'invocation': {'intent_id': 'intent', 'ordinal': 1, 'fingerprint': 'fingerprint', 'run_id': 'run', 'lane': 'main', 'slot_id': None}, 'request_sha256': payload_digest({'args': (json.dumps({'attempt': 2, 'feedback': ['bad patch']}, sort_keys=True, separators=(',', ':')),), 'kwargs': {}})}},
        {'kind': 'composed_provider_completed', 'payload': {'binding': 'call2', 'tokens': 7, 'result': 'bad'}},
        {'kind': 'construction_outcome', 'payload': terminal},
        {'kind': 'hierarchical_budget', 'payload': {'event': 'settle', 'data': {'intent_id': 'intent',
            'fingerprint': 'fingerprint', 'actual_costs': {'token': 14, 'node': 1, 'eval_count': 0},
            'measured_units': ['token', 'node', 'eval_count', 'wallclock']}}},
    ]
    proposal = {'candidate': {**candidate, 'hypothesis': None}, 'artifact': '', 'cost': dict(cost),
                'measured_cost_units': ['token', 'node', 'eval_count']}
    evidence = {'candidate_id': 'candidate', 'executor_status': 'failed_to_run', 'result_text': 'construction attempts exhausted: bad patch',
                'eval_result': {'status': 'failed_to_run', 'metrics': {}, 'cost': asdict(CostVec()),
                                'text_feedback': 'construction attempts exhausted: bad patch', 'contract': {'binding': {'candidate_id': 'candidate'}}}}
    return rows, {'cycle': 3, 'proposal': proposal, 'evidence': evidence}


def test_known_construction_failure_uses_original_terminal_evidence():
    from zoo.mle_bench_lite.governed_currency import _verify_failed_construction_cycle
    rows, event = failed_record()
    _verify_failed_construction_cycle(rows, event, 'run')


@pytest.mark.parametrize('mutation', ['missing_start', 'wrong_plan', 'wrong_run', 'wrong_cost', 'wrong_detail',
                                      'success', 'wrong_candidate', 'duplicate_terminal', 'zero_cost_bool', 'failure_type', 'late_start', 'missing_intent', 'unsettled', 'wrong_usage', 'valid_patch', 'wrong_prompt', 'reused_completion', 'wrong_call_identity', 'retry_after_failure'])
def test_construction_failure_cannot_replace_missing_physical_evidence(mutation):
    from zoo.mle_bench_lite.governed_currency import _verify_failed_construction_cycle
    rows, event = deepcopy(failed_record())
    if mutation == 'missing_start': rows.pop(3)
    elif mutation == 'wrong_plan': rows[2]['payload']['plan']['candidate']['id'] = 'other'
    elif mutation == 'wrong_run': rows[8]['payload']['identity']['operation']['run_id'] = 'other'
    elif mutation == 'wrong_cost': event['proposal']['cost']['tokens_in'] += 1
    elif mutation == 'wrong_detail': event['evidence']['result_text'] = 'other'
    elif mutation == 'success': event['evidence']['eval_result']['status'] = 'ok'
    elif mutation == 'wrong_candidate': event['evidence']['candidate_id'] = 'other'
    elif mutation == 'zero_cost_bool': event['evidence']['eval_result']['cost']['tokens_in'] = False
    elif mutation == 'failure_type': rows[8]['payload']['outcome']['failure_type'] = 'OperatorBudgetExhausted'
    elif mutation == 'late_start': rows[3], rows[8] = rows[8], rows[3]
    elif mutation == 'missing_intent': rows[8]['payload']['identity']['operation'].pop('intent_id')
    elif mutation == 'unsettled': rows.pop()
    elif mutation == 'wrong_usage': rows[5]['payload']['tokens'] = 6
    elif mutation == 'wrong_call_identity': rows[4]['payload']['invocation']['fingerprint'] = 'other'
    elif mutation == 'retry_after_failure': rows[5]['payload'].update(outcome='failed', result='provider invocation failed (RuntimeError)')
    elif mutation == 'valid_patch': rows[5]['payload']['result'] = 'valid'
    elif mutation == 'wrong_prompt': rows[4]['payload']['request_sha256'] = 'bad'
    elif mutation == 'reused_completion': rows[6]['payload']['binding'] = 'call'
    else: rows.append(deepcopy(rows[8]))
    with pytest.raises(ValueError):
        _verify_failed_construction_cycle(rows, event, 'run')


def test_known_billed_provider_failure_remains_an_unscored_cycle():
    from zoo.mle_bench_lite.governed_currency import _verify_failed_construction_cycle
    rows, event = failed_record()
    rows[5]['payload'].update(outcome='failed', result='provider invocation failed (RuntimeError)')
    del rows[6:8]
    detail = 'RuntimeError: provider invocation failed (RuntimeError)'
    rows[6]['payload']['outcome']['detail'] = detail
    rows[6]['payload']['outcome']['cost']['tokens_in'] = 7
    rows[7]['payload']['data']['actual_costs']['token'] = 7
    event['proposal']['cost']['tokens_in'] = 7
    event['evidence']['result_text'] = detail
    event['evidence']['eval_result']['text_feedback'] = detail
    _verify_failed_construction_cycle(rows, event, 'run')
