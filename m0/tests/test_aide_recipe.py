"""Public Framework tree-choice fixtures; actual MLE execution is tested separately."""
import json
from dataclasses import replace

import pytest

from core.x1.checkpoint import RunCheckpoint, payload_digest

from core.executor.types import EvalStatus
from test_composed_budget import Domain, Provider
from test_configured_construction import build, profile, records

TASK = 'Construct a program for a fixed public validation task.'


class PlanProvider(Provider):
    def __call__(self, prompt):
        super().__call__(prompt)
        return json.dumps({'artifact': f'program-{self.generation_index}',
                           'hypothesis': f'generated plan {self.generation_index}'})


class ScoredDomain(Domain):
    def __init__(self, scores):
        super().__init__()
        self.scores = tuple(scores)

    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        score = self.scores[proposal.candidate.created_cycle]
        return replace(result, status=EvalStatus.FAILED_TO_RUN if score is None else EvalStatus.OK,
                       metrics={} if score is None else {'dev/score': score},
                       text_feedback='SyntaxError: fixture broken program' if score is None
                       else 'Public validation completed')


def assembly(*, debug_probability=0.0):
    value = profile(frozen=False, projection=['memory'])
    value['memory'] = {'name': 'scoped', 'options': {
        'context_scope': 'run', 'levels': ['L1'], 'trust_floor': 'ungated',
        'include_negative': True, 'include_imported': False, 'top_k': 10, 'max_chars': 160000}}
    value['policy'] = {'name': 'aide', 'options': {
        'num_drafts': 3, 'debug_probability': debug_probability,
        'max_debug_depth': 2, 'seed': 7}}
    value['operators'] = [{'name': 'draft'}, {'name': 'debug'}, {'name': 'improve'}]
    value['frontier'] = {'name': 'tree', 'options': {'retain_rejected': True}}
    return value


def test_independent_drafts_then_validation_best_improve_preserves_ties_and_history(tmp_path):
    # Catches greedy chaining of initial drafts, deleting valid losers, and tie replacement.
    provider, domain = PlanProvider(), ScoredDomain([.6, .2, .5, .6, .8])
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=4)
    result = fw.evolve(TASK)
    candidates = [r['proposal']['candidate'] for r in records(fw, 'composed_evidence')]
    assert [c['operator'] for c in candidates] == ['draft', 'draft', 'draft', 'improve', 'improve']
    assert [c['parents'] for c in candidates] == [[], [], [], [candidates[0]['id']], [candidates[0]['id']]]
    assert result['best_candidate_id'] == candidates[4]['id']
    assert fw._composed.frontier.nodes[candidates[1]['id']].status == 'done'
    assert fw._composed.frontier.nodes[candidates[2]['id']].status == 'done'
    assert candidates[3]['hypothesis'] == 'generated plan 4'
    requests = [json.loads(p) for p in provider.prompts]
    assert [r['recipe']['kind'] for r in requests] == ['draft', 'draft', 'draft', 'improve', 'improve']
    before = provider.calls, len(domain.calls)
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert (provider.calls, len(domain.calls)) == before


def test_debug_follows_failed_leaf_until_depth_limit_then_improves_valid_best(tmp_path):
    # A failed root counts toward the quota, and cannot be selected again once it has a child.
    provider, domain = PlanProvider(), ScoredDomain([None, .6, .4, None, None, .7])
    fw = build(tmp_path, assembly=assembly(debug_probability=1.0),
               provider=provider, domain=domain, generations=5)
    result = fw.evolve(TASK)
    candidates = [r['proposal']['candidate'] for r in records(fw, 'composed_evidence')]
    assert [c['operator'] for c in candidates] == ['draft', 'draft', 'draft', 'debug', 'debug', 'improve']
    assert [c['parents'] for c in candidates] == [[], [], [], [candidates[0]['id']],
                                               [candidates[3]['id']], [candidates[1]['id']]]
    for index in (0, 3, 4):
        node = fw._composed.frontier.nodes[candidates[index]['id']]
        assert node.eval_status == 'failed_to_run' and node.score is None and node.status == 'done'
    requests = [json.loads(p) for p in provider.prompts]
    assert requests[3]['recipe']['comparison'] == requests[4]['recipe']['comparison'] == {}
    assert result['best_candidate_id'] == candidates[5]['id']
    assert fw.replay(TASK)['replay_certificate']['passed']


