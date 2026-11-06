"""Read-only cross-record validation of resident control outcomes.

A terminal row is an index into measured execution evidence, not an independent
claim of success. This validator also accepts an unfinished journal prefix: only
fully linked terminal rows become results, while starts remain visible to audit.
"""
from __future__ import annotations

import math
from dataclasses import asdict, fields

from core.composition.contracts import Proposal, json_copy
from core.composition.evaluation import binding_for, decode_evidence, validate_evidence
from core.executor.types import Candidate, CostVec, EvalRequest, EvalStatus
from core.x1.checkpoint import payload_digest

_START = {'slot_id', 'plan_ref', 'candidate_id', 'main_cycles'}
_TERMINAL = _START | {'status', 'proposal', 'evidence', 'failure_type'}
_OPERATOR = {'intent_id', 'fingerprint', 'proposal', 'failure_type'}
_EVALUATION_FAILURE = {'intent_id', 'fingerprint', 'cost', 'measured_cost_units', 'reason'}
_OPERATOR_FAILURES = {'OperatorFailure', 'OperatorBudgetExhausted'}
_EVALUATION_FAILURES = {'MeasuredCommandError', 'MeasuredEvaluationError'}


def _require(condition, message):
    if not condition:
        raise ValueError('governed control audit: ' + message)


def _shape(value, names, label):
    _require(type(value) is dict and set(value) == names, 'invalid ' + label + ' fields')


def _proposal(value, candidate_id):
    _shape(value, {field.name for field in fields(Proposal)}, 'proposal')
    _shape(value['candidate'], {field.name for field in fields(Candidate)}, 'proposal candidate')
    candidate = Candidate(**value['candidate'])
    candidate.validate()
    _require(candidate.id == candidate_id and candidate.parents == []
             and type(candidate.created_cycle) is int and candidate.created_cycle == 0,
             'proposal changed control identity, lineage or cycle')
    _require(type(value['artifact']) is str, 'proposal artifact must be text')
    _cost(value['cost'])
    return Proposal(candidate, value['artifact'])


def _cost(value):
    _shape(value, {field.name for field in fields(CostVec)}, 'settlement cost')
    for name, number in value.items():
        _require(type(number) in (int, float) and math.isfinite(number) and number >= 0,
                 'nonfinite or negative settlement cost')
        if name in {'tokens_in', 'tokens_out', 'node_count', 'eval_count'}:
            _require(type(number) is int, 'noninteger settlement count')
    return {'token': value['tokens_in'] + value['tokens_out'], 'node': value['node_count'],
            'eval_count': value['eval_count'], 'wallclock': value['wall_seconds'],
            'gpu_hours': value['gpu_hours'], 'usd': value['usd']}


