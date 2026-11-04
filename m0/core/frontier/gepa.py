"""Per-instance winner coverage and reproducible GEPA-style parent selection.

This standalone component covers the instance-frontier selection mechanism, not
GEPA's reflection, paired minibatch acceptance, or an end-to-end reproduction.
All candidates must have complete scores on the same frozen validation set.
"""
from __future__ import annotations

import math
import random


def _tuples(value):
    return tuple(_tuples(item) for item in value) if isinstance(value, list) else value


def _lists(value):
    return [_lists(item) for item in value] if isinstance(value, tuple) else value


class InstanceFrontier:
    """Keep immutable complete score vectors; sample surviving winners by frequency.

    Redundant winner coverage is removed in ascending aggregate-score order.
    Equal aggregate scores are broken by insertion order as a reproducible
    adaptation; the pinned GEPA reference can depend on set iteration for ties.
    """
    def __init__(self, item_ids, *, seed):
        if type(item_ids) is not list or not item_ids or any(type(i) is not str or not i for i in item_ids) \
                or len(set(item_ids)) != len(item_ids) or type(seed) is not int or seed < 0:
            raise ValueError('a frozen unique item list and nonnegative integer seed are required')
        self._items = tuple(item_ids)
        self._seed = seed
        self._scores = {}
        self._rng = random.Random(seed)

    def offer(self, candidate_id, scores):
        if type(candidate_id) is not str or not candidate_id or type(scores) is not dict or set(scores) != set(self._items):
            raise ValueError('candidate and complete frozen validation scores are required')
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in scores.values()):
            raise ValueError('scores must be finite numeric values')
        values = {item: float(scores[item]) for item in self._items}
        if candidate_id in self._scores:
            if self._scores[candidate_id] != values:
                raise ValueError('candidate scores are immutable')
            return
        self._scores[candidate_id] = values

    def _eligible_scores(self, eligible):
        if eligible is not None and (not isinstance(eligible, (set, frozenset)) or
                                     any(type(candidate) is not str for candidate in eligible)):
            raise ValueError('eligible candidates must be an explicit set of identities')
        return {candidate: scores for candidate, scores in self._scores.items()
                if eligible is None or candidate in eligible}

    def winners(self, *, eligible=None):
        scores = self._eligible_scores(eligible)
        if not scores:
            return {item: [] for item in self._items}
        return {item: [candidate for candidate, row in scores.items()
                       if row[item] == max(other[item] for other in scores.values())]
                for item in self._items}

    def pruned_winners(self, *, eligible=None):
        scores = self._eligible_scores(eligible)
        fronts = self.winners(eligible=eligible)
        # Python's stable sort breaks aggregate ties by insertion order.
        candidates = sorted(scores, key=lambda candidate: sum(scores[candidate].values()) / len(self._items))
        for candidate in candidates:
            covered = [item for item in self._items if candidate in fronts[item]]
            if covered and all(len(fronts[item]) > 1 for item in covered):
                for item in covered:
                    fronts[item].remove(candidate)
        return fronts

    def frequencies(self, *, eligible=None):
        counts = {}
        for winners in self.pruned_winners(eligible=eligible).values():
            for candidate in winners:
                counts[candidate] = counts.get(candidate, 0) + 1
        return {candidate: counts[candidate] for candidate in self._scores if candidate in counts}

    def select(self, *, eligible=None):
        # Each winning instance contributes one slot to the seeded draw.
        weighted = [candidate for candidate, count in self.frequencies(eligible=eligible).items() for _ in range(count)]
        if not weighted:
            raise ValueError('no evaluated candidate available for selection')
        return self._rng.choice(weighted)

    def checkpoint_state(self):
        return {'schema_version': 1, 'items': list(self._items), 'seed': self._seed,
                'candidates': [{'id': candidate, 'scores': dict(scores)} for candidate, scores in self._scores.items()],
                'random_state': _lists(self._rng.getstate())}

    @classmethod
    def from_checkpoint(cls, state):
        if type(state) is not dict or set(state) != {'schema_version', 'items', 'seed', 'candidates', 'random_state'} \
                or type(state['schema_version']) is not int or state['schema_version'] != 1 or type(state['candidates']) is not list:
            raise ValueError('invalid instance frontier checkpoint')
        result = cls(state['items'], seed=state['seed'])
        for candidate in state['candidates']:
            if type(candidate) is not dict or set(candidate) != {'id', 'scores'} or \
                    type(candidate['id']) is not str or candidate['id'] in result._scores:
                raise ValueError('invalid checkpoint candidate')
            result.offer(candidate['id'], candidate['scores'])
        try:
            result._rng.setstate(_tuples(state['random_state']))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError('invalid frontier random state') from error
        return result