def test_empty_construction_failure_counts_as_root_but_is_not_a_repair_parent(tmp_path):
    class EmptyFirst(PlanProvider):
        def __call__(self, prompt):
            response = json.loads(super().__call__(prompt))
            if self.generation_index == 1:
                response['artifact'] = ''
            return json.dumps(response)

    fw = build(tmp_path, assembly=assembly(debug_probability=1.0), provider=EmptyFirst(),
               domain=ScoredDomain([None, .6, .4, .7]), generations=3)
    fw.evolve(TASK)
    candidates = [r['proposal']['candidate'] for r in records(fw, 'composed_evidence')]
    assert [c['operator'] for c in candidates] == ['draft', 'draft', 'draft', 'improve']
    assert candidates[3]['parents'] == [candidates[1]['id']]
    assert fw._composed.frontier.nodes[candidates[0]['id']].eval_status == 'failed_to_run'


def test_exhausted_parent_directions_fall_back_to_a_fresh_draft(tmp_path):
    configured = assembly(debug_probability=1.0)
    # Each completed root uses 12 tokens; the next 10-token reservation cannot fit.
    configured['budget']['options']['limits']['direction']['token'] = 20
    fw = build(tmp_path, assembly=configured, provider=PlanProvider(),
               domain=ScoredDomain([None, .6, .4, .7]), generations=3)
    result = fw.evolve(TASK)
    candidates = [r['proposal']['candidate'] for r in records(fw, 'composed_evidence')]
    assert len(candidates) == 4
    assert [c['operator'] for c in candidates] == ['draft'] * 4
    assert all(c['parents'] == [] for c in candidates)
    assert result['best_candidate_id'] == candidates[3]['id']


@pytest.mark.parametrize('defect', ['retention', 'debug_depth', 'operators', 'admission'])
def test_incoherent_aide_assembly_is_rejected_before_calls(tmp_path, defect):
    configured = assembly()
    if defect == 'retention':
        configured['frontier']['options']['retain_rejected'] = False
    elif defect == 'debug_depth':
        configured['operators'][1]['options'] = {'max_debug_depth': 4}
    elif defect == 'operators':
        configured['operators'] = [{'name': 'draft'}, {'name': 'reflective'}]
    else:
        configured['admission'] = {'name': 'layered'}
    provider = PlanProvider()
    with pytest.raises(ValueError, match='AIDE'):
        build(tmp_path, assembly=configured, provider=provider, domain=ScoredDomain([.2]), generations=0).evolve(TASK)
    assert provider.calls == 0


def rebind_checkpoint(path, payload):
    """Exercise semantic checks beyond the checkpoint's self-declared digest."""
    RunCheckpoint.create(payload).save(path / 'checkpoint.json')
    journal = path / 'x1.jsonl'
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    boundary = [r for r in rows if r['kind'] == 'composed_checkpoint'][-1]
    boundary['payload']['sha256'] = payload_digest(payload)
    journal.write_text(''.join(json.dumps(r) + '\n' for r in rows))


@pytest.mark.parametrize('defect', ['rng', 'frontier_score', 'retention', 'policy_history', 'incumbent'])
def test_rehashed_aide_checkpoint_tampering_is_rejected_before_calls(tmp_path, defect):
    configured = assembly(debug_probability=1.0)
    fw = build(tmp_path, assembly=configured, provider=PlanProvider(),
        domain=ScoredDomain([None, .6, .4, .8, .9]), generations=4, stop=3)
    fw.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    if defect == 'rng':
        import random
        payload['module_states']['policy:0']['rng_state'] = json.loads(json.dumps(random.Random(53).getstate()))
    elif defect == 'policy_history':
        payload['module_states']['policy:0']['base']['history'][-1]['nodes'][0]['score'] = .123
    elif defect == 'incumbent':
        payload['incumbent'] = next(k for k, v in payload['proposals'].items()
                                    if v['candidate']['created_cycle'] == 1)
    else:
        frontier = json.loads(payload['frontier_checkpoint'])
        if defect == 'retention':
            frontier['payload']['config']['retain_rejected'] = False
        else:
            frontier['payload']['nodes'][0]['score'] = 100
        frontier['payload_sha256'] = payload_digest(frontier['payload'])
        payload['frontier_checkpoint'] = json.dumps(frontier)
    rebind_checkpoint(tmp_path, payload)
    provider, domain = PlanProvider(), ScoredDomain([None, .6, .4, .8, .9])
    before = fw.store.path.read_bytes()
    resumed = build(tmp_path, assembly=configured, provider=provider, domain=domain,
                    generations=4, resume=True)
    with pytest.raises(ValueError, match='AIDE|retention'):
        resumed.evolve(TASK)
    assert provider.calls == 0 and domain.calls == []
    assert fw.store.path.read_bytes() == before


