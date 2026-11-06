"""Recalculate best tracking from caller-supplied admissions and evaluations.

This primitive does not authenticate its inputs, prove that all admissions were
captured, or certify the reference run. Callers must establish those separately.
"""
import math
import re

from core.openevolve_interop import ProgramDatabase  # Load the pinned vendor path.
from core.x1.checkpoint import payload_digest
from openevolve.utils.metrics_utils import get_fitness_score


def _valid_measurement(value):
    return (type(value) is dict and set(value) == {'program_ref', 'metrics'} and
            type(value['program_ref']) is str and
            re.fullmatch(r'sha256:[0-9a-f]{64}', value['program_ref']) is not None and
            type(value['metrics']) is dict and bool(value['metrics']) and
            all(type(key) is str and bool(key) and type(number) in (int, float) and
                math.isfinite(number) for key, number in value['metrics'].items()))


def audit_reference_best(events, *, evaluated, selected_id):
    """Verify best updates for a caller-pinned complete set of admissions."""
    if (type(events) is not list or not 1 <= len(events) <= 1000 or
            type(evaluated) is not dict or not evaluated or
            any(type(key) is not str or not key or not _valid_measurement(value)
                for key, value in evaluated.items()) or
            type(selected_id) is not str or not selected_id):
        raise ValueError('invalid caller-supplied reference admissions')
    by_id, kinds, observed, best, best_fitness = {}, {}, set(), None, None
    keys = {'kind', 'id', 'parent_id', 'program_ref', 'metrics', 'best_before', 'best_after'}
    v2_keys = keys | {'iteration', 'target_island'}
    schema = set(events[0]) if type(events[0]) is dict else set()
    if schema not in (keys, v2_keys):
        raise ValueError('invalid reference admission schema')
    for index, event in enumerate(events):
        if (type(event) is not dict or set(event) != schema or
                event['kind'] not in {'seed', 'candidate', 'migrant'} or
                type(event['id']) is not str or not event['id'] or event['id'] in by_id or
                event['best_before'] != best):
            raise ValueError('invalid reference admission or best transition')
        if schema == v2_keys and (
                (event['iteration'] is not None and
                 (type(event['iteration']) is not int or event['iteration'] < 0)) or
                (event['target_island'] is not None and
                 (type(event['target_island']) is not int or not 0 <= event['target_island'] < 4))):
            raise ValueError('invalid reference admission iteration or island')
        if schema == v2_keys and (
                (event['kind'] in ('seed', 'migrant') and event['iteration'] is not None) or
                (event['kind'] == 'migrant' and event['target_island'] is None) or
                (event['kind'] == 'candidate' and
                 (event['iteration'] is None or event['iteration'] < 1 or event['target_island'] is None))):
            raise ValueError('reference admission does not match its host operation')
        ident, kind = event['id'], event['kind']
        measurement = {'program_ref': event['program_ref'], 'metrics': event['metrics']}
        if not _valid_measurement(measurement):
            raise ValueError('invalid reference admission measurement')
        if kind == 'seed':
            if index != 0 or event['parent_id'] is not None:
                raise ValueError('reference seed must be the first admission')
        elif index == 0:
            raise ValueError('reference admissions must begin with a seed')
        if kind == 'migrant':
            parent = event['parent_id']
            if type(parent) is not str or parent not in by_id or kinds[parent] == 'migrant' or \
                    payload_digest(measurement) != payload_digest(by_id[parent]):
                raise ValueError('reference migrant does not match its source')
        else:
            if ident not in evaluated or payload_digest(measurement) != payload_digest(evaluated[ident]):
                raise ValueError('reference admission differs from its evaluation')
            observed.add(ident)
        fitness = get_fitness_score(measurement['metrics'], ['complexity', 'diversity'])
        if not math.isfinite(fitness):
            raise ValueError('invalid reference fitness')
        if best is None or fitness > best_fitness:
            best, best_fitness = ident, fitness
        if event['best_after'] != best:
            raise ValueError('reference best transition differs from pinned host')
        by_id[ident] = measurement
        kinds[ident] = kind
    if observed != set(evaluated) or best != selected_id:
        raise ValueError('reference admission coverage or selected best differs')
    return {'scope': 'caller_supplied_reference_admissions', 'selected_id': best,
            'fitness': best_fitness, 'complete_run_certified': False}


