"""Research feedback must reach future hypotheses through source-bound M5 entries."""
import json
from dataclasses import replace

from core.executor.types import EvalStatus
from test_arbor_recipe import ArborProvider, TASK, assembly
from test_composed_budget import Domain, Provider
from test_configured_construction import build, records


class FeedbackDomain(Domain):
    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        if request.split_id == 'dev' and proposal.candidate.created_cycle == 2:
            return replace(result, status=EvalStatus.FAILED_TO_RUN, metrics={},
                           text_feedback='BROKEN_SCALE: normalization produced invalid predictions')
        return result


class FeedbackProvider(ArborProvider):
    def __call__(self, prompt):
        request = json.loads(prompt)
        if request.get('kind') == 'arbor_insight':
            Provider.__call__(self, prompt)
            learned = 'BROKEN_SCALE: avoid invalid normalization' if 'BROKEN_SCALE' in prompt else 'validated public signal'
            return json.dumps({'summary': request['target_id'] + ': ' + learned})
        if request.get('kind') == 'arbor_ideation' and request['observation']['cycle'] >= 3:
            Provider.__call__(self, prompt)
            text = json.dumps(request['context'])
            hypothesis = 'avoid broken scaling' if 'BROKEN_SCALE' in text else 'repeat scaling'
            return json.dumps({'new_ideas': [{'parent_id': None, 'hypothesis': hypothesis,
                'expected_observation': 'Check validation after normalization.', 'source_refs': []}],
                'selection': {'new_index': 0}})
        return super().__call__(prompt)


def run_feedback(path, *, ablated=False):
    configured = assembly()
    if ablated:
        # No pilot insight has verified trust: this removes actual retrieval,
        # while keeping the same execution, synthesis and evaluation fixture.
        configured['memory']['options']['trust_floor'] = 'verified'
    provider, domain = FeedbackProvider(), FeedbackDomain()
    fw = build(path, assembly=configured, provider=provider, domain=domain, generations=3)
    fw.evolve(TASK)
    return fw, provider


def test_leaf_failure_updates_ancestors_and_global_prior_then_changes_next_prompt(tmp_path):
    # Merely logging a failed leaf or updating its own insight cannot pass.
    fw, provider = run_feedback(tmp_path)
    candidates = [row['proposal']['candidate'] for row in records(fw, 'composed_evidence')]
    assert candidates[3]['hypothesis'] == 'avoid broken scaling'
    planning = [json.loads(p) for p in provider.prompts if json.loads(p).get('kind') == 'arbor_ideation']
    memory = planning[3]['context']['retrieval']['content']['memory']
    negative = [item for item in memory if 'BROKEN_SCALE' in json.dumps(item['body'])]
    assert {candidates[0]['id'], 'global'} <= {item['body']['target_id'] for item in negative}
    failure_ref = records(fw, 'composed_evidence')[2]['evidence_ref']
    assert all(failure_ref in item['body']['source_refs'] for item in negative)
    synthesis = [json.loads(p) for p in provider.prompts if json.loads(p).get('kind') == 'arbor_insight']
    assert any(row['target_id'] == candidates[0]['id'] and row['previous_summary']
               and 'BROKEN_SCALE' in json.dumps(row) for row in synthesis)


def test_second_child_preserves_first_child_sources(tmp_path):
    fw, provider = run_feedback(tmp_path)
    evidence = records(fw, 'composed_evidence')
    root = evidence[0]['proposal']['candidate']['id']
    last = [json.loads(p) for p in provider.prompts if json.loads(p).get('kind') == 'arbor_ideation'][-1]
    entries = last['context']['retrieval']['content']['memory']
    aggregates = [item for item in entries if item['body'].get('target_id') == root]
    assert len(aggregates) == 1  # Old immutable versions must not all be retrieved.
    assert {evidence[1]['evidence_ref'], evidence[2]['evidence_ref']} <= set(aggregates[0]['body']['source_refs'])
    archived = [entry for entry in fw._composed.memory.entries.values()
                if isinstance(entry.payload.body, dict) and entry.payload.body.get('target_id') == root]
    assert len(archived) > len(aggregates)


def test_insight_ablation_changes_actual_ideation(tmp_path):
    active, active_provider = run_feedback(tmp_path / 'active')
    ablated, ablated_provider = run_feedback(tmp_path / 'ablated', ablated=True)
    def last_hypothesis(fw):
        return records(fw, 'composed_evidence')[-1]['proposal']['candidate']['hypothesis']
    assert last_hypothesis(active) == 'avoid broken scaling'
    assert last_hypothesis(ablated) == 'repeat scaling'
    active_prompt = [p for p in active_provider.prompts if json.loads(p).get('kind') == 'arbor_ideation'][-1]
    ablated_prompt = [p for p in ablated_provider.prompts if json.loads(p).get('kind') == 'arbor_ideation'][-1]
    assert 'BROKEN_SCALE' in active_prompt and 'BROKEN_SCALE' not in ablated_prompt


def test_tampered_pending_checkpoint_rejected_before_provider(tmp_path):
    import pytest
    from core.x1.checkpoint import RunCheckpoint
    from test_aide_recipe import rebind_checkpoint
    fw = build(tmp_path, assembly=assembly(), provider=ArborProvider(), domain=Domain(),
               generations=2, stop=1)
    fw.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    payload['module_states']['policy:0']['pending'][0]['hypothesis'] = 'forged pending work'
    rebind_checkpoint(tmp_path, payload)
    provider, domain = ArborProvider(), Domain()
    with pytest.raises(ValueError, match='Arbor'):
        build(tmp_path, assembly=assembly(), provider=provider, domain=domain,
              generations=2, resume=True).evolve(TASK)
    assert provider.calls == 0 and domain.calls == []


