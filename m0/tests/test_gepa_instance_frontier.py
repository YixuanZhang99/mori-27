"""GEPA's per-instance winners are distinct from aggregate-score ranking."""
import copy
import math

import pytest

from core.frontier.gepa import InstanceFrontier


def test_pruning_preserves_each_instance_and_uses_winner_frequency():
    frontier = InstanceFrontier(['a', 'b', 'c'], seed=7)
    frontier.offer('A', {'a': 1, 'b': 0, 'c': 0})
    frontier.offer('B', {'a': 0, 'b': 1, 'c': 1})
    frontier.offer('C', {'a': 1, 'b': 1, 'c': 0})
    assert frontier.winners() == {'a': ['A', 'C'], 'b': ['B', 'C'], 'c': ['B']}
    assert frontier.pruned_winners() == {'a': ['C'], 'b': ['B', 'C'], 'c': ['B']}
    assert frontier.frequencies() == {'B': 2, 'C': 2}
    assert {frontier.select() for _ in range(30)} == {'B', 'C'}


def test_checkpoint_restores_random_stream_and_frontier():
    left = InstanceFrontier(['a', 'b'], seed=3)
    left.offer('left', {'a': 1, 'b': 0})
    left.offer('right', {'a': 0, 'b': 1})
    left.select()
    right = InstanceFrontier.from_checkpoint(copy.deepcopy(left.checkpoint_state()))
    assert [left.select() for _ in range(20)] == [right.select() for _ in range(20)]
    assert left.checkpoint_state() == right.checkpoint_state()


@pytest.mark.parametrize('scores', [{}, {'a': 1}, {'a': True, 'b': 1},
                                     {'a': math.nan, 'b': 1}, {'a': 1, 'b': math.inf},
                                     {'a': 1, 'b': 2, 'extra': 3}])
def test_reject_incomplete_or_invalid_scores_without_mutating_state(scores):
    frontier = InstanceFrontier(['a', 'b'], seed=4)
    before = frontier.checkpoint_state()
    with pytest.raises(ValueError):
        frontier.offer('bad', scores)
    assert frontier.checkpoint_state() == before


def test_candidate_identity_is_immutable_and_empty_selection_is_rejected():
    frontier = InstanceFrontier(['a'], seed=0)
    with pytest.raises(ValueError):
        frontier.select()
    frontier.offer('x', {'a': 1})
    frontier.offer('x', {'a': 1})
    with pytest.raises(ValueError):
        frontier.offer('x', {'a': 0})


def test_reject_malformed_checkpoint_without_coercing_candidate_identity():
    frontier = InstanceFrontier(['a'], seed=0)
    state = frontier.checkpoint_state()
    state['candidates'] = [{'id': [], 'scores': {'a': 1}}]
    with pytest.raises(ValueError):
        InstanceFrontier.from_checkpoint(state)
