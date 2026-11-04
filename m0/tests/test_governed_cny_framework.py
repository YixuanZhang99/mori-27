"""Public governed CNY integration: temporary authority and loopback HTTP only."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
from pathlib import Path

import pytest

from core.budget.ledger import BudgetError
from core.composition.defaults import composed_profile, default_registry
from core.llm import UsageError
from core.loop import Framework, LoopConfig
from examples.governed_controls import IntegerDomain, TASK
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
from test_governed_cny_provider import local_endpoint, reply

BOUND = 1048580  # Frozen service input capacity 1,048,576 + output allowance 4.


class CountedProvider(GovernedCNYProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_attempts = 0

    def perform_request(self, body):
        self.http_attempts += 1
        return super().perform_request(body)


def campaign_fixture(path):
    campaign = CampaignBudget.create(path / 'campaign.db', limit_micro_cny=200000000)
    campaign.enable_governance(expected_policy_sha256=campaign.manifest_binding()['policy_sha256'],
                               expected_head=campaign.snapshot()['journal_head'])
    return campaign


def framework(path, campaign, endpoint, *, pause=None, resume=False, tokens=10000000, worktree=None):
    bridge_type = importlib.import_module('zoo.mle_bench_lite.governed_currency').CNYInvocationBridge
    registry = default_registry()
    registry.install_external_bridge('cny_invocation_v1', lambda: bridge_type(campaign))
    sessions = []
    frozen_campaign = campaign.manifest_binding()
    def fresh():
        value = CountedProvider('deepseek-flash', endpoint.url,
            campaign_binding=frozen_campaign, max_completion_tokens=4,
            timeout=2, api_key='fixture-only-secret')
        sessions.append(value)
        return value
    main = fresh()
    registry.register('provider', 'governed-cny-fixture', lambda ctx, opts: fresh(),
                      governance=main.governance_binding())
    registry.register('domain', 'integer-fixture', lambda ctx, opts: IntegerDomain(),
                      governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    profile = composed_profile(name='governed-cny-loopback-fixture')
    profile['domain'] = {'name': 'native'}
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {'global': {'token': tokens, 'node': 20, 'eval_count': 20},
                   'direction': {'token': 10000000, 'node': 20, 'eval_count': 20},
                   'candidate': {'token': 10000000, 'node': 20, 'eval_count': 20}},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {
            'planning': {'token': 0, 'node': 0, 'eval_count': 0},
            'operator': {'token': BOUND, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [1]}]}}
    profile['governance'] = {'schema_version': 1, 'controls': {
        'after_main_cycles': [0, 2], 'seed': 7,
        'provider': {'name': 'governed-cny-fixture'},
        'domain': {'name': 'integer-fixture'},
        'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [1]},
        'reservations': {'operator': {'token': BOUND, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 1}}}}
    if worktree is not None:
        from test_composed_worktree_framework import profile as worktree_profile
        command = worktree_profile(worktree, layered=False)
        profile['domain'] = command['domain']
        profile['executor'] = command['executor']
        profile['budget']['options']['reservation']['token'] = 7
        profile['governance']['controls']['domain'] = copy.deepcopy(command['domain'])
        profile['governance']['controls']['reservations']['evaluation']['token'] = 7
    config = LoopConfig(max_generations=1, total_budget=tokens, reeval_floor=0,
                        stop_after_generation=pause, resume_from_checkpoint=resume)
    fw = Framework.from_profile(profile, main, IntegerDomain() if worktree is None else None, config, str(path),
                                component_registry=registry)
    return fw, sessions


def answers(endpoint, count):
    endpoint.responses.extend(reply(choices=[{'finish_reason': 'stop',
        'message': {'content': 'candidate_value=73'}}]) for _ in range(count))


def test_public_framework_protects_and_links_all_main_control_calls(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    answers(local_endpoint, 4)
    fw, sessions = framework(tmp_path / 'run', campaign, local_endpoint)
    result = fw.evolve(TASK)
    assert result['runtime'] == 'composed-v8-governed-external'
    report = fw.inspect()['governance']
    assert report['planned'] == report['completed'] == 2
    assert report['failed'] == report['pending'] == report['unresolved'] == 0
    assert report['budget']['accounts']['control'] == {'token': 14, 'node': 2, 'eval_count': 2}
    assert report['budget']['reconciled'] is True
    assert len(sessions) == len({id(value) for value in sessions}) == 3
    assert [value.http_attempts for value in sessions] == [2, 1, 1]
    snapshot = campaign.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == 152
    assert snapshot['pending_calls'] == []
    assert snapshot['protected_micro_cny'] == 0
    operations = snapshot['operations']
    assert len(operations) == len(local_endpoint.requests) == 4
    assert len({value['call_id'] for value in operations}) == 4
    assert len({value['run_id'] for value in operations}) == 1
    assert [value['lane'] for value in operations] == ['control', 'main', 'main', 'control']
    assert [value['slot_id'] for value in operations] == ['control-0000', None, None, 'control-0001']
    for operation, body in zip(operations, local_endpoint.requests):
        assert operation['request_sha256'] == hashlib.sha256(body).hexdigest()
        assert operation['kind'] == 'governed_reserve'
        assert operation['phase'] == 'operator'
        assert operation['ordinal'] == 0
        assert operation['usage'] == {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}
        assert operation['upper_bound_micro_cny'] == 38
        assert operation['bound_violation'] is False
    starts = list(fw.store.read('composed_provider_started'))
    assert len(starts) == 4
    for row, operation in zip(starts, operations):
        invocation = row['payload']['invocation']
        context = invocation['external_context']
        assert invocation['schema_version'] == 2
        assert context['lane'] == operation['lane']
        assert context['slot_id'] == operation['slot_id']
        assert context['currency_run_id'] == operation['run_id']
        assert context['phase'] == operation['phase']
        assert context['ordinal'] == operation['ordinal']
        assert context['intent_id'] == invocation['intent_id']
        assert context['physical_fingerprint'] == invocation['fingerprint']
        if context['lane'] == 'control':
            assert context['account'] == 'control'
        else:
            assert context['account'] in {'explore', 'exploit'}
        encoded = json.dumps({'schema_version': 1, 'context': context,
            'wire_request_sha256': operation['request_sha256']}, sort_keys=True,
            ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        assert hashlib.sha256(encoded).hexdigest() == operation['call_id']
    control_ids = {row['payload']['candidate_id'] for row in fw.store.read('governed_control_terminal')}
    assert result['best_candidate_id'] not in control_ids
    assert not control_ids.intersection(fw._composed.frontier.nodes)


def test_public_pause_resume_and_replay_never_repeat_http_or_currency_events(tmp_path, local_endpoint, monkeypatch):
    campaign = campaign_fixture(tmp_path)
    answers(local_endpoint, 4)
    workdir = tmp_path / 'run'
    paused, _ = framework(workdir, campaign, local_endpoint, pause=0)
    paused.evolve(TASK)
    assert len(local_endpoint.requests) == 2
    assert paused.inspect()['governance']['pending'] == 1
    paused_head = campaign.snapshot()['journal_head']
    resumed, sessions = framework(workdir, campaign, local_endpoint, resume=True)
    resumed.evolve(TASK)
    assert len(local_endpoint.requests) == 4
    assert [value.http_attempts for value in sessions] == [1, 0, 1]
    assert resumed.inspect()['governance']['completed'] == 2
    before = campaign.snapshot()
    assert before['journal_head'] != paused_head
    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay attempted HTTP')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    repeated, _ = framework(workdir, campaign, local_endpoint, resume=True)
    repeated.evolve(TASK)
    replay = repeated.replay(TASK)['replay_certificate']
    assert replay['passed'] is True
    assert replay['mode'] == 'recorded_outcomes'
    assert replay['external_calls'] == 0
    assert len(local_endpoint.requests) == 4
    assert campaign.snapshot() == before


def test_real_60000_token_limit_is_not_silently_expanded_for_capacity_mode(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    before = campaign.snapshot()
    with pytest.raises((ValueError, BudgetError, UsageError), match='capacity|budget|protect|bound'):
        fw, _ = framework(tmp_path / 'run', campaign, local_endpoint, tokens=60000)
        fw.evolve(TASK)
    assert local_endpoint.requests == []
    assert campaign.snapshot() == before


def test_known_output_bound_breach_is_charged_then_stops_both_lanes(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(reply(usage={
        'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 8}))
    fw, _ = framework(tmp_path / 'run', campaign, local_endpoint)
    with pytest.raises((ValueError, UsageError)):
        fw.evolve(TASK)
    snapshot = campaign.snapshot()
    assert len(local_endpoint.requests) == 1
    assert snapshot['settled_upper_bound_micro_cny'] == 46
    assert snapshot['pending_calls'] == []
    assert len(snapshot['operations']) == 1
    assert snapshot['operations'][0]['usage']['total_tokens'] == 8
    assert snapshot['operations'][0]['bound_violation'] is True
    assert fw._composed.budget.account_summary()['global']['used']['token'] == 8
    assert list(fw.store.read('governed_control_terminal')) == []


def test_unknown_transport_remains_pending_and_blocks_another_run(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append('disconnect')
    fw, _ = framework(tmp_path / 'run', campaign, local_endpoint)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    before = campaign.snapshot()
    assert len(local_endpoint.requests) == len(before['pending_calls']) == 1
    assert before['settled_upper_bound_micro_cny'] == 0
    assert before['operations'][0].get('usage') is None
    with pytest.raises((ValueError, UsageError, BudgetError)):
        another, _ = framework(tmp_path / 'another-run', campaign, local_endpoint)
        another.evolve(TASK)
    assert len(local_endpoint.requests) == 1
    assert campaign.snapshot() == before


def test_known_content_failure_remains_failed_control_while_others_drain(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': ''}}]))
    answers(local_endpoint, 3)
    fw, _ = framework(tmp_path / 'run', campaign, local_endpoint)
    fw.evolve(TASK)
    report = fw.inspect()['governance']
    assert report['planned'] == 2
    assert report['completed'] == report['failed'] == 1
    assert report['pending'] == report['unresolved'] == 0
    assert report['budget']['accounts']['control'] == {'token': 14, 'node': 2, 'eval_count': 1}
    assert len(local_endpoint.requests) == 4
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    terminals = [row['payload'] for row in fw.store.read('governed_control_terminal')]
    assert [(row['slot_id'], row['status']) for row in terminals] == [
        ('control-0000', 'failed'), ('control-0001', 'evaluated')]


def test_real_worktree_cny_calls_and_recorded_replay_use_no_new_http_or_command(tmp_path, local_endpoint, monkeypatch):
    from test_composed_worktree_framework import prepare, TASK as COMMAND_TASK
    from test_composed_worktree_executor import git
    prepare(tmp_path)
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(reply(choices=[{'finish_reason': 'stop',
        'message': {'content': 'VALUE = 0.5\n'}}]) for _ in range(4))
    fw, sessions = framework(tmp_path / 'run', campaign, local_endpoint, worktree=tmp_path)
    result = fw.evolve(COMMAND_TASK)
    assert result['runtime'] == 'composed-v8-governed-external'
    assert result['best_candidate_id']
    assert fw.inspect()['governance']['completed'] == 2
    assert [value.http_attempts for value in sessions] == [2, 1, 1]
    assert len(local_endpoint.requests) == 4
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    terminals = [row['payload'] for row in fw.store.read('governed_control_terminal')]
    for row in terminals:
        commit = row['evidence']['evidence']['branch_ref']
        assert git(tmp_path / 'repo', 'show', commit + ':candidate.py') == 'VALUE = 0.5'
        assert git(tmp_path / 'repo', 'show', commit + ':invocations.txt') == 'called'
    starts = list(fw.store.read('worktree_process_started'))
    assert len(starts) >= 4
    executed = {str(path.relative_to(tmp_path)): path.read_bytes()
                for pattern in ('**/target.json', '**/process-result.json') for path in tmp_path.glob(pattern)}
    assert executed
    currency_before = campaign.snapshot()
    popen = subprocess.Popen
    def forbid_command(args, *positional, **keywords):
        if isinstance(args, (list, tuple)) and any(str(arg).endswith('/command_worker.py') for arg in args):
            raise AssertionError('recorded replay attempted command execution')
        return popen(args, *positional, **keywords)
    def forbid_provider(*args, **kwargs):
        raise AssertionError('recorded replay attempted HTTP')
    monkeypatch.setattr(subprocess, 'Popen', forbid_command)
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbid_provider)
    replay = fw.replay(COMMAND_TASK)
    certificate = replay['replay_certificate']
    assert certificate['passed'] is True
    assert certificate['mode'] == 'recorded_outcomes'
    assert certificate['external_calls'] == 0
    assert certificate['receipt_chain_match'] and certificate['transcript_consumed']
    assert replay['ledger'] == result['ledger']
    assert len(local_endpoint.requests) == 4
    assert campaign.snapshot() == currency_before
    assert {str(path.relative_to(tmp_path)): path.read_bytes()
            for pattern in ('**/target.json', '**/process-result.json') for path in tmp_path.glob(pattern)} == executed


def test_framework_sigkill_after_response_before_currency_settlement_recovers_without_http_repeat(tmp_path, local_endpoint):
    import os
    import signal
    import sys
    campaign = campaign_fixture(tmp_path)
    answers(local_endpoint, 4)
    workdir = tmp_path / 'run'
    script = '''import os, signal, sys
from types import SimpleNamespace
from pathlib import Path
from test_governed_cny_framework import framework, TASK
from zoo.mle_bench_lite.cny_budget import CampaignBudget
original = CampaignBudget.settle
def die_before_settlement(self, *args, **kwargs):
    os.kill(os.getpid(), signal.SIGKILL)
CampaignBudget.settle = die_before_settlement
campaign = CampaignBudget(sys.argv[2])
fw, _ = framework(Path(sys.argv[1]), campaign, SimpleNamespace(url=sys.argv[3]))
fw.evolve(TASK)
'''
    source = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(source), str(source / 'tests')))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    child = subprocess.run([sys.executable, '-c', script, str(workdir), str(campaign.path),
                            local_endpoint.url], env=env, capture_output=True, text=True, timeout=20)
    assert child.returncode == -signal.SIGKILL, child.stderr
    assert len(local_endpoint.requests) == 1
    pending = campaign.snapshot()
    assert len(pending['pending_calls']) == 1
    assert pending['settled_upper_bound_micro_cny'] == 0
    responses = list((workdir / '.governed-cny').glob('call-*.response.json'))
    assert len(responses) == 1
    assert json.loads(responses[0].read_text())['payload']['usage']['total_tokens'] == 7
    resumed, sessions = framework(workdir, campaign, local_endpoint, resume=True)
    resumed.evolve(TASK)
    assert [provider.http_attempts for provider in sessions] == [2, 0, 1]
    assert len(local_endpoint.requests) == 4
    assert resumed.inspect()['governance']['completed'] == 2
    complete = campaign.snapshot()
    assert complete['pending_calls'] == []
    assert complete['settled_upper_bound_micro_cny'] == 152
    assert len(complete['operations']) == 4
