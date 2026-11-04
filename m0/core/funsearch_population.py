"""Durable FunSearch-inspired island population; not an end-to-end reproduction.

Cluster scores use the final *frozen* case id, equivalent to the reference's
last inserted test when that input order is fixed. Sampling uses Python's seeded
PRNG rather than NumPy's global generator, so individual draws are not bitwise
identical to upstream. Resets retain a replayable history and reject late writes.
"""
from __future__ import annotations

import copy
import math
import random


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _softmax(values, temperature):
    maximum = max(values)
    weights = [math.exp((value - maximum) / temperature) for value in values]
    total = sum(weights)
    return [value / total for value in weights]


def _lists(value):
    return [_lists(x) for x in value] if isinstance(value, tuple) else value


def _tuples(value):
    return tuple(_tuples(x) for x in value) if isinstance(value, list) else value


class FunSearchPopulation:
    def __init__(self, *, case_ids, islands, seed, prompt_size, temperature, temperature_period):
        if (not isinstance(case_ids, list) or not case_ids or
                any(type(x) is not str or not x for x in case_ids) or
                len(set(case_ids)) != len(case_ids) or case_ids != sorted(case_ids)):
            raise ValueError('frozen sorted unique case ids are required')
        if (type(islands) is not int or islands < 2 or type(seed) is not int or seed < 0 or
                type(prompt_size) is not int or prompt_size < 1 or
                not _finite(temperature) or temperature <= 0 or
                type(temperature_period) is not int or temperature_period < 1):
            raise ValueError('invalid population configuration')
        self.case_ids = tuple(case_ids)
        self.islands, self.seed, self.prompt_size = islands, seed, prompt_size
        self.temperature, self.temperature_period = float(temperature), temperature_period
        self._rng = random.Random(seed)
        self._candidates = {}
        self._islands = [self._empty() for _ in range(islands)]
        self._history = []

    @staticmethod
    def _empty(epoch=0):
        return {'epoch': epoch, 'clusters': {}, 'count': 0, 'best': None}

    def _island(self, index):
        if type(index) is not int or not 0 <= index < self.islands:
            raise ValueError('invalid island')
        return self._islands[index]

    def register(self, candidate_id, program, scores, *, island, epoch=None):
        if (island is None and epoch is not None) or (island is not None and epoch is None):
            raise ValueError('island-specific registration requires an epoch')
        if island is None and self._history:
            raise ValueError('global seed registration is only valid at initialization')
        if (type(candidate_id) is not str or not candidate_id or type(program) is not str or not program or
                type(scores) is not dict or set(scores) != set(self.case_ids) or
                any(not _finite(v) for v in scores.values())):
            raise ValueError('candidate requires finite scores for all frozen cases')
        record = {'program': program, 'scores': {key: float(scores[key]) for key in self.case_ids}}
        existing = self._candidates.get(candidate_id)
        if existing is not None and existing != record:
            raise ValueError('candidate identity cannot be changed')
        indices = list(range(self.islands)) if island is None else [island]
        for index in indices:
            state = self._island(index)
            if epoch is not None and (type(epoch) is not int or epoch != state['epoch']):
                raise ValueError('stale island epoch')
        self._candidates[candidate_id] = record
        for index in indices:
            state = self._island(index)
            sig = tuple(record['scores'][key] for key in self.case_ids)
            members = state['clusters'].setdefault(sig, [])
            if candidate_id in members:
                continue
            members.append(candidate_id)
            state['count'] += 1
            if state['best'] is None or record['scores'][self.case_ids[-1]] > self._candidates[state['best']]['scores'][self.case_ids[-1]]:
                state['best'] = candidate_id
            self._history.append({'type': 'register', 'island': index, 'candidate': candidate_id,
                                  'epoch': state['epoch']})

    def candidate(self, candidate_id):
        return copy.deepcopy(self._candidates[candidate_id])

    def history(self):
        return copy.deepcopy(self._history)

    def inspect_island(self, index):
        state = self._island(index)
        return {'epoch': state['epoch'], 'count': state['count'], 'best': state['best'],
                'clusters': [{'signature': list(sig), 'score': sig[-1], 'candidates': list(ids)}
                             for sig, ids in state['clusters'].items()]}

    def cluster_probabilities(self, index):
        state = self._island(index)
        if not state['clusters']:
            raise ValueError('island is empty')
        temp = self.temperature * (1 - (state['count'] % self.temperature_period) / self.temperature_period)
        return _softmax([signature[-1] for signature in state['clusters']], temp)

    def program_probabilities(self, index, signature):
        try:
            ids = self._island(index)['clusters'][tuple(signature)]
        except (KeyError, TypeError) as exc:
            raise ValueError('unknown signature') from exc
        lengths = [len(self._candidates[candidate]['program']) for candidate in ids]
        shortest, longest = min(lengths), max(lengths)
        return _softmax([-(length - shortest) / (longest + 1e-6) for length in lengths], 1.0)

    def sample(self, index):
        state = self._island(index)
        signatures = list(state['clusters'])
        weights = self.cluster_probabilities(index)
        choices = self._rng.choices(signatures, weights=weights, k=min(len(signatures), self.prompt_size))
        selected = []
        for signature in choices:
            ids = state['clusters'][signature]
            selected.append(self._rng.choices(ids, weights=self.program_probabilities(index, signature), k=1)[0])
        return {'island': index, 'epoch': state['epoch'],
                'candidates': sorted(selected, key=lambda candidate: self._candidates[candidate]['scores'][self.case_ids[-1]])}

    def _reset(self, index, founder_island, founder, epoch):
        old = self._island(index)
        if (type(epoch) is not int or epoch != old['epoch'] + 1 or founder_island == index or
                self._island(founder_island)['best'] != founder or founder not in self._candidates):
            raise ValueError('invalid reset founder or epoch')
        self._islands[index] = self._empty(epoch)
        record = self._candidates[founder]
        signature = tuple(record['scores'][key] for key in self.case_ids)
        self._islands[index].update(clusters={signature: [founder]}, count=1, best=founder)
        event = {'island': index, 'founder_island': founder_island, 'founder': founder, 'epoch': epoch}
        self._history.append({'type': 'reset', **event})
        return event

    def reset_weaker_half(self):
        if any(state['best'] is None for state in self._islands):
            raise ValueError('cannot reset an empty island')
        rank = sorted(range(self.islands), key=lambda i: self._candidates[self._islands[i]['best']]['scores'][self.case_ids[-1]] + self._rng.gauss(0, 1e-6))
        count = self.islands // 2
        keep = rank[count:]
        events = []
        for index in rank[:count]:
            founder_island = self._rng.choice(keep)
            events.append(self._reset(index, founder_island, self._islands[founder_island]['best'], self._islands[index]['epoch'] + 1))
        return events

    def checkpoint_state(self):
        return {'schema_version': 1, 'config': {'case_ids': list(self.case_ids), 'islands': self.islands,
                'seed': self.seed, 'prompt_size': self.prompt_size, 'temperature': self.temperature,
                'temperature_period': self.temperature_period}, 'candidates': copy.deepcopy(self._candidates),
                'history': self.history(), 'random_state': _lists(self._rng.getstate())}

    @classmethod
    def from_checkpoint(cls, state):
        if (type(state) is not dict or set(state) != {'schema_version', 'config', 'candidates', 'history', 'random_state'} or
                type(state['schema_version']) is not int or state['schema_version'] != 1 or
                type(state['config']) is not dict or type(state['candidates']) is not dict or type(state['history']) is not list):
            raise ValueError('invalid population checkpoint')
        try:
            result = cls(**state['config'])
            for event in state['history']:
                if type(event) is not dict:
                    raise ValueError('invalid history event')
                if event.get('type') == 'register' and set(event) == {'type', 'island', 'candidate', 'epoch'}:
                    record = state['candidates'][event['candidate']]
                    if type(record) is not dict or set(record) != {'program', 'scores'}:
                        raise ValueError('invalid candidate record')
                    result.register(event['candidate'], record['program'], record['scores'], island=event['island'], epoch=event['epoch'])
                elif event.get('type') == 'reset' and set(event) == {'type', 'island', 'founder_island', 'founder', 'epoch'}:
                    result._reset(event['island'], event['founder_island'], event['founder'], event['epoch'])
                else:
                    raise ValueError('invalid history event')
            if result._candidates != state['candidates'] or result._history != state['history']:
                raise ValueError('checkpoint history mismatch')
            result._rng.setstate(_tuples(state['random_state']))
            return result
        except (TypeError, KeyError, OverflowError, IndexError) as exc:
            raise ValueError('invalid population checkpoint') from exc