def audit_terminals(runtime, plan, sessions):
    """Validate live control residence against the physical authority and inputs."""
    budget = runtime.budget.audit_governance()
    _require(budget['plan_ref'] == plan['plan_ref'], 'plan differs from physical protection')
    slots = {slot['slot_id']: slot for slot in plan['slots']}
    _require(len(slots) == len(plan['slots']), 'duplicate planned slots')
    identifiers = {slot_id: payload_digest({'run_id': runtime._logical_run_id,
        'plan_ref': plan['plan_ref'], 'slot_id': slot_id}) for slot_id in slots}
    rows = list(runtime.store.read())
    reserves, settles, outcomes, physical, failures, measurements = {}, {}, {}, {}, {}, {}
    starts, terminals, completions = {}, {}, {}
    committed, stopped = 0, None
    started_order = []

    def put(target, key, index, data, label):
        _require(type(key) is str and key not in target, 'duplicate or missing ' + label + ' identity')
        target[key] = (index, data)

    for index, row in enumerate(rows):
        kind, data = row['kind'], row['payload']
        if kind == 'hierarchical_budget':
            event, payload = data['event'], data['data']
            if event == 'reserve':
                put(reserves, payload['intent']['intent_id'], index, payload, 'physical reservation')
            elif event == 'settle':
                put(settles, payload['intent_id'], index, payload, 'physical settlement')
        elif kind == 'composed_checkpoint':
            count = data.get('next_cycle')
            _require(type(count) is int and committed <= count <= committed + 1,
                     'checkpoint main cycle schedule is inconsistent')
            if count != committed:
                stopped = None
            committed = count
        elif kind == 'governed_main_stopped':
            _shape(data, {'main_cycles', 'disposition'}, 'main stop')
            _require(type(data['main_cycles']) is int and data['main_cycles'] == committed
                     and data['disposition'] in {'ordinary', 'integrity'}, 'invalid main stop schedule')
            stopped = data
        elif kind == 'governed_control_started':
            _shape(data, _START, 'control start')
            slot_id = data['slot_id']
            _require(type(slot_id) is str and slot_id in slots, 'unknown control start slot')
            _require(data['plan_ref'] == plan['plan_ref'] and data['candidate_id'] == identifiers[slot_id],
                     'control start changed frozen identity')
            _require(type(data['main_cycles']) is int and data['main_cycles'] == committed,
                     'control start main cycle schedule differs from committed cycles')
            planned = slots[slot_id]['after_main_cycles']
            _require(stopped is None or stopped['disposition'] == 'ordinary',
                     'control start follows an integrity stop')
            _require(data['main_cycles'] == planned or (data['main_cycles'] < planned and
                     stopped is not None and stopped['disposition'] == 'ordinary'),
                     'control start differs from frozen schedule without ordinary drain')
            _require(len(started_order) < len(slots) and slot_id == list(slots)[len(started_order)],
                     'control starts are duplicated or out of planned order')
            _require(not started_order or started_order[-1] in terminals,
                     'new control started before the preceding draw became terminal')
            started_order.append(slot_id)
            put(starts, slot_id, index, data, 'control start')
        elif kind == 'governed_operator_outcome':
            _shape(data, _OPERATOR, 'operator outcome')
            put(outcomes, data['intent_id'], index, data, 'operator outcome')
        elif kind == 'governed_evaluation_completed' and runtime.budget._require_initial_control:
            put(completions, data.get('identity', {}).get('intent_id'), index, data, 'control evaluation completion')
        elif kind == 'composed_physical_evidence':
            _shape(data, {'intent_id', 'request', 'evidence'}, 'physical evidence')
            put(physical, data['intent_id'], index, data, 'physical evidence')
        elif kind == 'governed_evaluation_failure':
            _shape(data, _EVALUATION_FAILURE, 'evaluation failure')
            _require(data['reason'] in _EVALUATION_FAILURES, 'unrecognized measured evaluation failure')
            put(failures, data['intent_id'], index, data, 'evaluation failure')
        elif kind == 'composed_operation_measurement':
            _shape(data, {'identity', 'elapsed'}, 'operation measurement')
            identity = data['identity']
            _shape(identity, {'intent_id', 'fingerprint', 'cost', 'coverage', 'evaluation', 'operator'},
                   'operation measurement identity')
            put(measurements, identity['intent_id'], index, data, 'operation measurement')
        elif kind == 'governed_control_terminal':
            _shape(data, _TERMINAL, 'control terminal')
            slot_id = data['slot_id']
            _require(type(slot_id) is str and slot_id in starts, 'terminal lacks original control start')
            _require(all(data[key] == starts[slot_id][1][key] for key in _START),
                     'terminal differs from original control start')
            _require(data['status'] in {'evaluated', 'failed'}, 'invalid terminal status')
            put(terminals, slot_id, index, data, 'control terminal')

    def reservation(slot_id, phase):
        intent_id = f'control:{slot_id}:{phase}'
        _require(intent_id in reserves, 'control phase lacks physical reservation')
        index, record = reserves[intent_id]
        intent = record['intent']
        _require(intent['lane'] == 'control' and intent['control_slot'] == slot_id
                 and intent['account'] == 'control' and intent['direction_id'] == f'control:{slot_id}'
                 and intent['operation'] == ('operator' if phase == 'operator' else 'dev'),
                 'physical reservation differs from control phase authority')
        candidate = intent['candidate']
        _require(candidate['id'] == identifiers[slot_id] and candidate['parents'] == []
                 and type(candidate['created_cycle']) is int and candidate['created_cycle'] == 0,
                 'physical reservation changed control candidate')
        expected_request = None if phase == 'operator' else asdict(EvalRequest(**slots[slot_id]['request']))
        _require(intent['request'] == expected_request, 'physical reservation changed frozen request')
        return intent_id, index, record

    def settlement(intent_id, reservation_record, cost, coverage, *, evaluation, before_terminal):
        _require(intent_id in settles and intent_id in measurements, 'terminal lacks physical settlement evidence')
        settle_index, settled = settles[intent_id]
        measure_index, measure = measurements[intent_id]
        _require(measure_index < settle_index < before_terminal, 'settlement precedes no valid terminal measurement')
        identity = measure['identity']
        _require(identity == {'intent_id': intent_id, 'fingerprint': reservation_record['fingerprint'],
            'cost': cost, 'coverage': coverage, 'evaluation': evaluation, 'operator': not evaluation},
            'settlement measurement differs from terminal cost or phase')
        _require(settled['fingerprint'] == reservation_record['fingerprint'], 'settlement receipt changed')
        elapsed = measure['elapsed']
        _require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
                 'invalid settlement elapsed time')
        amounts = _cost(cost)
        _require(type(coverage) is list and len(set(coverage)) == len(coverage), 'invalid settlement coverage')
        amounts['node'] = 0 if evaluation else 1
        if evaluation:
            amounts['eval_count'] = max(1, amounts['eval_count'])
        if 'wallclock' not in coverage:
            amounts['wallclock'] = elapsed
        elif evaluation:
            slot = reservation_record['intent']['control_slot']
            construction = sessions[slot].get('construction_execution')
            supervised = getattr(runtime, 'durable_executor', False) or (
                construction is not None and construction.owner.command_executor is not None)
            if supervised:
                amounts['wallclock'] = max(amounts['wallclock'], elapsed)
        _require(settled['actual_costs'] == {unit: amounts[unit] for unit in runtime.budget.units},
                 'physical settlement differs from actual terminal costs')
        return settle_index

    # Authority rows outside a terminal still need a valid control reservation;
    # otherwise an appended forged outcome could remain hidden as pending work.
    for records in (outcomes, physical, failures, measurements):
        for intent_id, (index, data) in records.items():
            _require(intent_id in reserves, 'execution evidence has no physical reservation')
            intent = reserves[intent_id][1]['intent']
            if intent['lane'] == 'control':
                slot_id = intent['control_slot']
                _require(slot_id in starts and starts[slot_id][0] < index,
                         'control execution evidence has no preceding start')
                reservation(slot_id, 'operator' if intent['operation'] == 'operator' else 'evaluation')

    results = {}
    for slot_id, (terminal_index, terminal) in terminals.items():
        operator_id, reserve_index, operator_reserve = reservation(slot_id, 'operator')
        _require(operator_id in outcomes, 'terminal lacks authoritative operator outcome')
        outcome_index, outcome = outcomes[operator_id]
        _require(reserve_index < starts[slot_id][0] < outcome_index < terminal_index,
                 'operator outcome order differs from control start')
        _require(outcome['fingerprint'] == operator_reserve['fingerprint']
                 and outcome['proposal'] == terminal['proposal'], 'terminal proposal differs from original operator outcome')
        proposal = _proposal(terminal['proposal'], identifiers[slot_id])
        op_failure = outcome['failure_type']
        _require(op_failure is None or op_failure in _OPERATOR_FAILURES, 'unknown operator failure authority')
        op_settled = settlement(operator_id, operator_reserve, terminal['proposal']['cost'],
            terminal['proposal']['measured_cost_units'], evaluation=False, before_terminal=terminal_index)
        _require(outcome_index < op_settled, 'operator settlement predates its terminal outcome')
        evaluation_id = f'control:{slot_id}:evaluation'
        failure_type = terminal['failure_type']
        if op_failure is not None:
            _require(terminal['evidence'] is None and evaluation_id not in reserves
                     and terminal['status'] == 'failed' and failure_type == op_failure,
                     'failed operator terminal contradicts evaluation or failure authority')
        else:
            _, evaluation_reserve_index, evaluation_reserve = reservation(slot_id, 'evaluation')
            _require(op_settled < evaluation_reserve_index < terminal_index,
                     'evaluation reservation precedes settled control proposal')
            if terminal['evidence'] is None:
                _require(evaluation_id in failures and evaluation_id not in physical
                         and failure_type in _EVALUATION_FAILURES and terminal['status'] == 'failed',
                         'missing evidence has no authoritative measured evaluation failure')
                failure_index, failure = failures[evaluation_id]
                _require(failure['reason'] == failure_type and failure['fingerprint'] == evaluation_reserve['fingerprint']
                         and evaluation_reserve_index < failure_index < terminal_index,
                         'measured evaluation failure differs from reservation')
                settlement(evaluation_id, evaluation_reserve, failure['cost'], failure['measured_cost_units'],
                           evaluation=True, before_terminal=terminal_index)
            else:
                _require(evaluation_id in physical and evaluation_id not in failures and failure_type is None,
                         'terminal evidence lacks a unique authoritative evaluation outcome')
                physical_index, actual = physical[evaluation_id]
                request = EvalRequest(**slots[slot_id]['request'])
                _require(actual['request'] == asdict(request) and actual['evidence'] == terminal['evidence'],
                         'terminal evidence differs from original frozen physical evidence')
                domain = sessions[slot_id]['domain']
                context_for = getattr(domain, 'evaluation_context_for', None)
                expected = binding_for(proposal, request, evaluator_version=domain.evaluator_version,
                    evaluation_context=context_for(request) if callable(context_for) else domain.evaluation_context)
                evidence = decode_evidence(terminal['evidence'])
                validate_evidence(evidence, expected_binding=expected)
                derived = 'evaluated' if evidence.eval_result.status is EvalStatus.OK else 'failed'
                _require(terminal['status'] == derived, 'terminal status contradicts actual evaluation evidence')
                if runtime.budget._require_initial_control:
                    _require(evaluation_id in completions, 'control terminal lacks sealed original completion')
                    completion_index, completion = completions[evaluation_id]
                    _require(completion_index < settles[evaluation_id][0] and
                             settles[evaluation_id][1].get('measurement_evidence_ref') ==
                             'sha256:' + payload_digest(completion) and completion.get('evidence') == terminal['evidence'] and
                             completion.get('elapsed') == measurements[evaluation_id][1].get('elapsed'),
                             'control completion differs from sealed physical settlement')
                eval_settled = settlement(evaluation_id, evaluation_reserve, asdict(evidence.eval_result.cost),
                    list(evidence.eval_result.contract.measured_cost_units), evaluation=True,
                    before_terminal=terminal_index)
                _require(eval_settled < physical_index < terminal_index,
                         'physical evidence order differs from evaluation settlement')
        _require(budget['slots'][slot_id]['status'] == terminal['status'],
                 'terminal status differs from physical slot settlement or cancellation')
        results[slot_id] = json_copy(terminal)
    return results