def test_aide_resume_preserves_original_tree_and_next_random_choice(tmp_path):
    configured = assembly(debug_probability=1.0)
    scores = [None, .6, None, .8, .9, .7]
    full = build(tmp_path / 'full', assembly=configured, provider=PlanProvider(),
                 domain=ScoredDomain(scores), generations=5)
    expected = full.evolve(TASK)
    first = build(tmp_path / 'resumed', assembly=configured, provider=PlanProvider(),
                  domain=ScoredDomain(scores), generations=5, stop=3)
    first.evolve(TASK)
    provider = PlanProvider()
    resumed = build(tmp_path / 'resumed', assembly=configured, provider=provider,
                    domain=ScoredDomain(scores), generations=5, resume=True)
    actual = resumed.evolve(TASK)
    assert provider.calls == 2
    assert actual['best_candidate_id'] == expected['best_candidate_id']
    assert resumed._composed.frontier._edge_payload() == full._composed.frontier._edge_payload()
    assert resumed.replay(TASK)['replay_certificate']['passed']


@pytest.mark.parametrize('case', ['ordinary_failed', 'debug_success', 'debug_nonleaf', 'debug_depth'])
def test_driver_refuses_forged_parent_capability_before_another_provider_call(tmp_path, case):
    from core.composition.contracts import Selection
    from core.composition.defaults import default_registry
    from core.composition.strategies import GreedyPolicy

    def forced_choice(frontier):
        nodes = sorted(frontier.nodes.values(), key=lambda n: n.created_cycle)
        if not nodes:
            return Selection([], 'draft')
        if case == 'ordinary_failed':
            return Selection([nodes[0].id], 'improve')
        if case == 'debug_nonleaf':
            return Selection([nodes[0].id], 'debug')
        return Selection([nodes[-1].id], 'debug')

    from core.composition.aide_policy import AIDEPolicy
    def create_policy(ctx, opts):
        policy = AIDEPolicy(ctx.scope_context)
        policy.choose = forced_choice
        return policy

    registry = default_registry()
    registry.register('policy', 'forged', create_policy)
    configured = assembly(debug_probability=1.0)
    configured['policy'] = {'name': 'forged'}
    scores = [.4] if case == 'debug_success' else [None] * 4
    provider = PlanProvider()
    fw = build(tmp_path, assembly=configured, provider=provider, domain=ScoredDomain(scores),
               generations=3, registry=registry)
    with pytest.raises(ValueError, match='invalid parents'):
        fw.evolve(TASK)
    assert provider.calls == {'ordinary_failed': 1, 'debug_success': 1,
                              'debug_nonleaf': 2, 'debug_depth': 3}[case]


def test_no_valid_parent_and_disabled_debug_keeps_drafting_without_invented_best(tmp_path):
    fw = build(tmp_path, assembly=assembly(debug_probability=0), provider=PlanProvider(),
               domain=ScoredDomain([None] * 5), generations=4)
    result = fw.evolve(TASK)
    assert result['best_candidate_id'] is None
    assert all(r['proposal']['candidate']['parents'] == [] for r in records(fw, 'composed_evidence'))
    assert all(n.eval_status == 'failed_to_run' and n.score is None and n.status == 'done'
               for n in fw._composed.frontier.nodes.values())
    assert fw.replay(TASK)['replay_certificate']['passed']


@pytest.mark.parametrize('boundary', ['aide_selection', 'materialization_completed'])
def test_interrupted_debug_cycle_adopts_original_decision_and_materialization(tmp_path, monkeypatch, boundary):
    from core.composition.recovery import ContinuationStore

    class Crash(BaseException):
        pass

    original = ContinuationStore._write
    def cut(store, row):
        original(store, row)
        if row['kind'] == boundary and len(list(store.read('composed_evidence'))) == 3:
            raise Crash()

    configured = assembly(debug_probability=1.0)
    provider = PlanProvider()
    fw = build(tmp_path, assembly=configured, provider=provider,
               domain=ScoredDomain([None, .6, .4, .8]), generations=3)
    monkeypatch.setattr(ContinuationStore, '_write', cut)
    with pytest.raises(Crash):
        fw.evolve(TASK)
    monkeypatch.setattr(ContinuationStore, '_write', original)
    resumed_provider = PlanProvider()
    resumed = build(tmp_path, assembly=configured, provider=resumed_provider,
                    domain=ScoredDomain([None, .6, .4, .8]), generations=3, resume=True)
    resumed.evolve(TASK)
    assert provider.calls + resumed_provider.calls == 4
    assert len(records(resumed, 'aide_selection')) == len(records(resumed, 'composed_evidence')) == 4
    candidates = [r['proposal']['candidate'] for r in records(resumed, 'composed_evidence')]
    assert candidates[-1]['operator'] == 'debug' and candidates[-1]['parents'] == [candidates[0]['id']]
    assert resumed.replay(TASK)['replay_certificate']['passed']


