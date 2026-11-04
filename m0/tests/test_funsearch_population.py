"""Behavioral contract for the FunSearch-inspired population building block."""
import math
import pytest

from core.funsearch_population import FunSearchPopulation


def population(seed=9):
    return FunSearchPopulation(case_ids=['a', 'b'], islands=2, seed=seed,
                               prompt_size=2, temperature=1.0, temperature_period=10)


def test_signature_clusters_objective_and_shorter_program_weights():
    p = population()
    p.register('short', 'x', {'a': .25, 'b': .8}, island=0, epoch=0)
    p.register('long', 'x' * 101, {'b': .8, 'a': .25}, island=0, epoch=0)
    p.register('other', 'z', {'a': .1, 'b': .2}, island=0, epoch=0)
    clusters = p.inspect_island(0)['clusters']
    assert len(clusters) == 2
    first = next(c for c in clusters if c['signature'] == [.25, .8])
    assert first['score'] == .8 and first['candidates'] == ['short', 'long']
    weights = p.program_probabilities(0, [.25, .8])
    expected = math.exp(-100 / (101 + 1e-6))
    assert weights == pytest.approx([1 / (1 + expected), expected / (1 + expected)])
    assert p.cluster_probabilities(0) == pytest.approx(
        [1 / (1 + math.exp(-.6 / .7)), 1 / (1 + math.exp(.6 / .7))])


def test_seeded_checkpoint_restores_sampling_and_retains_reset_history():
    p = population()
    p.register('initial', 'start', {'a': 0, 'b': 0}, island=None)
    p.register('strong', 'best', {'a': .2, 'b': 1}, island=1, epoch=0)
    state = p.checkpoint_state()
    restored = FunSearchPopulation.from_checkpoint(state)
    assert [p.sample(1) for _ in range(5)] == [restored.sample(1) for _ in range(5)]
    events = p.reset_weaker_half()
    assert events == [{'island': 0, 'founder_island': 1, 'founder': 'strong', 'epoch': 1}]
    assert p.inspect_island(0)['clusters'][0]['candidates'] == ['strong']
    assert p.history()[-1] == {'type': 'reset', **events[0]}
    assert p.candidate('initial')['program'] == 'start'
    with pytest.raises(ValueError, match='stale'):
        p.register('late', 'late', {'a': 1, 'b': 1}, island=0, epoch=0)


def test_rejects_nonfinite_incomplete_mutated_and_invalid_data():
    p = population()
    for scores in ({'a': 0}, {'a': 0, 'b': float('nan')}, {'a': 0, 'b': True}):
        with pytest.raises(ValueError):
            p.register('bad', 'x', scores, island=0, epoch=0)
    p.register('one', 'x', {'a': 0, 'b': 1}, island=0, epoch=0)
    with pytest.raises(ValueError):
        p.register('one', 'different', {'a': 0, 'b': 1}, island=1, epoch=0)
    with pytest.raises(ValueError):
        p.sample(1)


def test_stale_proposal_cannot_omit_epoch_and_extreme_scores_remain_finite():
    p = population()
    with pytest.raises(ValueError, match="epoch"):
        p.register('unbound', 'x', {'a': 0, 'b': 0}, island=0)
    p.register('high', 'x', {'a': 0, 'b': 1e308}, island=0, epoch=0)
    p.register('low', 'y', {'a': 0, 'b': -1e308}, island=0, epoch=0)
    assert p.cluster_probabilities(0) == [1.0, 0.0]


def test_reset_checkpoint_replays_and_rejects_tampering():
    p = population()
    p.register('base', 'x', {'a': 0, 'b': 0}, island=None)
    p.register('best', 'xx', {'a': 1, 'b': 1}, island=1, epoch=0)
    p.reset_weaker_half()
    state = p.checkpoint_state()
    restored = FunSearchPopulation.from_checkpoint(state)
    assert restored.checkpoint_state() == state
    state['history'][-1]['founder'] = 'base'
    with pytest.raises(ValueError):
        FunSearchPopulation.from_checkpoint(state)


def test_global_seed_registration_only_allowed_at_initialization():
    p = population()
    p.register('base', 'x', {'a': 0, 'b': 0}, island=None)
    with pytest.raises(ValueError, match='initial'):
        p.register('late', 'y', {'a': 1, 'b': 1}, island=None)
    assert 'late' not in [event.get('candidate') for event in p.history()]


def test_sample_binds_candidates_to_the_island_epoch():
    p = population()
    p.register('base', 'x', {'a': 0, 'b': 0}, island=None)
    draw = p.sample(0)
    assert draw == {'island': 0, 'epoch': 0, 'candidates': ['base']}


def test_checkpoint_rejects_boolean_reset_epoch():
    p = population()
    p.register('base', 'x', {'a': 0, 'b': 0}, island=None)
    p.register('best', 'y', {'a': 0, 'b': 1}, island=1, epoch=0)
    p.reset_weaker_half()
    state = p.checkpoint_state()
    state['history'][-1]['epoch'] = True
    with pytest.raises(ValueError):
        FunSearchPopulation.from_checkpoint(state)


def test_enormous_integer_scores_are_rejected_as_invalid():
    p = population()
    with pytest.raises(ValueError):
        p.register('bad', 'x', {'a': 0, 'b': 10 ** 1000}, island=0, epoch=0)


def test_selection_conditions_on_eligible_candidates_without_sampling_pruned():
    p = population(seed=31)
    p.register('base', 'x', {'a': 0, 'b': 0}, island=None)
    p.register('short', 'a', {'a': 1, 'b': 1}, island=0, epoch=0)
    p.register('long', 'a' * 40, {'a': 1, 'b': 1}, island=0, epoch=0)
    for _ in range(30):
        draw = p.sample(0, eligible={'base', 'long'})
        assert set(draw['candidates']) <= {'base', 'long'}
    before = p.checkpoint_state()
    with pytest.raises(ValueError, match='eligible'):
        p.sample(0, eligible={'outside'})
    assert p.checkpoint_state() == before
    with pytest.raises(ValueError):
        p.sample(0, eligible=['base'])
