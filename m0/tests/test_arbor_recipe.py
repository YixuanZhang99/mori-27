"""Hypothesis choices must precede execution and remain separate from code bases."""
import json
import copy
import hashlib
from dataclasses import replace

import pytest

from test_composed_budget import Domain, Provider, physical_operations
from test_configured_construction import build, profile, records
from core.composition.defaults import default_registry

TASK = 'Test hypotheses against a fixed public development signal.'


class ArborProvider(Provider):
    def __init__(self, mode='pending'):
        super().__init__()
        self.mode = mode

    def __call__(self, prompt):
        super().__call__(prompt)
        request = json.loads(prompt)
        if request.get('kind') == 'arbor_insight':
            return json.dumps({'summary': 'Development observation for ' + request['target_id']})
        if request.get('kind') != 'arbor_ideation':
            return json.dumps({'artifact': 'program:' + request['hypothesis'],
                               'hypothesis': request['hypothesis']})
        observation = request['observation']
        cycle = observation['cycle']
        nodes = sorted(observation['nodes'], key=lambda n: n['created_cycle'])

        def idea(name, parent=None, refs=()):
            return {'parent_id': parent, 'hypothesis': name,
                    'expected_observation': 'Measure the effect on public validation.',
                    'source_refs': list(refs)}

        if self.mode == 'invalid':
            ideas = [idea('unknown parent', 'missing')]
        elif self.mode == 'depth':
            ideas = [idea('extend ' + str(cycle), nodes[-1]['id'] if nodes else None)]
        elif self.mode == 'reference' and cycle:
            ideas = [idea('independent hypothesis', refs=['candidate:' + nodes[0]['id']])]
        elif cycle == 0:
            ideas = [idea('baseline hypothesis'), idea('unused root')]
        elif cycle == 1:
            ideas = [idea('first child', nodes[0]['id']), idea('pending sibling', nodes[0]['id'])]
        else:
            pending = next(item for item in request['pending'] if item['hypothesis'] == 'pending sibling')
            return json.dumps({'new_ideas': [], 'selection': {'pending_id': pending['id']}})
        return json.dumps({'new_ideas': ideas, 'selection': {'new_index': 0}})


def assembly():
    value = profile(frozen=True, projection=['memory'])
    value['policy'] = {'name': 'arbor', 'options': {'max_cycles': 5, 'max_tree_depth': 2,
                                                   'seed': 0, 'max_new_ideas': 3}}
    value['operators'] = [{'name': 'hypothesis_refine'}]
    value['frontier'] = {'name': 'tree', 'options': {'retain_rejected': True}}
    value['memory'] = {'name': 'scoped', 'options': {'context_scope': 'run',
        'levels': ['L1', 'L2'], 'trust_floor': 'ungated', 'include_negative': True,
        'top_k': 20, 'max_chars': 160000}}
    value['budget']['options']['operation_reservations']['planning']['token'] = 100
    value['budget']['options']['operation_reservations']['operator']['token'] = 10
    value['admission'] = {'name': 'layered', 'options': {'call_budget': 6}}
    value['execution']['constructor']['options'] = {'max_attempts': 2}
    return value


def test_arbor_ideates_before_selecting_and_dispatches_one_pending_hypothesis(tmp_path):
    # Greedy execution without a real proposal batch, or consuming all options, must fail.
    provider, domain = ArborProvider(), Domain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=0)
    fw.evolve(TASK)
    proposals = records(fw, 'arbor_ideas_proposed')
    selected = records(fw, 'arbor_selected')
    candidates = records(fw, 'composed_evidence')
    assert len(proposals) == len(selected) == len(candidates) == 1
    assert [idea['hypothesis'] for idea in proposals[0]['ideas']] == ['baseline hypothesis', 'unused root']
    assert selected[0]['hypothesis_id'] == proposals[0]['ideas'][0]['id']
    assert candidates[0]['proposal']['candidate']['hypothesis'] == 'baseline hypothesis'
    assert len(fw._composed.parts['policy'].checkpoint_state()['pending']) == 1
    kinds = [row['kind'] for row in fw.store.read()]
    assert kinds.index('arbor_observed') < kinds.index('arbor_ideas_proposed') < kinds.index('arbor_selected')
    assert kinds.index('arbor_selected') < kinds.index('arbor_dispatched') < kinds.index('composed_evidence')
    assert sum(row['actual']['token'] for row in physical_operations(fw)) >= provider.calls * provider.tokens
    assert len([call for call in domain.calls if call['request']['split_id'] == 'dev']) == 1