def audit_reference_best_from_physical(events, *, trace, rows, accounting, seed_sha256, selected_id):
    """Bind recorded admissions to caller-authenticated physical stage results.

    The caller must independently authenticate the worker report, physical
    ledger, accounting and patch coverage. This does not certify a full run.
    """
    from zoo.circle_packing.host_physical import _validate_stage_result
    if (type(events) is not list or not events or type(trace) is not dict or
            type(rows) is not list or type(accounting) is not dict or
            accounting.get('iteration_accounting_complete') is not True or
            type(accounting.get('seed_stage_ids')) is not list or
            type(seed_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', seed_sha256) or
            type(trace.get('iterations')) is not list or type(trace.get('stage_bindings')) is not list):
        raise ValueError('reference best requires authenticated complete accounting')
    starts, terminals = {}, {}
    try:
        for row in rows:
            if row['kind'] not in ('host_stage_started', 'host_stage_completed'):
                continue
            payload = row['payload']
            ident = payload['request_id']
            target = starts if row['kind'] == 'host_stage_started' else terminals
            if type(ident) is not str or re.fullmatch(r'[0-9a-f]{32}', ident) is None or ident in target:
                raise ValueError('duplicate or invalid reference stage identity')
            target[ident] = payload
        seen = set()
        def measured(program_ref, ids):
            if type(ids) is not list or not 1 <= len(ids) <= 2:
                raise ValueError('reference evaluation requires a complete cascade')
            stage_metrics = []
            for index, ident in enumerate(ids):
                if ident in seen or ident not in starts or ident not in terminals:
                    raise ValueError('reference stage is missing or reused')
                seen.add(ident)
                start, result = starts[ident], terminals[ident]['result']
                if (start['program_ref'] != program_ref or start['stage'] != index + 1 or
                        start['prior_id'] != (None if index == 0 else ids[0])):
                    raise ValueError('reference cascade differs from its program or ordering')
                _validate_stage_result(result, stage=index + 1, program_ref=program_ref)
                stage_metrics.append(result['metrics'] if result['status'] == 'ok'
                                     else {'combined_score': 0.0, 'fixture_stage_failed': 1.0})
            needs_second = stage_metrics[0]['combined_score'] >= .5
            if needs_second != (len(ids) == 2):
                raise ValueError('reference cascade does not match its threshold')
            if len(stage_metrics) == 1:
                return stage_metrics[0]
            merged = {}
            for metrics in stage_metrics:
                merged.update({key: float(value) for key, value in metrics.items()
                               if isinstance(value, (int, float)) and key != 'error'})
            return merged

        seed_id = events[0]['id']
        seed_ref = 'sha256:' + seed_sha256
        evaluated = {seed_id: {'program_ref': seed_ref,
                               'metrics': measured(seed_ref, accounting['seed_stage_ids'])}}
        iterations = trace['iterations']
        for item in iterations:
            if item['state'] != 'candidate':
                continue
            ident, number = item['child_id'], item['iteration']
            if type(ident) is not str or not ident or ident in evaluated or type(number) is not int:
                raise ValueError('reference candidate identity is duplicated or invalid')
            admissions = [event for event in events if event.get('id') == ident and event.get('kind') == 'candidate']
            if len(admissions) != 1:
                raise ValueError('reference candidate lacks its unique host admission')
            if 'iteration' in admissions[0] and (admissions[0]['iteration'] != number or
                    type(item.get('target_island')) is not int or
                    admissions[0]['target_island'] != item['target_island']):
                raise ValueError('reference candidate admission differs from its iteration or island')
            ref = 'sha256:' + item['program_sha256']
            ids = [binding['request_id'] for binding in trace['stage_bindings'] if binding['iteration'] == number]
            evaluated[ident] = {'program_ref': ref, 'metrics': measured(ref, ids)}
        result = audit_reference_best(events, evaluated=evaluated, selected_id=selected_id)
        return {**result, 'scope': 'caller_pinned_reference_best_from_physical',
                'candidate_iteration_and_island_verified': 'iteration' in events[0]}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid reference best physical evidence') from error
