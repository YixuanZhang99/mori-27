"""Actual Framework population/crossover flow with one DAG and governed M9 state."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import asdict, replace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.defaults import default_registry, population_profile
from core.composition.evaluation import EvaluationContract, PrivateEvaluationData, binding_for
from core.composition.population import PopulationPolicy
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.frontier.population import PopulationFrontier
from core.frontier.research import FrontierCheckpoint, _digest
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import RunCheckpoint

TASK = 'combine two population members while keeping gate selection independent'


class Provider:
    model = 'population-offline-v1'
    supplier = 'offline-simulation'

    def __init__(self, fail_crossover=False):
        self.calls, self.index, self.prompts = 0, 0, []
        self.fail_crossover = fail_crossover

    def __call__(self, prompt):
        self.calls += 1; self.index += 1; self.prompts.append(prompt)
        crossover = prompt.startswith('[composed-crossover')
        self.last_usage = {'total_tokens': 7 if crossover else 5}
        if crossover:
            if self.fail_crossover:
                raise RuntimeError('known-cost native crossover error')
            parents = json.loads(prompt.split('PARENTS:\n', 1)[1].split('\nCONTEXT:', 1)[0])
            return 'COMBINED[' + '|'.join(parent['artifact'] for parent in parents) + ']'
        return 'ROOT-' + str(self.index)

    def checkpoint_state(self):
        return {'index': self.index}

    def restore_state(self, state):
        self.index = state['index']


class Domain:
    evaluator_version = 'population-native-v1'
    measured_cost_units = ('token', 'eval_count', 'node')
    contexts = {split: 'sha256:' + hashlib.sha256(text.encode()).hexdigest() for split, text in (
        ('dev', 'population development contents'), ('admission', 'population held out gate contents'),
        ('final_audit', 'population sealed final contents'))}
    evaluation_context = contexts['dev']

    def __init__(self, gate_scores=(10, 9, 8, 11, 7, 12), failed_cycle=None):
        self.gate_scores, self.failed_cycle, self.calls = tuple(gate_scores), failed_cycle, []

    def validate_request(self, request):
        request.validate()
        if request.split_id not in self.contexts:
            raise ValueError('unsupported population domain split')

    def evaluation_context_for(self, request):
        return self.contexts[request.split_id]

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        cycle, split = proposal.candidate.created_cycle, request.split_id
        self.calls.append({'cycle': cycle, 'candidate_id': proposal.candidate.id,
            'parents': list(proposal.candidate.parents), 'artifact': proposal.artifact, 'request': copy.deepcopy(asdict(request))})
        failed = split == 'dev' and cycle == self.failed_cycle
        score = cycle + 1 if split == 'dev' else self.gate_scores[cycle] if split == 'admission' else -100
        metrics = {} if failed else {('dev/score' if split == 'dev' else 'gate/score'): score}
        return EvalResult(EvalStatus.FAILED_TO_RUN if failed else EvalStatus.OK, metrics,
            CostVec(tokens_in=2, eval_count=1), fidelity=request.fidelity,
            text_feedback='lesson:' + str(cycle) if split == 'dev' else 'HELD_OUT_POPULATION_CANARY',
            contract=EvaluationContract(binding_for(proposal, request, evaluator_version=self.evaluator_version,
                evaluation_context=self.evaluation_context_for(request)), self.measured_cost_units,
                private=PrivateEvaluationData(data={'secret': 'PRIVATE_POPULATION_CANARY'})))


def assembly(*, capacity=2, selection='uniform', seed=17, scalar=False):
    value = population_profile(capacity=capacity, selection=selection, sample_seed=seed)
    value['domain'] = {'name': 'native'}
    value['memory'] = {'name': 'scoped', 'options': {'context_scope': 'parents', 'max_chars': 16000}}
    value['admission'] = {'name': 'layered', 'options': {
        'metric': 'gate/score', 'dev_metric': 'dev/score', 'direction': 'maximize', 'dev_direction': 'maximize'}}
    if not scalar:
        value['budget'] = {'name': 'hierarchical', 'options': {
            'limits': {level: {'token': 10000, 'node': 100, 'eval_count': 100} for level in ('global', 'direction', 'candidate')},
            'reservation': {'token': 5, 'node': 0, 'eval_count': 1},
            'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
                                      'operator': {'token': 10, 'node': 1, 'eval_count': 0}},
            'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}}
    return value


def build(path, *, profile=None, llm=None, domain=None, generations=3, stop=None, resume=False, registry=None):
    return Framework.from_profile(profile or assembly(), llm or Provider(), domain or Domain(),
        LoopConfig(max_generations=generations, stop_after_generation=stop, resume_from_checkpoint=resume,
                   total_budget=100000, intent_cost=2000, reeval_floor=0), str(path),
        component_registry=registry or default_registry())


def rows(fw, kind):
    return [row['payload'] for row in fw.store.read(kind)]


def assert_accounting(fw, provider, domain):
    crossovers = sum(prompt.startswith('[composed-crossover') for prompt in provider.prompts)
    expected_tokens = 5 * (provider.calls - crossovers) + 7 * crossovers + 2 * len(domain.calls)
    state = fw._composed.budget.state()
    assert state['global']['used'] == {'token': expected_tokens, 'node': provider.calls, 'eval_count': len(domain.calls)}
    assert not state['open_intents']
    assert sum(scope['used']['token'] for scope in state['directions'].values()) == expected_tokens


def test_framework_two_parent_crossover_retains_gate_rejected_valid_parents_and_one_authoritative_dag(tmp_path):
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, llm=provider, domain=domain)
    result = fw.evolve(TASK)
    frontier = fw._composed.frontier
    assert isinstance(frontier, PopulationFrontier)
    records = rows(fw, 'composed_evidence')
    ids = [record['proposal']['candidate']['id'] for record in records]
    assert [record['proposal']['candidate']['operator'] for record in records] == ['draft', 'draft', 'crossover', 'crossover']
    assert records[0]['proposal']['candidate']['parents'] == records[1]['proposal']['candidate']['parents'] == []
    assert set(records[2]['proposal']['candidate']['parents']) == set(ids[:2])
    assert [record['decision']['admit'] for record in rows(fw, 'composed_decision')] == [True, False, False, True]
    assert records[1]['evidence']['eval_result']['status'] == 'ok'
    assert ids[1] not in frontier.member_ids and ids[1] in frontier.nodes
    assert frontier.nodes[ids[2]].parent_ids == records[2]['proposal']['candidate']['parents']
    assert frontier.nodes[ids[3]].depth == 2 and frontier.nodes[ids[2]].status == 'done'
    assert frontier.protected_id == result['best_candidate_id'] == ids[3]
    assert result['population']['members'] == list(frontier.member_ids) and len(frontier.member_ids) == 2
    assert result['reporting']['gate_selected']['candidate_id'] == ids[3]
    assert result['reporting']['final_audit']['evidence']['candidate_id'] == ids[3]
    assert result['best_prompt'] == records[3]['proposal']['artifact']
    assert 'ROOT-1' in records[2]['proposal']['artifact'] and 'ROOT-2' in records[2]['proposal']['artifact']
    assert_accounting(fw, provider, domain)
    assert fw.replay()['replay_certificate']['passed']


def test_both_parent_lessons_and_context_identity_reach_real_crossover_without_held_out_payloads(tmp_path):
    provider = Provider(); fw = build(tmp_path, llm=provider, generations=2)
    fw.evolve(TASK)
    crossover = provider.prompts[2]
    assert 'lesson:0' in crossover and 'lesson:1' in crossover
    assert 'PRIVATE_POPULATION_CANARY' not in repr(provider.prompts)
    assert 'HELD_OUT_POPULATION_CANARY' not in repr(provider.prompts)
    pack = rows(fw, 'composed_context')[2]
    proposal = rows(fw, 'composed_evidence')[2]['proposal']
    assert proposal['candidate']['context_pack_ref'] == pack['context_ref']
    assert len(pack['context']['memory']) == 2
    assert len(fw._composed.memory.entries) == 3


@pytest.mark.parametrize('pressure', ['uniform', 'tournament', 'softmax'])
def test_configured_sampling_pressure_commits_real_parent_draws_and_rng_to_authoritative_state(tmp_path, pressure):
    profile = assembly(capacity=4, selection=pressure)
    profile['frontier']['options'].update(tournament_size=4, temperature=0.001)
    fw = build(tmp_path, profile=profile, domain=Domain(gate_scores=(10, 9, 8, 7, 6)), generations=4)
    result = fw.evolve(TASK)
    receipts = [receipt for row in rows(fw, 'population_sampling_committed') for receipt in row['receipts']]
    proposals = rows(fw, 'composed_evidence')[2:]
    assert len(receipts) == 3 and all(receipt['strategy'] == pressure for receipt in receipts)
    assert [row['proposal']['candidate']['parents'] for row in proposals] == [receipt['selected'] for receipt in receipts]
    assert result['population']['rng_state'] == receipts[-1]['after']
    assert result['population']['rng_state']['calls'] == 3
    assert result['best_candidate_id'] in result['population']['members']
    assert fw.replay()['replay_certificate']['passed']


def test_uniform_and_cold_softmax_produce_different_actual_crossovers_under_identical_scores(tmp_path):
    outputs = []
    for pressure in ('uniform', 'softmax'):
        profile = assembly(capacity=4, selection=pressure)
        profile['frontier']['options']['temperature'] = 0.001
        fw = build(tmp_path / pressure, profile=profile, domain=Domain(gate_scores=(10, 9, 8, 7, 6)), generations=4)
        fw.evolve(TASK)
        outputs.append([row['proposal']['candidate']['parents'] for row in rows(fw, 'composed_evidence')[3:]])
    assert outputs[0] != outputs[1]


@pytest.mark.parametrize('failure', ['evaluation', 'operator'])
def test_failed_candidates_never_enter_population_and_known_cost_stays_charged(tmp_path, failure):
    provider = Provider(fail_crossover=failure == 'operator')
    domain = Domain(failed_cycle=2 if failure == 'evaluation' else None)
    fw = build(tmp_path, llm=provider, domain=domain, generations=3)
    fw.evolve(TASK)
    records = rows(fw, 'composed_evidence'); failed = records[2]['proposal']['candidate']['id']
    assert records[2]['evidence']['eval_result']['status'] == 'failed_to_run'
    assert failed not in fw._composed.frontier.member_ids
    assert failed not in records[3]['proposal']['candidate']['parents']
    assert fw._composed.frontier.nodes[failed].status == 'pruned'
    assert_accounting(fw, provider, domain)


def test_population_works_with_scalar_budget_without_a_parallel_legacy_archive(tmp_path):
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, profile=assembly(scalar=True), llm=provider, domain=domain, generations=2)
    result = fw.evolve(TASK)
    assert len(rows(fw, 'population_finalized')) == 3
    assert result['population']['nodes'] == 3 and isinstance(fw._composed.frontier, PopulationFrontier)
    assert result['population']['protected_id'] == result['best_candidate_id']
    assert fw.replay()['replay_certificate']['passed']


@pytest.mark.parametrize('fault', ['capacity', 'operators', 'metric', 'different_rungs'])
def test_invalid_population_composition_fails_before_any_provider_or_evaluation_call(tmp_path, fault):
    profile = assembly()
    if fault == 'capacity': profile['frontier']['options']['capacity'] = 1
    elif fault == 'operators': profile['operators'].reverse()
    elif fault == 'metric': profile['operators'][1]['options'] = {'metric': 'wrong/objective'}
    else: profile['budget']['options']['fidelity_rungs'].append({'fidelity': 'high', 'split_id': 'dev'})
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, profile=profile, llm=provider, domain=domain)
    with pytest.raises(ValueError, match='population|crossover|ordered|comparable'):
        fw.evolve(TASK)
    assert provider.calls == 0 and domain.calls == [] and not fw.store.path.exists()


def test_policy_cannot_bypass_sampling_receipts_or_advance_rng_for_an_invalid_return(tmp_path):
    class UnrecordedPolicy(PopulationPolicy):
        async def select(self, frontier, budget):
            ids = frontier.eligible_parent_ids()
            return list(ids[:2]) if len(ids) >= 2 else []
    registry = default_registry()
    registry.register('policy', 'unrecorded', lambda context, options: UnrecordedPolicy(context.scope_context))
    profile = assembly(); profile['policy'] = {'name': 'unrecorded'}
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, profile=profile, llm=provider, domain=domain, registry=registry)
    with pytest.raises(ValueError, match='sampling receipt'):
        fw.evolve(TASK)
    assert provider.calls == 2 and fw._composed.frontier.rng_state == {'counter': 0, 'calls': 0}
    assert not rows(fw, 'population_sampling_committed')


def test_cycle_boundary_resume_preserves_population_members_lineage_next_rng_and_replay(tmp_path):
    full = build(tmp_path / 'full'); expected = full.evolve(TASK)
    partial = build(tmp_path / 'resume', stop=2); partial.evolve(TASK)
    resumed = build(tmp_path / 'resume', resume=True); actual = resumed.evolve(TASK)
    for field in ('best_candidate_id', 'best_prompt', 'best_score', 'population', 'ledger', 'accepted_candidate_ids'):
        assert actual[field] == expected[field]
    assert resumed._composed.frontier._edge_payload() == full._composed.frontier._edge_payload()
    assert resumed.replay()['replay_certificate']['passed']
    assert resumed.replay()['replay_certificate']['passed']


@pytest.mark.parametrize('fault', ['members', 'incumbent', 'rng', 'lineage',
    'retained_status', 'rng_journal', 'rebound_parents'])
def test_rehashed_population_checkpoint_tampering_is_rejected_before_new_paid_work(tmp_path, fault):
    fw = build(tmp_path, stop=2); fw.evolve(TASK)
    checkpoint = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    payload = json.loads(checkpoint['frontier_checkpoint'])['payload']
    if fault == 'members': payload['population']['members'] = []
    elif fault == 'incumbent': payload['population']['protected_id'] = None
    elif fault in {'rng', 'rng_journal'}:
        payload['population']['rng_state']['counter'] += 123
        if fault == 'rng_journal':
            transcript = [json.loads(line) for line in fw.store.path.read_text().splitlines()]
            event = next(row for row in reversed(transcript) if row['kind'] == 'population_sampling_committed')
            event['payload']['rng_state']['counter'] += 123
            fw.store.path.write_text(''.join(json.dumps(row) + '\n' for row in transcript))
    elif fault == 'retained_status':
        population = payload['population']
        node = next(node for node in payload['nodes'] if node['id'] in population['members']
                    and node['id'] != population['protected_id'])
        node.update(status='pruned', prune_reason='forged exclusion')
        eligible = sorted((node for node in payload['nodes'] if node['status'] in {'done', 'merged'}
                           and node['eval_status'] == 'ok'), key=lambda node: (-node['score'], node['created_cycle'], node['id']))
        retained = [population['protected_id']] + [node['id'] for node in eligible if node['id'] != population['protected_id']]
        population['members'] = sorted(retained[:payload['config']['capacity']])
    else:
        node = next(node for node in payload['nodes'] if len(node['parent_ids']) == 2)
        node['parent_ids'].reverse()
        if fault == 'rebound_parents':
            checkpoint['proposals'][node['id']]['candidate']['parents'].reverse()
    checkpoint['frontier_checkpoint'] = FrontierCheckpoint(1, payload, _digest(payload)).to_bytes().decode()
    RunCheckpoint.create(checkpoint).save(tmp_path / 'checkpoint.json')
    provider, domain = Provider(), Domain()
    before_resume = fw.store.path.read_bytes()
    resumed = build(tmp_path, llm=provider, domain=domain, resume=True)
    with pytest.raises((ValueError, RuntimeError), match='population|checkpoint|lineage|genealogy|RNG|durable|journal'):
        resumed.evolve(TASK)
    assert provider.calls == 0 and domain.calls == []
    assert fw.store.path.read_bytes() == before_resume




def test_named_population_profile_uses_public_framework_entry_point(tmp_path):
    from test_composed_runtime import CountingEvaluator
    provider = Provider()
    fw = Framework.from_profile('population_prompt', provider, CountingEvaluator(),
        LoopConfig(max_generations=2, total_budget=30000, intent_cost=2000, reeval_floor=0), str(tmp_path))
    result = fw.evolve(TASK)
    assert provider.calls == 3 and len(rows(fw, 'population_finalized')) == 3
    assert len(rows(fw, 'composed_evidence')[2]['proposal']['candidate']['parents']) == 2
    assert result['population']['capacity'] == 8
    assert fw.replay()['replay_certificate']['passed']




@pytest.mark.parametrize('extra', ['gpu_hours', 'usd'])
def test_local_population_policy_does_not_authorize_unmetered_crossover_resources(tmp_path, extra):
    profile = assembly()
    budget = profile['budget']['options']
    for value in budget['limits'].values():
        value[extra] = 10.0
    budget['reservation'][extra] = 1.0
    for value in budget['operation_reservations'].values():
        value[extra] = 0.0
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, profile=profile, llm=provider, domain=domain)
    with pytest.raises(ValueError, match='physical cost coverage'):
        fw.evolve(TASK)
    assert provider.calls == 0 and not domain.calls and not fw.store.path.exists()


# S7's durable operation protocol also owns S8's decision and RNG continuation.
from test_composed_worktree_framework import (LocalProvider, prepare as prepare_worktree,
    profile as worktree_profile, framework as worktree_framework, provider_calls, wait_pause)
from test_composed_worktree_executor import stop
from core.composition.worktree import WorktreeCommandExecutor


class CodePopulationProvider(LocalProvider):
    def __call__(self, prompt):
        result = super().__call__(prompt)
        if prompt.startswith('[composed-crossover'):
            parents = json.loads(prompt.split('PARENTS:\n', 1)[1].split('\nCONTEXT:', 1)[0])
            values = [float(parent['artifact'].split('=')[1]) for parent in parents]
            assert len(values) == 2
            return 'VALUE = ' + str(sum(values) / 2 + 0.2) + '\n'
        return result


def command_population_profile(root, *, delay=0.0, proxy=False):
    result = worktree_profile(root, delay=delay, proxy=proxy)
    population = population_profile(capacity=2, selection='uniform', sample_seed=17)
    for field in ('policy', 'operators', 'frontier'):
        result[field] = population[field]
    return result


def test_population_crossover_runs_in_real_git_worktrees_and_resumes_the_same_selection(tmp_path):
    prepare_worktree(tmp_path)
    profile = command_population_profile(tmp_path)
    fw = worktree_framework(tmp_path, provider=CodePopulationProvider(tmp_path), generations=2, assembly=profile)
    result = fw.evolve(TASK)
    assert result['population']['rng_state']['calls'] == 1
    assert result['ledger']['global']['used'] == {'token': 64, 'node': 3, 'eval_count': 7}
    records = rows(fw, 'composed_evidence')
    assert len(records[2]['proposal']['candidate']['parents']) == 2
    parents = [float(record['proposal']['artifact'].split('=')[1]) for record in records[:2]]
    assert float(records[2]['proposal']['artifact'].split('=')[1]) == sum(parents) / 2 + 0.2
    assert len(rows(fw, 'worktree_process_started')) == 7
    fresh = CodePopulationProvider(tmp_path)
    resumed = worktree_framework(tmp_path, provider=fresh, generations=2, resume=True, assembly=profile)
    assert resumed.evolve(TASK) == result and fresh.calls == 0


def _wait_population_operation(root, owner, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in (root / 'run' / 'worktree-operations').glob('*/operation.json'):
            record = json.loads(path.read_text())
            candidate = record['binding']['proposal']['candidate']
            if candidate['created_cycle'] == 2 and record['binding']['request']['split_id'] == 'dev' \
                    and (path.parent / 'target-authorized.json').exists():
                return path.parent, record
        if owner.poll() is not None:
            raise AssertionError('owner exited before crossover command: ' + owner.stderr.read()[-3000:])
        time.sleep(0.02)
    raise AssertionError('owner never launched crossover evaluation')


@pytest.mark.parametrize('pause', ['sampling', 'running', 'completed'])
def test_population_sigkill_continuation_commits_rng_once_without_repeating_paid_work(tmp_path, pause):
    prepare_worktree(tmp_path)
    owner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--population-owner', str(tmp_path), pause],
        env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if pause == 'running':
            directory, operation = _wait_population_operation(tmp_path, owner)
            target = json.loads((directory / 'target.json').read_text())
        else:
            wait_pause(tmp_path, owner, timeout=20)
        stop(owner)
        provider = CodePopulationProvider(tmp_path)
        profile = command_population_profile(tmp_path, delay=0.3)
        fw = worktree_framework(tmp_path, provider=provider, generations=2, resume=True, assembly=profile)
        result = fw.evolve(TASK)
        assert provider.calls == (1 if pause == 'sampling' else 0)
        assert len(provider_calls(tmp_path)) == 3
        assert result['ledger']['global']['used'] == {'token': 64, 'node': 3, 'eval_count': 7}
        assert not result['ledger']['open_intents']
        assert len(rows(fw, 'worktree_process_started')) == 7
        draws = rows(fw, 'population_sampling_committed')
        assert len(draws) == 1 and result['population']['rng_state'] == draws[0]['rng_state']
        assert result['population']['rng_state']['calls'] == 1
        assert rows(fw, 'composed_evidence')[2]['proposal']['candidate']['parents'] == draws[0]['receipts'][0]['selected']
        assert result['best_candidate_id'] == fw._composed.frontier.protected_id
        if pause == 'running':
            assert json.loads((directory / 'target.json').read_text()) == target
            assert json.loads((directory / 'operation.json').read_text()) == operation
        calls = len(provider_calls(tmp_path))
        fresh = CodePopulationProvider(tmp_path)
        complete = worktree_framework(tmp_path, provider=fresh, generations=2, resume=True, assembly=profile)
        assert complete.evolve(TASK) == result and fresh.calls == 0
        assert len(provider_calls(tmp_path)) == calls
    finally:
        stop(owner)


def _population_owner(root, pause):
    if pause == 'sampling':
        original = PopulationFrontier.commit_selection
        def pause_sampling(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if self.rng_state['calls'] == 1:
                (root / 'owner-paused').write_text('durable sampling receipt before provider invocation')
                time.sleep(60)
            return result
        PopulationFrontier.commit_selection = pause_sampling
    elif pause == 'completed':
        original = WorktreeCommandExecutor._complete
        def pause_completed(self, directory, recorded, *args):
            evidence = original(self, directory, recorded, *args)
            candidate = recorded['binding']['proposal']['candidate']
            if candidate['created_cycle'] == 2 and recorded['binding']['request']['split_id'] == 'dev':
                (root / 'owner-paused').write_text('completed crossover evaluation before settlement')
                time.sleep(60)
            return evidence
        WorktreeCommandExecutor._complete = pause_completed
    profile = command_population_profile(root, delay=0.3)
    worktree_framework(root, provider=CodePopulationProvider(root), generations=2, assembly=profile).evolve(TASK)


class FeedbackCodePopulationProvider(CodePopulationProvider):
    def __init__(self, root):
        super().__init__(root)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        artifact = super().__call__(prompt)
        if 'proxy_improved_true_regressed' in prompt:
            return 'VALUE = 0.95\n'
        return artifact


def test_population_proxy_calibration_and_worktree_share_receipts_memory_gate_and_physical_ledger(tmp_path):
    from test_composed_worktree_executor import git
    prepare_worktree(tmp_path)
    script = tmp_path / 'repo' / 'evaluate.py'
    code = script.read_text().replace("if mode=='sandbox':",
        "if request['request']['split_id']=='calibration' and 0.65 < value < 0.85: value=1-value\nif mode=='sandbox':")
    code = code.replace("'text_feedback':'local command'", "'text_feedback':('RAW_ANCHOR_CANARY' "
        "if request['request']['split_id']=='calibration' else 'HELDOUT_CANARY' "
        "if request['request']['split_id'] in ('admission','final_audit') else 'public development lesson')")
    script.write_text(code)
    git(tmp_path / 'repo', 'add', 'evaluate.py')
    git(tmp_path / 'repo', 'commit', '--quiet', '-m', 'independent calibration fixture')
    profile = command_population_profile(tmp_path, proxy=True)
    profile['memory']['options'] = {'context_scope': 'parents', 'include_negative': True, 'max_chars': 16000}
    provider = FeedbackCodePopulationProvider(tmp_path)
    fw = worktree_framework(tmp_path, provider=provider, generations=3, assembly=profile)
    result = fw.evolve(TASK)
    evidence = rows(fw, 'composed_evidence')
    assert [row['proposal']['candidate']['operator'] for row in evidence] == ['draft', 'draft', 'crossover', 'crossover']
    assert [row['decision']['admit'] for row in rows(fw, 'composed_decision')] == [True, True, False, True]
    assert result['proxy_validity']['mode'] == 'degraded'
    assert result['proxy_validity']['valid_pairs'] == 4
    assert result['reporting']['gate_calls'] == 3 and result['reporting']['final_audit']['calls'] == 1
    assert len(rows(fw, 'composed_anchor')) == 4
    assert len(rows(fw, 'worktree_process_started')) == 12
    assert result['ledger']['global']['used'] == {'token': 104, 'node': 4, 'eval_count': 12}
    assert not result['ledger']['open_intents'] and not any(result['ledger']['global']['reserved'].values())
    assert result['population']['rng_state']['calls'] == 2
    assert len(rows(fw, 'population_sampling_committed')) == 2
    assert all(len(row['proposal']['candidate']['parents']) == 2 for row in evidence[2:])
    assert 'proxy_improved_true_regressed' not in provider.prompts[2]
    assert 'proxy_improved_true_regressed' in provider.prompts[3]
    assert evidence[3]['proposal']['artifact'] == 'VALUE = 0.95\n'
    feedback = [entry for entry in rows(fw, 'composed_context')[3]['context']['memory'] if entry['negative']]
    assert feedback and 'proxy_improved_true_regressed' in json.dumps(feedback)
    assert all(canary not in repr(provider.prompts) for canary in ('PRIVATE_', 'RAW_ANCHOR_CANARY', 'HELDOUT_CANARY'))
    assert result['best_candidate_id'] == evidence[3]['proposal']['candidate']['id'] == fw._composed.frontier.protected_id
    fresh = FeedbackCodePopulationProvider(tmp_path)
    resumed = worktree_framework(tmp_path, provider=fresh, generations=3, resume=True, assembly=profile)
    assert resumed.evolve(TASK) == result and fresh.calls == 0


def test_gate_rejected_parent_owns_first_parent_direction_without_double_charging(tmp_path):
    profile = assembly(selection='greedy')
    fw = build(tmp_path, profile=profile, generations=2)
    result = fw.evolve(TASK)
    evidence = rows(fw, 'composed_evidence')
    rejected_id = evidence[1]['proposal']['candidate']['id']
    crossover_id = evidence[2]['proposal']['candidate']['id']
    assert not rows(fw, 'composed_decision')[1]['decision']['admit']
    assert evidence[2]['proposal']['candidate']['parents'][0] == rejected_id
    reservations = [row['data']['intent'] for row in rows(fw, 'hierarchical_budget') if row['event'] == 'reserve']
    crossover = [value for value in reservations if value['candidate']['id'] == crossover_id and value['operation'] != 'planning']
    assert {value['operation'] for value in crossover} == {'operator', 'dev', 'admission'}
    assert all(value['direction_id'] == rejected_id for value in crossover)
    assert sum(scope['used']['token'] for scope in result['ledger']['directions'].values()) == result['ledger']['global']['used']['token']


def test_valid_budget_abort_preserves_committed_sampling_on_repeated_unfunded_resume(tmp_path):
    profile = assembly()
    profile['admission'] = {'name': 'metric'}
    profile['budget']['options']['limits']['direction']['token'] = 12
    first = build(tmp_path, profile=profile, generations=2)
    original = first.evolve(TASK)
    assert original['cycles'] == 2 and original['population']['rng_state']['calls'] == 1
    assert len(rows(first, 'composed_cycle_aborted')) == 1
    for _ in range(2):
        provider, domain = Provider(), Domain()
        resumed = build(tmp_path, profile=profile, generations=2, resume=True, llm=provider, domain=domain)
        result = resumed.evolve(TASK)
        assert provider.calls == 0 and domain.calls == []
        assert result == original
        assert result['population']['rng_state']['calls'] == 1
        assert len(rows(resumed, 'composed_evidence')) == 2


def test_custom_tree_subclass_keeps_fresh_run_compatibility_without_claiming_portable_resume(tmp_path):
    from core.composition.defaults import composed_profile
    from core.frontier.research import ResearchFrontier
    class CustomTree(ResearchFrontier):
        pass
    registry = default_registry()
    registry.register('frontier', 'custom_tree', lambda context, options: CustomTree(store=context.store))
    profile = composed_profile()
    profile['domain'] = {'name': 'native'}
    profile['frontier'] = {'name': 'custom_tree'}
    provider = Provider()
    fw = build(tmp_path, profile=profile, registry=registry, llm=provider, generations=1)
    result = fw.evolve(TASK)
    assert provider.calls == result['cycles'] == 2 and 'population' not in result
    records = rows(fw, 'composed_evidence')
    assert records[1]['proposal']['candidate']['parents'] == [records[0]['proposal']['candidate']['id']]
    before = fw.store.path.read_bytes()
    fresh = Provider()
    resumed = build(tmp_path, profile=profile, registry=registry, llm=fresh, generations=1, resume=True)
    with pytest.raises(ValueError, match='portable restore'):
        resumed.evolve(TASK)
    assert fresh.calls == 0 and fw.store.path.read_bytes() == before


if __name__ == '__main__' and sys.argv[1] == '--population-owner':
    _population_owner(Path(sys.argv[2]), sys.argv[3])
