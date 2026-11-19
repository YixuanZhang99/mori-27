"""Policy must delegate parent choice to the actual evidence-bound host."""
import asyncio
from types import SimpleNamespace

import pytest

from core.memory.types import ScopeContext
from test_openevolve_state import measured, new_adapter


def policy(adapter):
    from core.composition.openevolve_policy import OpenEvolvePolicy
    return OpenEvolvePolicy(ScopeContext('run', 'task', 'domain'), adapter=adapter)


def node(identifier, status='done', evaluation='ok', score=.5):
    return SimpleNamespace(id=identifier, status=status, eval_status=evaluation, score=score)


def test_policy_uses_only_eligible_original_sources_and_requires_original_events():
    adapter = new_adapter(num_islands=1)
    measured(adapter, 'root', .4, iteration=0)
    subject = policy(adapter)
    frontier = SimpleNamespace(nodes={'root': node('root'), 'dead': node('dead', status='pruned')})
    selected = asyncio.run(subject.select_for_candidate('child', frontier, {}, adapter.events))
    assert selected == ['root']
    assert subject.pending_selection()['source_candidate_id'] == 'root'
    with pytest.raises(ValueError, match='candidate'):
        asyncio.run(subject.select(frontier, {}))


def test_policy_rejects_unbound_or_missing_original_history_before_host_selection():
    adapter = new_adapter(num_islands=1)
    measured(adapter, 'root', .4, iteration=0)
    subject = policy(adapter)
    frontier = SimpleNamespace(nodes={'root': node('root')})
    before = adapter.checkpoint_state()
    with pytest.raises(ValueError):
        asyncio.run(subject.select_for_candidate('child', frontier, {}, []))
    assert adapter.checkpoint_state() == before
    frontier.nodes['root'].status = 'pruned'
    with pytest.raises(ValueError, match='eligible'):
        asyncio.run(subject.select_for_candidate('child', frontier, {}, adapter.events))
    assert adapter.checkpoint_state() == before


def test_policy_seed_selection_requires_an_empty_frontier():
    subject = policy(new_adapter())
    empty = SimpleNamespace(nodes={})
    assert asyncio.run(subject.select_for_candidate('seed', empty, {}, [])) == []
    with pytest.raises(ValueError, match='evidence'):
        asyncio.run(subject.select_for_candidate('seed', SimpleNamespace(nodes={'root': node('root')}), {}, []))
    with pytest.raises(ValueError, match='evidence'):
        asyncio.run(subject.select_for_candidate('seed', SimpleNamespace(nodes={'bad': node('bad', status='pruned')}), {}, []))


def test_policy_checkpoint_binds_host_state_to_original_events():
    adapter = new_adapter(num_islands=1)
    measured(adapter, 'root', .4, iteration=0)
    subject = policy(adapter)
    state = subject.checkpoint_state()
    restored = policy(new_adapter(num_islands=1))
    restored.restore_state(state, adapter.events)
    assert restored.adapter.checkpoint_state() == adapter.checkpoint_state()
    bad = dict(state)
    bad['host'] = dict(state['host'], program_order=['forged'])
    before = restored.adapter.checkpoint_state()
    with pytest.raises(ValueError):
        restored.restore_state(bad, adapter.events)
    assert restored.adapter.checkpoint_state() == before