def test_pending_idea_uses_new_trunk_without_changing_skeleton_parent(tmp_path):
    # Dispatch from the hypothesis parent instead of the newer trunk changes the algorithm.
    provider, domain = ArborProvider(), Domain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2)
    fw.evolve(TASK)
    candidates = [row['proposal']['candidate'] for row in records(fw, 'composed_evidence')]
    assert [c['hypothesis'] for c in candidates] == ['baseline hypothesis', 'first child', 'pending sibling']
    assert candidates[2]['parents'] == [candidates[0]['id']]
    requests = [json.loads(p) for p in provider.prompts if 'recipe' in json.loads(p)]
    assert requests[2]['recipe']['parent_artifacts'] == [
        {'candidate_id': candidates[1]['id'], 'artifact': 'program:first child'}]
    assert requests[2]['recipe']['hypothesis_binding']['skeleton_parents'] == [candidates[0]['id']]
    assert len(records(fw, 'arbor_ideas_proposed')[2]['ideas']) == 0
    before = provider.calls, len(domain.calls)
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert (provider.calls, len(domain.calls)) == before


def test_reference_edges_do_not_change_depth(tmp_path):
    fw = build(tmp_path, assembly=assembly(), provider=ArborProvider('reference'),
               domain=Domain(), generations=1)
    fw.evolve(TASK)
    candidates = [row['proposal']['candidate'] for row in records(fw, 'composed_evidence')]
    assert candidates[1]['parents'] == []
    assert fw._composed.frontier.nodes[candidates[1]['id']].depth == 0
    assert any(edge['source'] == candidates[0]['id'] and edge['target'] == candidates[1]['id']
               for edge in fw._composed.frontier.edges['reference'])


@pytest.mark.parametrize('mode,generations,constructed', [('invalid', 0, 0), ('depth', 3, 3)])
def test_invalid_or_exhausted_parent_is_not_dispatched(tmp_path, mode, generations, constructed):
    provider, domain = ArborProvider(mode), Domain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=generations)
    with pytest.raises(ValueError, match='Arbor.*parent|Arbor.*depth'):
        fw.evolve(TASK)
    assert len(records(fw, 'materialization_completed')) == constructed
    assert len([call for call in domain.calls if call['request']['split_id'] == 'dev']) == constructed


@pytest.mark.parametrize('reference_parent', [False, True])
def test_exhausted_parent_budget_is_excluded_before_ideation(tmp_path, reference_parent):
    configured = assembly()
    configured['budget']['options']['limits']['direction']['token'] = 8
    configured['budget']['options']['operation_reservations']['operator']['token'] = 1
    configured['budget']['options']['operation_reservations']['planning']['token'] = 4
    configured['budget']['options']['reservation']['token'] = 7
    provider, domain = (CandidateReferenceParents() if reference_parent else ArborProvider()), Domain()
    provider.tokens = 1
    fw = build(tmp_path, assembly=configured, provider=provider, domain=domain, generations=1)
    with pytest.raises(ValueError, match='Arbor.*parent'):
        fw.evolve(TASK)
    assert len(records(fw, 'materialization_completed')) == 1
    planning = [json.loads(p) for p in provider.prompts if json.loads(p).get('kind') == 'arbor_ideation']
    assert len(planning) == 2
    assert planning[1]['observation']['nodes'][0]['status'] == 'pruned'
    assert planning[1]['eligible_parent_ids'] == []


class RepairProvider(ArborProvider):
    def __init__(self, changed=False):
        super().__init__()
        self.changed = changed

    def __call__(self, prompt):
        result = super().__call__(prompt)
        request = json.loads(prompt)
        if request.get('kind') in {'arbor_ideation', 'arbor_insight'}:
            return result
        if request['attempt'] == 1:
            return 'malformed artifact envelope'
        value = json.loads(result)
        if self.changed:
            value['hypothesis'] = 'replace the research direction'
        return json.dumps(value)


