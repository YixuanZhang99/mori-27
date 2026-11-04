"""Content-bound public OR3 task partitions without executing candidates."""
import pytest

from core.tasks.funsearch_binpacking import split_instances


def test_split_is_order_independent_disjoint_and_content_bound():
    cases = {f'case-{i:02}': {'capacity': 10, 'num_items': 2, 'items': [i % 5 + 1, 1]}
             for i in range(20)}
    first = split_instances(cases)
    second = split_instances(dict(reversed(list(cases.items()))))
    assert first == second
    assert len(first['dev']['instances']) == len(first['held_out']['instances']) == 10
    assert set(first['dev']['instances']).isdisjoint(first['held_out']['instances'])
    changed = {key: dict(value) for key, value in cases.items()}
    changed['case-00']['items'] = [2, 2]
    modified = split_instances(changed)
    assert first['dev']['sha256'] != modified['dev']['sha256']
    assert first['held_out']['sha256'] == modified['held_out']['sha256']


def test_split_rejects_malformed_data_before_use():
    with pytest.raises(ValueError):
        split_instances({'only-one': {'capacity': 10, 'num_items': 1, 'items': [1]}})
    cases = {f'{i:02}': {'capacity': 10, 'num_items': 1, 'items': [1]} for i in range(20)}
    cases['00']['items'] = [11]
    with pytest.raises(ValueError):
        split_instances(cases)
