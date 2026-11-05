"""Public Framework adapter for per-instance parent selection, fixture only."""
from dataclasses import replace

import pytest

from core.executor.evaluation_contract import ItemOutcome
from test_composed_budget import Domain, Provider, TASK, options
from core.composition.defaults import composed_profile
from core.loop import Framework, LoopConfig


def profile():
    value = composed_profile()
    value['domain'] = {'name': 'native'}
    value['budget'] = {'name': 'hierarchical', 'options': options()}
    return value


def build(path, *, assembly, provider, domain, generations, resume=False):
    config = LoopConfig(max_generations=generations, total_budget=100000, intent_cost=2000,
                        reeval_floor=0, baseline_every=2, resume_from_checkpoint=resume)
    return Framework.from_profile(assembly, provider, domain, config, str(path))


class ForbiddenDomain(Domain):
    async def evaluate(self, *_args):
        raise AssertionError('recovery must not evaluate again')


class ItemDomain(Domain):
    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        cycle = proposal.candidate.created_cycle
        items = (ItemOutcome('left', int(cycle % 2 == 0), visibility='public'),
                 ItemOutcome('right', int(cycle % 2 == 1), visibility='public'))
        return replace(result, contract=replace(result.contract, items=items))


def test_framework_selects_by_public_instance_winners_and_restores(tmp_path):
    assembly = profile()
    assembly['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 9}}
    domain, provider = ItemDomain(), Provider()
    fw = build(tmp_path, assembly=assembly, provider=provider, domain=domain, generations=3)
    result = fw.evolve(TASK)
    policy = fw._composed.parts['policy']
    assert len(policy.instance_frontier.checkpoint_state()['candidates']) == 4
    winners = policy.instance_frontier.winners()
    assert set(winners['left']).isdisjoint(winners['right'])
    saved = policy.checkpoint_state()
    assert fw.replay(TASK)['replay_certificate']['passed']
    resumed = build(tmp_path, assembly=assembly, provider=Provider(),
                    domain=ForbiddenDomain(), generations=3, resume=True)
    assert resumed.evolve(TASK)['best_candidate_id'] == result['best_candidate_id']
    assert resumed._composed.parts['policy'].checkpoint_state() == saved


def test_framework_rejects_missing_public_item_scores(tmp_path):
    assembly = profile()
    assembly['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 9}}
    with pytest.raises(ValueError, match='public instance'):
        build(tmp_path, assembly=assembly, provider=Provider(), domain=Domain(), generations=0).evolve(TASK)



def test_m7_policy_consumes_only_public_verdicts_and_replays(tmp_path):
    from test_configured_construction import profile as construction_profile, ConstructorProvider, build as construction_build
    class PrivateDomain(ItemDomain):
        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            return replace(result, text_feedback='SECRET_RAW_FEEDBACK', contract=replace(result.contract, items=result.contract.items +
                (ItemOutcome('SECRET_PRIVATE_ITEM', 1, visibility='private'),)))
    assembly = construction_profile(projection=[])
    assembly['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 1}}
    provider = ConstructorProvider()
    fw = construction_build(tmp_path, assembly=assembly, provider=provider, domain=PrivateDomain(), generations=3)
    fw.evolve(TASK)
    policy = fw._composed.parts['policy']
    assert len(policy.instance_frontier.checkpoint_state()['candidates']) == 4
    records = [row['payload'] for row in fw.store.read('composed_evidence')]
    assert records[2]['proposal']['candidate']['parents'] == [records[0]['proposal']['candidate']['id']]
    assert records[1]['evidence']['eval_result']['metrics']['dev/score'] > records[0]['evidence']['eval_result']['metrics']['dev/score']
    assert all('SECRET_PRIVATE_ITEM' not in prompt and 'SECRET_RAW_FEEDBACK' not in prompt for prompt in provider.prompts)
    assert 'SECRET_PRIVATE_ITEM' not in str(policy.checkpoint_state())
    public_events = [row['payload'] for row in fw.store.read('gepa_public_verdicts')]
    assert len(public_events) == 4
    assert all(set(event['verdicts']) == {'left', 'right'} for event in public_events)
    assert 'SECRET_PRIVATE_ITEM' not in str(public_events)
    resumed = construction_build(tmp_path, assembly=assembly, provider=ConstructorProvider(forbidden=True),
                                 domain=ForbiddenDomain(), generations=3, resume=True)
    resumed.evolve(TASK)
    assert resumed._composed.parts['policy'].checkpoint_state() == policy.checkpoint_state()
    assert resumed.replay(TASK, adapter_factory=lambda p, s: (ConstructorProvider(forbidden=True), ForbiddenDomain()))['replay_certificate']['passed']


def test_m7_rejects_coherently_rehashed_policy_score_tampering_on_resume(tmp_path):
    import json
    from core.x1.checkpoint import payload_digest
    from test_configured_construction import profile as construction_profile, ConstructorProvider, build as construction_build
    assembly = construction_profile(projection=[])
    assembly['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 9}}
    fw = construction_build(tmp_path, assembly=assembly, provider=ConstructorProvider(), domain=ItemDomain(), generations=1)
    fw.evolve(TASK)
    path = tmp_path / 'checkpoint.json'
    envelope = json.loads(path.read_text())
    candidate = envelope['payload']['module_states']['policy:0']['instance_frontier']['candidates'][0]
    candidate['scores']['left'] = 1.0 - candidate['scores']['left']
    envelope['payload_sha256'] = payload_digest(envelope['payload'])
    path.write_text(json.dumps(envelope))
    journal = tmp_path / 'x1.jsonl'
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    boundary = [row for row in rows if row['kind'] == 'composed_checkpoint'][-1]
    boundary['payload']['sha256'] = envelope['payload_sha256']
    journal.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    resumed = construction_build(tmp_path, assembly=assembly, provider=ConstructorProvider(forbidden=True),
                                 domain=ForbiddenDomain(), generations=1, resume=True)
    with pytest.raises(ValueError, match='public verdict evidence'):
        resumed.evolve(TASK)


def test_m7_crash_after_public_verdict_event_reuses_original_calls(tmp_path, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from test_configured_construction import profile as construction_profile, ConstructorProvider, build as construction_build
    from test_materialization_recovery import Crash
    assembly = construction_profile(projection=[])
    assembly['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 1}}
    provider, domain = ConstructorProvider(), ItemDomain()
    write = ContinuationStore._write
    def cut(store, row):
        write(store, row)
        if row['kind'] == 'gepa_public_verdicts':
            raise Crash('public verdict committed')
    monkeypatch.setattr(ContinuationStore, '_write', cut)
    first = construction_build(tmp_path, assembly=assembly, provider=provider, domain=domain, generations=0)
    with pytest.raises(Crash):
        first.evolve(TASK)
    assert provider.calls == 1 and len(domain.calls) == 1
    monkeypatch.setattr(ContinuationStore, '_write', write)
    resumed = construction_build(tmp_path, assembly=assembly, provider=ConstructorProvider(forbidden=True),
                                 domain=ForbiddenDomain(), generations=0, resume=True)
    resumed.evolve(TASK)
    assert len(list(resumed.store.read('gepa_public_verdicts'))) == 1
    assert provider.calls == 1 and len(domain.calls) == 1
    assert resumed.replay(TASK, adapter_factory=lambda p, s: (ConstructorProvider(forbidden=True), ForbiddenDomain()))['replay_certificate']['passed']


def test_m7_public_selection_never_receives_control_verdicts(tmp_path):
    from core.loop import Framework
    from test_construction_controls import FreshConstructor
    from test_configured_construction import profile as construction_profile
    from test_governed_runtime import governed
    template, _, _, _, _ = governed(tmp_path, provider_factory=FreshConstructor, domain_factory=ItemDomain)
    assembly = template._composed.assembly.to_dict()
    assembly.update(schema_version=2, execution=construction_profile(projection=[])['execution'])
    assembly['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 1}}
    fw = Framework.from_profile(assembly, FreshConstructor(), ItemDomain(), template._composed.cfg,
                                str(tmp_path), component_registry=template._composed.registry)
    result = fw.evolve(TASK)
    assert result['governance']['completed'] == 3
    events = [row['payload'] for row in fw.store.read('gepa_public_verdicts')]
    main_ids = {row['payload']['proposal']['candidate']['id'] for row in fw.store.read('composed_evidence')}
    control_ids = {row['payload']['construction_result']['candidate']['id']
                   for row in fw.store.read('materialization_completed')
                   if row['payload']['identity']['operation']['lane'] == 'control'}
    assert {event['candidate_id'] for event in events} == main_ids
    assert not control_ids.intersection(main_ids)
    assert {item['id'] for item in fw._composed.parts['policy'].instance_frontier.checkpoint_state()['candidates']} == main_ids