def test_same_hypothesis_format_repair_keeps_identity(tmp_path):
    provider, domain = RepairProvider(), Domain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=0)
    fw.evolve(TASK)
    result = records(fw, 'materialization_completed')[0]['construction_result']
    assert result['initial_hypothesis'] == result['effective_hypothesis'] == 'baseline hypothesis'
    assert [item['status'] for item in result['attempts']] == ['invalid_output', 'complete']
    assert provider.calls == 5  # Ideation, two construction attempts, leaf and global synthesis.
    assert sum(r['actual']['token'] for r in physical_operations(fw)) >= 15


def test_changed_hypothesis_repair_is_rejected_with_cost(tmp_path):
    provider, domain = RepairProvider(changed=True), Domain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=0)
    result = fw.evolve(TASK)
    assert result['best_candidate_id'] is None
    assert records(fw, 'materialization_completed') == []
    assert domain.calls == []
    assert provider.calls == 5
    assert sum(r['actual']['token'] for r in physical_operations(fw)) == 25


def test_forged_trunk_binding_fails_before_construction(tmp_path):
    class ReplaceTrunk:
        def apply(self, request):
            if request.cycle == 0:
                return request
            strategy = copy.deepcopy(request.strategy)
            strategy['arbor']['artifact'] = 'substituted code'
            strategy['arbor']['binding']['execution_base']['artifact_sha256'] = hashlib.sha256(b'substituted code').hexdigest()
            return replace(request, strategy=strategy)

    configured = assembly()
    configured['skills'] = [{'name': 'replace-trunk'}]
    registry = default_registry()
    registry.register('skill', 'replace-trunk', lambda ctx, opts: ReplaceTrunk(),
        execution={'schema_version': 1, 'contract': 'projected_skill_v1'})
    provider, domain = ArborProvider(), Domain()
    fw = build(tmp_path, assembly=configured, provider=provider, domain=domain, generations=1, registry=registry)
    with pytest.raises(ValueError, match='Arbor request differs'):
        fw.evolve(TASK)
    assert len(records(fw, 'materialization_completed')) == 1
    assert provider.calls == 5


def test_completed_cycle_resume_retains_unconsumed_hypothesis(tmp_path):
    provider, domain = ArborProvider(), Domain()
    first = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2, stop=1)
    first.evolve(TASK)
    prior_calls = provider.calls
    assert len(records(first, 'materialization_completed')) == 2
    resumed = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2, resume=True)
    resumed.evolve(TASK)
    candidates = [row['proposal']['candidate'] for row in records(resumed, 'composed_evidence')]
    assert [c['hypothesis'] for c in candidates] == ['baseline hypothesis', 'first child', 'pending sibling']
    assert provider.calls == prior_calls + 5
    assert len([call for call in domain.calls if call['request']['split_id'] == 'dev']) == 3


def test_planner_parent_candidates_are_explicit_and_distinct_from_pending_hypotheses(tmp_path):
    class ExplicitParents(ArborProvider):
        def __call__(self, prompt):
            result = super().__call__(prompt)
            request = json.loads(prompt)
            if request.get('kind') != 'arbor_ideation':
                return result
            nodes = request['observation']['nodes']
            eligible = [n['id'] for n in nodes if n['status'] in {'done', 'merged'}
                        and n['eval_status'] == 'ok' and n['score'] is not None
                        and n['depth'] < request['max_tree_depth']]
            assert request['eligible_parent_ids'] == eligible
            assert request['eligible_parent_refs'] == ['candidate:' + identifier for identifier in eligible]
            assert not set(request['eligible_parent_ids']) & {i['id'] for i in request['pending']}
            if nodes:
                # The real response confused these namespaces. Choose a parent from
                # the explicit executed-candidate list, not an unexecuted pending idea.
                assert request['pending']
                value = json.loads(result)
                for idea in value['new_ideas']:
                    idea['parent_id'] = request['eligible_parent_ids'][0]
                return json.dumps(value)
            return result

    provider = ExplicitParents()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=Domain(), generations=1)
    fw.evolve(TASK)
    candidates = records(fw, 'composed_evidence')
    assert len(candidates) == 2
    assert candidates[1]['proposal']['candidate']['parents'] == [candidates[0]['proposal']['candidate']['id']]
    assert fw.replay(TASK)['replay_certificate']['passed']