def test_skill_cannot_switch_the_operator_after_parent_authorization(tmp_path):
    from core.composition.defaults import default_registry

    class SwitchOperator:
        def apply(self, request):
            if request.parents:
                request.strategy['operator'] = 'debug'
            return request

    registry = default_registry()
    registry.register('skill', 'switch', lambda ctx, opts: SwitchOperator(),
                      execution={'schema_version': 1, 'contract': 'projected_skill_v1'})
    configured = assembly(debug_probability=0)
    configured['skills'] = [{'name': 'switch'}]
    provider = PlanProvider()
    fw = build(tmp_path, assembly=configured, provider=provider,
               domain=ScoredDomain([.6, .4, .3, .8]), generations=3, registry=registry)
    fw.evolve(TASK)
    candidates = [r['proposal']['candidate'] for r in records(fw, 'composed_evidence')]
    assert candidates[-1]['operator'] == 'improve'
    assert json.loads(provider.prompts[-1])['recipe']['kind'] == 'improve'


@pytest.mark.parametrize('defect', ['body', 'level', 'source', 'missing'])
def test_aide_restore_rejects_rehashed_journal_facts_before_calls(tmp_path, defect):
    configured = assembly(debug_probability=1)
    fw = build(tmp_path, assembly=configured, provider=PlanProvider(),
        domain=ScoredDomain([None, .6, .4, .8, .9]), generations=4, stop=3)
    fw.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    entry = payload['memory']['entries'][0]
    if defect == 'body':
        entry['payload']['body']['generated_plan'] = 'FORGED_GENERATED_PLAN'
    elif defect == 'level':
        entry['level'] = 'L2'
    elif defect == 'source':
        entry['payload']['body']['artifact_sha256'] = 'sha256:' + 'f' * 64
    else:
        payload['memory']['entries'].pop()
    rebind_checkpoint(tmp_path, payload)
    provider, domain = PlanProvider(), ScoredDomain([None, .6, .4, .8, .9])
    resumed = build(tmp_path, assembly=configured, provider=provider, domain=domain,
                    generations=4, resume=True)
    with pytest.raises(ValueError, match='AIDE journal'):
        resumed.evolve(TASK)
    assert provider.calls == 0 and domain.calls == []


def test_selected_old_failed_parent_missing_from_small_context_refuses_generation(tmp_path):
    configured = assembly(debug_probability=1)
    configured['memory']['options']['max_chars'] = 1024
    provider = PlanProvider()
    fw = build(tmp_path, assembly=configured, provider=provider,
               domain=ScoredDomain([None, .6, .4, .8]), generations=3)
    with pytest.raises(ValueError, match='selected failed parent.*feedback'):
        fw.evolve(TASK)
    assert provider.calls == 3


@pytest.mark.parametrize('defect', ['levels', 'scope', 'trust', 'imports', 'projection'])
def test_aide_rejects_nonjournal_memory_configuration_before_calls(tmp_path, defect):
    configured = assembly()
    options = configured['memory']['options']
    if defect == 'levels':
        options['levels'] = ['L2']
    elif defect == 'scope':
        options['context_scope'] = 'ancestors'
    elif defect == 'trust':
        options['trust_floor'] = 'gated'
    elif defect == 'imports':
        options['include_imported'] = True
    else:
        configured['execution']['spec']['context_projection'] = []
    provider = PlanProvider()
    with pytest.raises(ValueError, match='AIDE.*journal'):
        build(tmp_path, assembly=configured, provider=provider,
              domain=ScoredDomain([.6]), generations=0).evolve(TASK)
    assert provider.calls == 0


def test_old_failed_parent_survives_eight_newer_journal_entries(tmp_path):
    configured = assembly(debug_probability=1)
    configured['policy']['options']['num_drafts'] = 9
    provider = PlanProvider()
    fw = build(tmp_path, assembly=configured, provider=provider,
               domain=ScoredDomain([None] + [.6] * 8 + [.8]), generations=9)
    fw.evolve(TASK)
    evidence = records(fw, 'composed_evidence')
    original = evidence[0]['proposal']['candidate']['id']
    request = json.loads(provider.prompts[-1])
    assert request['recipe']['kind'] == 'debug'
    entries = request['context']['content']['memory']
    assert len(entries) == 9
    selected = next(e['body'] for e in entries if e['body']['candidate_id'] == original)
    assert selected['public_feedback'] == 'SyntaxError: fixture broken program'
    assert selected['generated_plan'] == 'generated plan 1'
    second = next(e['body'] for e in entries if e['body']['candidate_id'] == evidence[1]['proposal']['candidate']['id'])
    assert second['dev_metrics'] == {'dev/score': .6}
    assert 'independent' in second['initial_intent']
    assert all(e.level == 'L1' and e.state == 'active' for e in fw._composed.memory.entries.values())
    assert fw.replay(TASK)['replay_certificate']['passed']
