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
    for index, event in enumerate(events):
        if (type(event) is not dict or set(event) != keys or
                event['kind'] not in {'seed', 'candidate', 'migrant'} or
                type(event['id']) is not str or not event['id'] or event['id'] in by_id or
                event['best_before'] != best):
            raise ValueError('invalid reference admission or best transition')
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