def test_invalid_unselected_idea_parent_is_rejected_atomically(tmp_path):
    class PendingAsParent(ArborProvider):
        def __call__(self, prompt):
            result = super().__call__(prompt)
            request = json.loads(prompt)
            if request.get('kind') == 'arbor_ideation' and request['observation']['cycle'] == 1:
                value = json.loads(result)
                value['new_ideas'][1]['parent_id'] = request['pending'][0]['id']
                return json.dumps(value)
            return result

    fw = build(tmp_path, assembly=assembly(), provider=PendingAsParent(), domain=Domain(), generations=1)
    with pytest.raises(ValueError, match='hypothesis parent is not eligible'):
        fw.evolve(TASK)
    assert len(records(fw, 'composed_evidence')) == 1
    assert len(records(fw, 'arbor_ideas_proposed')) == 1
    assert fw._composed.parts['policy'].checkpoint_state()['observation']['cycle'] == 0


class CandidateReferenceParents(ArborProvider):
    def __call__(self, prompt):
        result = super().__call__(prompt)
        if json.loads(prompt).get('kind') == 'arbor_ideation':
            value = json.loads(result)
            for idea in value['new_ideas']:
                if idea['parent_id'] is not None:
                    idea['parent_id'] = 'candidate:' + idea['parent_id']
            return json.dumps(value)
        return result


def test_candidate_reference_parent_preserves_lineage_pending_resume_and_replay(tmp_path):
    provider, domain = CandidateReferenceParents(), Domain()
    first = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2, stop=1)
    first.evolve(TASK)
    parent = records(first, 'composed_evidence')[0]['proposal']['candidate']['id']
    batch = records(first, 'arbor_ideas_proposed')[1]
    assert all(idea['parent_id'] == parent for idea in batch['ideas'])
    assert any('candidate:' + parent in r['result'] for r in records(first, 'composed_provider_completed'))
    # A process restart creates fresh external adapters; replay must not capture
    # the already-consumed fixture's mutable counters as its initial state.
    provider, domain = CandidateReferenceParents(), Domain()
    resumed = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2, resume=True)
    resumed.evolve(TASK)
    candidates = [r['proposal']['candidate'] for r in records(resumed, 'composed_evidence')]
    assert len(candidates) == 3 and candidates[1]['parents'] == candidates[2]['parents'] == [parent]
    assert candidates[2]['hypothesis'] == 'pending sibling'
    assert provider.calls == 5
    before = provider.calls, len(domain.calls)
    assert resumed.replay(TASK)['replay_certificate']['passed']
    assert (provider.calls, len(domain.calls)) == before


@pytest.mark.parametrize('invalid', ['missing', 'pending', 'double_prefix', 'empty', 'non_text'])
def test_candidate_reference_does_not_authorize_invalid_unselected_parent(tmp_path, invalid):
    class InvalidReference(CandidateReferenceParents):
        def __call__(self, prompt):
            result = super().__call__(prompt)
            request = json.loads(prompt)
            if request.get('kind') == 'arbor_ideation' and request['observation']['cycle'] == 1:
                value = json.loads(result)
                parent = request['eligible_parent_ids'][0]
                value['new_ideas'][1]['parent_id'] = {
                    'missing': 'candidate:missing', 'pending': 'candidate:' + request['pending'][0]['id'],
                    'double_prefix': 'candidate:candidate:' + parent, 'empty': 'candidate:',
                    'non_text': ['candidate:' + parent]}[invalid]
                return json.dumps(value)
            return result

    fw = build(tmp_path, assembly=assembly(), provider=InvalidReference(), domain=Domain(), generations=1)
    with pytest.raises(ValueError, match='Arbor.*parent'):
        fw.evolve(TASK)
    assert len(records(fw, 'composed_evidence')) == len(records(fw, 'arbor_ideas_proposed')) == 1
    assert fw._composed.parts['policy'].checkpoint_state()['observation']['cycle'] == 0


def test_candidate_reference_parent_still_obeys_depth_limit(tmp_path):
    fw = build(tmp_path, assembly=assembly(), provider=CandidateReferenceParents('depth'),
               domain=Domain(), generations=3)
    with pytest.raises(ValueError, match='Arbor.*depth'):
        fw.evolve(TASK)
    assert len(records(fw, 'composed_evidence')) == 3
