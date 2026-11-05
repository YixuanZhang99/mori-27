"""Valid program retention is independent of global incumbent promotion."""
from dataclasses import replace

import pytest

from core.executor.evaluation_contract import ItemOutcome
from test_configured_construction import build
from test_funsearch_framework import CodeProvider, NumericDomain, TASK, assembly


class ComplementaryDomain(NumericDomain):
    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        a, b = [(2, 2), (1, 3), (0, 1), (1, 1)][proposal.candidate.created_cycle]
        return replace(result, metrics={'dev/score': (a + b) / 2},
            contract=replace(result.contract, items=(
                ItemOutcome('a', metrics={'score': a}, visibility='public'),
                ItemOutcome('b', metrics={'score': b}, visibility='public'))))


def configured():
    profile = assembly()
    profile['frontier'] = {'name': 'population', 'options': {'capacity': 4}}
    profile['policy']['options']['reset_interval'] = 5
    return profile


def test_tied_and_worse_valid_programs_remain_eligible_for_island_selection(tmp_path):
    provider = CodeProvider()
    fw = build(tmp_path, assembly=configured(), provider=provider,
               domain=ComplementaryDomain(), generations=3)
    result = fw.evolve(TASK)
    nodes = sorted(fw._composed.frontier.nodes.values(), key=lambda n: n.created_cycle)
    assert len(nodes) == 4
    assert [n.status for n in nodes] == ['merged', 'done', 'done', 'done']
    assert result['best_score'] == 2
    selections = [r['payload']['selection']['receipt'] for r in fw.store.read('funsearch_selection')]
    assert set(selections[-1]['eligible']) == {n.id for n in nodes[:3]}
    assert set(fw._composed.frontier.member_ids) == {n.id for n in nodes}
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert provider.calls == 4


def test_population_funsearch_resume_reuses_original_draw_and_members(tmp_path):
    first = CodeProvider()
    fw = build(tmp_path, assembly=configured(), provider=first,
               domain=ComplementaryDomain(), generations=3, stop=1)
    fw.evolve(TASK)
    before = list(fw.store.read('funsearch_selection'))
    second = CodeProvider()
    restored = build(tmp_path, assembly=configured(), provider=second,
        domain=ComplementaryDomain(), generations=3, resume=True)
    restored.evolve(TASK)
    assert list(restored.store.read('funsearch_selection'))[:len(before)] == before
    assert first.calls + second.calls == 4
    assert len(restored._composed.frontier.member_ids) == 4
    assert restored.replay(TASK)['replay_certificate']['passed']
    assert first.calls + second.calls == 4


@pytest.mark.parametrize('fault', ['draw', 'reset'])
def test_restored_rng_requires_full_original_history(tmp_path, fault):
    import pytest
    from core.funsearch_population import FunSearchPopulation
    fw = build(tmp_path, assembly=assembly(), provider=CodeProvider(),
               domain=ComplementaryDomain(), generations=0)
    fw.evolve(TASK)
    policy = fw._composed.parts['policy']
    state = policy.checkpoint_state()
    forged = FunSearchPopulation.from_checkpoint(state['population'])
    # Valid internal snapshot, but no corresponding original draw or reset.
    if fault == 'draw':
        forged.sample(0)
    else:
        forged.reset_weaker_half()
    state['population'] = forged.checkpoint_state()
    policy.restore_state(state)
    with pytest.raises(ValueError, match='histor'):
        fw._composed.funsearch._audit()


def test_self_consistent_draw_cannot_add_an_unknown_eligible_parent(tmp_path, monkeypatch):
    import pytest
    from core.funsearch_population import FunSearchPopulation
    from core.funsearch_selection import draw_selection
    fw = build(tmp_path, assembly=assembly(), provider=CodeProvider(),
               domain=ComplementaryDomain(), generations=1)
    from core.composition.funsearch_policy import FunSearchPolicy
    original = FunSearchPolicy.select
    async def forged_select(policy, frontier, budget):
        parents = await original(policy, frontier, budget)
        pending = policy.pending_selection()
        if pending is not None:
            policy.population = FunSearchPopulation.from_checkpoint(pending['before'])
            receipt = draw_selection(policy.population, None,
                eligible=set(pending['receipt']['eligible']) | {'not-a-member'}, max_parents=2)
            policy._pending = {'receipt': receipt, 'before': pending['before'],
                               'after': policy.population.checkpoint_state()}
        return parents
    monkeypatch.setattr(FunSearchPolicy, 'select', forged_select)
    with pytest.raises(ValueError, match='eligible'):
        fw.evolve(TASK)


def test_valid_draw_cannot_hide_retained_eligible_members(tmp_path, monkeypatch):
    import pytest
    from core.composition.funsearch_policy import FunSearchPolicy
    from core.funsearch_population import FunSearchPopulation
    from core.funsearch_selection import draw_selection
    original = FunSearchPolicy.select
    async def narrowed_select(policy, frontier, budget):
        parents = await original(policy, frontier, budget)
        pending = policy.pending_selection()
        if pending is not None and len(pending['receipt']['eligible']) > 1:
            policy.population = FunSearchPopulation.from_checkpoint(pending['before'])
            receipt = draw_selection(policy.population, None,
                eligible={pending['receipt']['eligible'][0]}, max_parents=2)
            policy._pending = {'receipt': receipt, 'before': pending['before'],
                               'after': policy.population.checkpoint_state()}
            return receipt['ancestry']
        return parents
    monkeypatch.setattr(FunSearchPolicy, 'select', narrowed_select)
    fw = build(tmp_path, assembly=configured(), provider=CodeProvider(),
               domain=ComplementaryDomain(), generations=2)
    with pytest.raises(ValueError, match='eligible parents'):
        fw.evolve(TASK)
