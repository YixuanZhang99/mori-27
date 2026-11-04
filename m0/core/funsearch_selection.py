"""Replayable ordered program sampling, independent of the runtime journal.

The returned receipt must be bound to committed evidence by the runtime before
any external invocation. This module does not authenticate checkpoints itself.
"""
from __future__ import annotations

from core.funsearch_population import FunSearchPopulation
from core.x1.checkpoint import payload_digest


def _ref(value):
    return 'sha256:' + payload_digest(value)


def draw_selection(population, island, *, eligible, max_parents):
    if not isinstance(population, FunSearchPopulation):
        raise ValueError('FunSearch population required')
    if type(eligible) not in (set, frozenset) or any(type(x) is not str or not x for x in eligible):
        raise ValueError('explicit eligible identity set required')
    if type(max_parents) is not int or max_parents < population.prompt_size:
        raise ValueError('parent limit must accommodate the configured prompt size')
    before = _ref(population.checkpoint_state())
    result = population.sample_any(eligible=eligible) if island is None else population.sample(island, eligible=eligible)
    samples = result['candidates']
    return {'schema_version': 2, 'requested_island': island, 'island': result['island'], 'epoch': result['epoch'],
            'samples': samples, 'ancestry': list(dict.fromkeys(samples)),
            'eligible': sorted(eligible), 'state_before_ref': before,
            'state_after_ref': _ref(population.checkpoint_state())}


def verify_selection(receipt, before, after, *, eligible, max_parents):
    if type(receipt) is not dict or type(before) is not dict or type(after) is not dict:
        raise ValueError('selection and population states must be objects')
    population = FunSearchPopulation.from_checkpoint(before)
    try:
        replayed = draw_selection(population, receipt['requested_island'], eligible=eligible, max_parents=max_parents)
    except (KeyError, TypeError) as exc:
        raise ValueError('invalid selection receipt') from exc
    if _ref(receipt) != _ref(replayed) or _ref(population.checkpoint_state()) != _ref(after):
        raise ValueError('selection receipt or replayed population state differs')
    return True