def test_rehashed_aggregate_checkpoint_rejected_before_provider(tmp_path):
    import pytest
    from core.x1.checkpoint import RunCheckpoint
    from core.composition.context import _hash
    from test_aide_recipe import rebind_checkpoint
    fw, _ = run_feedback(tmp_path)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    entries = payload['memory']['entries']
    target = next(e for e in entries if e['payload']['schema_id'] == 'tree_insight/v1'
                  and e['payload']['body']['target_id'] == 'global' and not e['time']['superseded_by'])
    old_ref = target['provenance']['evidence_refs'][0]
    binding = payload['memory']['bindings'].pop(old_ref)
    binding['body']['summary'] = 'forged science'
    new_ref = _hash(binding)
    payload['memory']['bindings'][new_ref] = binding
    old_id, new_id = target['id'], 'arbor-insight:' + new_ref[7:]
    target['id'] = new_id
    target['payload']['body'] = binding['body']
    target['provenance']['evidence_refs'] = [new_ref]
    for entry in entries:
        if entry['time']['superseded_by'] == old_id:
            entry['time']['superseded_by'] = new_id
    rebind_checkpoint(tmp_path, payload)
    provider, domain = FeedbackProvider(), FeedbackDomain()
    with pytest.raises(ValueError, match='Arbor'):
        build(tmp_path, assembly=assembly(), provider=provider, domain=domain,
              generations=3, resume=True).evolve(TASK)
    assert provider.calls == 0 and domain.calls == []


def test_mixed_leaf_continuation_and_replay_use_original_insights(tmp_path):
    provider, domain = FeedbackProvider(), FeedbackDomain()
    first = build(tmp_path, assembly=assembly(), provider=provider, domain=domain,
                  generations=3, stop=2)
    first.evolve(TASK)
    previous_dev_calls = sum(c['request']['split_id'] == 'dev' for c in domain.calls)
    provider, domain = FeedbackProvider(), FeedbackDomain()
    resumed = build(tmp_path, assembly=assembly(), provider=provider, domain=domain,
                    generations=3, resume=True)
    resumed.evolve(TASK)
    assert provider.calls == 4  # Ideation, construction, leaf, global.
    assert records(resumed, 'composed_evidence')[-1]['proposal']['candidate']['hypothesis'] == 'avoid broken scaling'
    assert previous_dev_calls + sum(c['request']['split_id'] == 'dev' for c in domain.calls) == 4
    before = provider.calls, len(domain.calls)
    assert resumed.replay(TASK)['replay_certificate']['passed']
    assert (provider.calls, len(domain.calls)) == before


def test_insight_reference_creates_reference_edge_without_skeleton_parent(tmp_path):
    class CitingProvider(ArborProvider):
        def __call__(self, prompt):
            raw = super().__call__(prompt)
            request = json.loads(prompt)
            if request.get('kind') == 'arbor_ideation' and request['observation']['cycle'] == 1:
                value = json.loads(raw)
                entry = next(e for e in request['context']['retrieval']['content']['memory']
                             if e['body'].get('target_id') == 'global')
                value['new_ideas'][0]['parent_id'] = None
                value['new_ideas'][0]['source_refs'] = entry['provenance']['evidence_refs']
                return json.dumps(value)
            return raw
    fw = build(tmp_path, assembly=assembly(), provider=CitingProvider(), domain=Domain(), generations=1)
    fw.evolve(TASK)
    candidates = [row['proposal']['candidate']['id'] for row in records(fw, 'composed_evidence')]
    assert fw._composed.frontier.nodes[candidates[1]].depth == 0
    assert any(edge['source'] == candidates[0] and edge['target'] == candidates[1]
               for edge in fw._composed.frontier.edges['reference'])


def test_depth_two_synthesis_includes_each_ancestor_and_charges_all_calls(tmp_path):
    from test_composed_budget import physical_operations
    provider = ArborProvider('depth')
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=Domain(), generations=2)
    fw.evolve(TASK)
    targets = records(fw, 'arbor_backpropagated')[-1]['targets']
    candidates = [row['proposal']['candidate']['id'] for row in records(fw, 'composed_evidence')]
    assert targets == list(reversed(candidates)) + ['global']
    synthesis = [json.loads(p) for p in provider.prompts if json.loads(p).get('kind') == 'arbor_insight']
    assert len(synthesis) == 2 + 3 + 4
    assert sum(o['actual']['token'] for o in physical_operations(fw)) >= provider.calls * provider.tokens
    assert fw.replay(TASK)['replay_certificate']['passed']


def test_failed_synthesis_batch_keeps_memory_unapplied_and_charges_calls(tmp_path):
    import pytest
    from test_composed_budget import physical_operations
    class InvalidSummary(ArborProvider):
        def __call__(self, prompt):
            result = super().__call__(prompt)
            request = json.loads(prompt)
            if request.get('kind') == 'arbor_insight' and request['target_id'] == 'global':
                return json.dumps({'summary': '', 'admit': True})
            return result
    provider = InvalidSummary()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=Domain(), generations=0)
    with pytest.raises(ValueError, match='Arbor insight'):
        fw.evolve(TASK)
    assert fw._composed.memory.entries == {}
    assert records(fw, 'composed_evidence') == []
    assert provider.calls == 4
    assert sum(o['actual']['token'] for o in physical_operations(fw)) >= 20
