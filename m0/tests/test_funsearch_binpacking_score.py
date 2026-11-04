"""Reference-style online packing metrics, independent of a model."""
import numpy as np
import pytest

from core.tasks.funsearch_binpacking import score_instance


def test_best_fit_scores_number_of_used_bins():
    instance = {'capacity': 10, 'num_items': 4, 'items': [6, 4, 6, 4]}
    assert score_instance(instance, lambda item, bins: -(bins - item)) == -2


@pytest.mark.parametrize('priority', [lambda item, bins: 0,
                                      lambda item, bins: np.full(len(bins), np.nan),
                                      lambda item, bins: np.ones(len(bins) + 1)])
def test_invalid_priority_result_is_rejected(priority):
    with pytest.raises(ValueError):
        score_instance({'capacity': 10, 'num_items': 1, 'items': [5]}, priority)
