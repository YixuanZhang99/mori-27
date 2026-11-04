"""Selection receipts preserve sample order and replayable ancestry."""
import copy
import pytest
from core.funsearch_population import FunSearchPopulation
from core.funsearch_selection import draw_selection, verify_selection


def setup_population():
    p = FunSearchPopulation(case_ids=['a', 'b'], islands=2, seed=7,
                            prompt_size=2, temperature=10, temperature_period=10)
    p.register('a', 'x', {'a': 0, 'b': 0}, island=None)
    p.register('b', 'y', {'a': 1, 'b': 1}, island=0, epoch=0)
    return p


def test_selection_preserves_repeated_samples_and_replays_rng():
    p = setup_population()
    for _ in range(30):
        before = p.checkpoint_state()
        receipt = draw_selection(p, 0, eligible={'a', 'b'}, max_parents=2)
        after = p.checkpoint_state()
        assert verify_selection(receipt, before, after, eligible={'a', 'b'}, max_parents=2)
        if len(receipt['samples']) != len(receipt['ancestry']):
            break
    else:
        pytest.fail('fixture did not sample a duplicate')
    assert receipt['ancestry'] == list(dict.fromkeys(receipt['samples']))
    changed = copy.deepcopy(receipt)
    changed['samples'].reverse()
    if changed['samples'] == receipt['samples']:
        changed['samples'][0] = 'other'
    with pytest.raises(ValueError):
        verify_selection(changed, before, after, eligible={'a', 'b'}, max_parents=2)
    with pytest.raises(ValueError):
        verify_selection(receipt, before, after, eligible={'a'}, max_parents=2)


def test_selection_fails_before_advancing_rng_for_incompatible_lineage():
    p = setup_population()
    before = p.checkpoint_state()
    with pytest.raises(ValueError, match='parent'):
        draw_selection(p, 0, eligible={'a', 'b'}, max_parents=1)
    assert p.checkpoint_state() == before
    with pytest.raises(ValueError):
        draw_selection(p, 0, eligible={'missing'}, max_parents=2)
    assert p.checkpoint_state() == before


def test_receipt_rejects_boolean_disguised_as_integer():
    p = setup_population()
    before = p.checkpoint_state()
    receipt = draw_selection(p, 0, eligible={'a', 'b'}, max_parents=2)
    after = p.checkpoint_state()
    receipt['schema_version'] = True
    with pytest.raises(ValueError):
        verify_selection(receipt, before, after, eligible={'a', 'b'}, max_parents=2)
