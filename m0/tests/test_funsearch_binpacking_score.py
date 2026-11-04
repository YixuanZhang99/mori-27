"""Reference-style online packing metrics, independent of a model."""
import numpy as np
import pytest

from core.tasks.funsearch_binpacking import score_instance, score_partition


def test_best_fit_scores_number_of_used_bins():
    instance = {'capacity': 10, 'num_items': 4, 'items': [6, 4, 6, 4]}
    assert score_instance(instance, lambda item, bins: -(bins - item)) == -2


@pytest.mark.parametrize('priority', [lambda item, bins: 0,
                                      lambda item, bins: np.full(len(bins), np.nan),
                                      lambda item, bins: np.ones(len(bins) + 1)])
def test_invalid_priority_result_is_rejected(priority):
    with pytest.raises(ValueError):
        score_instance({'capacity': 10, 'num_items': 1, 'items': [5]}, priority)


def test_partition_returns_ordered_per_case_scores_and_mean():
    cases = {f'{i:02}': {'capacity': 10, 'num_items': 2, 'items': [6, 4]} for i in range(10)}
    result = score_partition(dict(reversed(list(cases.items()))), lambda item, bins: -(bins - item))
    assert list(result['case_scores']) == sorted(cases)
    assert list(result['case_scores'].values()) == [-1] * 10
    assert result['mean_score'] == -1.0
    with pytest.raises(ValueError):
        score_partition({}, lambda item, bins: bins)
