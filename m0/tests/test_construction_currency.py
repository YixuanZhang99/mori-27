"""Configured construction with real loopback transport and temporary CNY authority."""
import copy
import json
from pathlib import Path

import pytest

from core.loop import Framework
from core.llm import UsageError
from test_configured_construction import profile as construction_profile, records
from test_governed_cny_framework import (BOUND, CountedProvider, IntegerDomain, TASK,
    campaign_fixture, framework as legacy_framework)
from test_governed_cny_provider import local_endpoint, reply


def build(path, campaign, endpoint, *, cap=2, attempts=2, pause=None, resume=False,
          frozen=False, git=False, tokens=10000000, worktree=None):
    template, _ = legacy_framework(path, campaign, endpoint, pause=pause, resume=resume, tokens=tokens, worktree=worktree)
    assembly = template._composed.assembly.to_dict()
    execution = construction_profile(frozen=frozen)['execution']
    execution['constructor']['options']['max_attempts'] = attempts
    assembly.update(schema_version=2, execution=execution)
    assembly['budget']['options']['operation_reservations']['operator']['token'] = BOUND * cap
    assembly['governance']['controls']['reservations']['operator']['token'] = BOUND * cap
    assembly['governance']['controls']['provider'] = {'name': 'construction-cny'}
    if git:
        assembly['executor'] = {'name': 'git_artifact', 'options': {}}
    if worktree is not None:
        assembly['executor']['name'] = 'git_artifact'
        assembly['executor']['options'].pop('run_root')
    sessions = []
    def fresh():
        raw = CountedProvider('deepseek-flash', endpoint.url,
            campaign_binding=campaign.manifest_binding(), max_completion_tokens=4,
            timeout=2, api_key='fixture-only-secret',
            phase_call_limits={'operator': cap, 'evaluation': 0})
        sessions.append(raw)
        return raw
    main = fresh()
    registry = template._composed.registry
    registry.register('provider', 'construction-cny', lambda ctx, opts: fresh(),
                      governance=main.governance_binding())
    fw = Framework.from_profile(assembly, main, IntegerDomain() if worktree is None else None, template._composed.cfg,
                                str(path), component_registry=registry)
    return fw, sessions


def answer(content=None, **changes):
    return reply(choices=[{'finish_reason': 'stop', 'message': {'content': content or
        json.dumps({'artifact': 'candidate_value=73', 'hypothesis': 'Fixture hypothesis'})}}], **changes)


@pytest.mark.parametrize('git', [False, True])
def test_public_construction_currency_binds_artifacts_and_replays_without_http(tmp_path, local_endpoint, monkeypatch, git):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, sessions = build(tmp_path / 'run', campaign, local_endpoint, git=git)
    result = fw.evolve(TASK)
    assert result['runtime'] == 'composed-v9-m7-governed-external'
    assert len(local_endpoint.requests) == 4
    assert [p.http_attempts for p in sessions] == [2, 1, 1]
    assert len(records(fw, 'materialization_completed')) == 4
    snapshot = campaign.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == 152
    assert snapshot['pending_calls'] == []
    bridge = fw._composed.governed.external
    bundle = bridge.replay_bundle()
    binding = bundle['preparation']['run']['construction']
    assert binding['envelope'] == 'candidate_production_v1'
    assert binding['execution'] == fw._composed.assembly.execution.to_dict()
    assert set(binding['controls']) == {'control-0000', 'control-0001'}
    audit = bridge.audit()['construction']
    assert audit['materializations'] == 4
    assert audit['provider_calls'] == 4
    assert len(audit['artifact_links']) == 4
    assert {v['materialization_ref'] for v in audit['artifact_links']} == {
        ref['materialization_ref'] for report in [result['execution']['main'], *result['execution']['controls'].values()]
        for ref in report['artifacts'].values()}
    for row in records(fw, 'composed_provider_started'):
        assert row['invocation']['external_context']['runtime_id'] == result['runtime']
    def forbidden(*args, **kwargs):
        raise AssertionError('replay performed HTTP')
    monkeypatch.setattr(CountedProvider, 'perform_request', forbidden)
    replay = fw.replay(TASK)
    assert replay['replay_certificate']['passed']
    assert replay['ledger'] == result['ledger']
    assert campaign.snapshot() == snapshot
    assert len(local_endpoint.requests) == 4


def test_build_and_repair_share_one_intent_continuous_ordinals_and_cost(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend([answer('invalid construction JSON'), answer()] * 4)
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint)
    fw.evolve(TASK)
    assert len(local_endpoint.requests) == 8
    operations = campaign.snapshot()['operations']
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 304
    assert [op['ordinal'] for op in operations] == [0, 1] * 4
    starts = records(fw, 'composed_provider_started')
    for first, second in zip(starts[::2], starts[1::2]):
        a, b = first['invocation'], second['invocation']
        assert a['intent_id'] == b['intent_id']
        assert a['external_context']['ordinal'] == 0 and b['external_context']['ordinal'] == 1
    totals = fw.inspect()['governance']['budget']['physical_totals']
    assert totals == {'token': 56, 'node': 4, 'eval_count': 4}
    assert fw._composed.governed.external.audit()['construction']['provider_calls'] == 8


def test_known_first_unknown_repair_retains_whole_physical_reserve(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend([answer('invalid JSON'), answer(usage=None)])
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    before = campaign.snapshot()
    assert len(local_endpoint.requests) == 2
    assert before['settled_upper_bound_micro_cny'] == 38
    assert len(before['pending_calls']) == 1
    assert before['operations'][0]['usage']['total_tokens'] == 7
    assert 'usage' not in before['operations'][1]
    assert records(fw, 'construction_outcome') == []
    assert records(fw, 'materialization_completed') == []
    physical = fw._composed.budget._rebuild()[0]['operations']
    unresolved = [v for v in physical.values() if v['intent']['operation'] == 'operator']
    assert len(unresolved) == 1
    assert unresolved[0]['status'] == 'unresolved'
    assert 'actual_costs' not in unresolved[0]
    assert unresolved[0]['intent']['amounts']['token'] == 2 * BOUND
    journal = Path(fw.store.path).read_bytes()
    resumed, _ = build(tmp_path / 'run', campaign, local_endpoint, resume=True)
    with pytest.raises((UsageError, ValueError)):
        resumed.evolve(TASK)
    assert len(local_endpoint.requests) == 2
    assert campaign.snapshot() == before
    assert Path(fw.store.path).read_bytes() == journal


def test_frozen_hypothesis_rejection_is_charged_without_materialization(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint, frozen=True)
    fw.evolve(TASK)
    assert len(local_endpoint.requests) == 4
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    assert records(fw, 'materialization_completed') == []
    assert fw.inspect()['governance']['budget']['physical_totals'] == {'token': 28, 'node': 4, 'eval_count': 0}
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 4


def test_one_call_cap_prevents_repair_without_spending_future_controls(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer('invalid JSON') for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint, cap=1, attempts=3)
    fw.evolve(TASK)
    assert len(local_endpoint.requests) == 3
    ops = campaign.snapshot()['operations']
    assert [v['ordinal'] for v in ops] == [0] * 3
    assert [v['lane'] for v in ops] == ['control', 'main', 'control']
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 114
    assert campaign.snapshot()['protected_micro_cny'] == 0
    assert records(fw, 'materialization_completed') == []


def test_main_capacity_exhaustion_preserves_all_future_control_calls(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend([answer('invalid JSON'), answer()] * 2)
    fw, sessions = build(tmp_path / 'run', campaign, local_endpoint, tokens=4 * BOUND)
    fw.evolve(TASK)
    assert [v.http_attempts for v in sessions] == [0, 2, 2]
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    assert fw.inspect()['governance']['completed'] == 2


def test_paused_construction_keeps_original_currency_plan_and_completed_control(tmp_path, local_endpoint):
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint, pause=0)
    fw.evolve(TASK)
    first = fw._composed.governed.external.replay_bundle()['preparation']
    resumed, providers = build(tmp_path / 'run', campaign, local_endpoint, resume=True)
    resumed.evolve(TASK)
    assert len(local_endpoint.requests) == 4
    assert [p.http_attempts for p in providers] == [1, 0, 1]
    assert resumed._composed.governed.external.replay_bundle()['preparation'] == first
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    assert resumed.replay(TASK)['replay_certificate']['passed']


@pytest.mark.parametrize('boundary', ['composed_provider_completed', 'construction_outcome',
                                     'materialization_completed', 'worktree_artifact_commit'])
def test_actual_sigkill_adopts_original_paid_construction(tmp_path, local_endpoint, boundary):
    import os
    import signal
    import subprocess
    import sys
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    script = '''import os, signal, sys
from pathlib import Path
from types import SimpleNamespace
from test_construction_currency import build, TASK
from core.composition.recovery import ContinuationStore
from zoo.mle_bench_lite.cny_budget import CampaignBudget
write = ContinuationStore._write
def cut(self, record):
    result = write(self, record)
    if record["kind"] == sys.argv[4]:
        os.kill(os.getpid(), signal.SIGKILL)
    return result
ContinuationStore._write = cut
fw, _ = build(Path(sys.argv[1]), CampaignBudget(sys.argv[2]), SimpleNamespace(url=sys.argv[3]), git=True)
fw.evolve(TASK)
'''
    source = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(source), str(source / 'tests'))), PYTHONDONTWRITEBYTECODE='1')
    killed = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'run'), str(campaign.path),
        local_endpoint.url, boundary], env=env, capture_output=True, text=True, timeout=25)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    assert len(local_endpoint.requests) == 1
    resumed, sessions = build(tmp_path / 'run', campaign, local_endpoint, resume=True, git=True)
    resumed.evolve(TASK)
    assert [p.http_attempts for p in sessions] == [2, 0, 1]
    assert len(local_endpoint.requests) == 4
    assert len(records(resumed, 'materialization_completed')) == 4
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    assert campaign.snapshot()['pending_calls'] == []
    assert resumed.replay(TASK)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 4


def test_replay_rejects_changed_frozen_construction_binding(tmp_path, local_endpoint):
    from core.composition.external_provider import ExternalConstructionRunContext
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint)
    fw.evolve(TASK)
    bridge = fw._composed.governed.external
    run = bridge._run
    changed = run.to_dict()
    changed.update(mode='recorded', recorded_bundle=bridge.replay_bundle())
    changed['recorded_bundle']['preparation']['run']['construction']['execution']['spec']['role'] = 'coder'
    context = ExternalConstructionRunContext(**changed, store=run.store,
        physical_identity_lookup=run.physical_identity_lookup, provider_sessions=dict(run.provider_sessions))
    before = campaign.snapshot()
    with pytest.raises(ValueError, match='identity changed'):
        CNYInvocationBridge(None).bind_run(context)
    assert campaign.snapshot() == before
    assert len(local_endpoint.requests) == 4


def test_audit_rejects_self_consistent_replacement_role_definition(tmp_path, local_endpoint):
    from core.composition.construction_audit import audit_construction
    from core.x1.checkpoint import payload_digest
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint)
    fw.evolve(TASK)
    bridge = fw._composed.governed.external
    rows = copy.deepcopy(bridge._root_rows())
    terminal = next(row['payload'] for row in rows if row['kind'] == 'construction_outcome')
    terminal['outcome']['result']['role']['instructions'] = 'Substituted unauthorized role definition'
    artifact = next(row['payload'] for row in rows if row['kind'] == 'materialization_completed')
    artifact['construction_result'] = copy.deepcopy(terminal['outcome']['result'])
    artifact['outcome_ref'] = 'sha256:' + payload_digest(terminal)
    # Stop before evaluation so its independent old materialization hash cannot be the reason for rejection.
    cut = next(i for i, row in enumerate(rows) if row['kind'] == 'materialization_completed')
    with pytest.raises(ValueError, match='role|contract|prompt'):
        audit_construction(rows[:cut + 1], bridge._run.construction, logical_run_id=bridge._run.logical_run_id,
            provider_arguments={payload_digest(r['prepared']['context']):
                json.loads(r['prepared']['wire_body'])['messages'][0]['content'] for r in bridge._records()})


@pytest.mark.parametrize('field,replacement', [('projection_ref', 'sha256:' + '0' * 64),
                                               ('initial_hypothesis', 'Substituted hypothesis'),
                                               ('artifact', 'candidate_value=1')])
def test_audit_rejects_self_consistent_result_detached_from_paid_prompt(tmp_path, local_endpoint, field, replacement):
    from core.composition.construction_audit import audit_construction
    from core.x1.checkpoint import payload_digest
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint)
    fw.evolve(TASK)
    bridge = fw._composed.governed.external
    rows = copy.deepcopy(bridge._root_rows())
    terminal = next(row['payload'] for row in rows if row['kind'] == 'construction_outcome')
    terminal['outcome']['result'][field] = replacement
    artifact = next(row['payload'] for row in rows if row['kind'] == 'materialization_completed')
    artifact['construction_result'] = copy.deepcopy(terminal['outcome']['result'])
    artifact['outcome_ref'] = 'sha256:' + payload_digest(terminal)
    if field == 'artifact':
        import hashlib
        artifact['artifact'].update(reference='sha256:' + hashlib.sha256(replacement.encode()).hexdigest(),
                                    size_bytes=len(replacement.encode()))
    cut = next(i for i, row in enumerate(rows) if row['kind'] == 'materialization_completed')
    with pytest.raises(ValueError, match='prompt|plan|projection'):
        audit_construction(rows[:cut + 1], bridge._run.construction, logical_run_id=bridge._run.logical_run_id,
            provider_arguments={payload_digest(r['prepared']['context']):
                json.loads(r['prepared']['wire_body'])['messages'][0]['content'] for r in bridge._records()})


def test_standalone_loopback_example_runs_construct_repair_resume_and_replay(tmp_path, capsys):
    from examples.governed_cny_offline import main
    assert main(['--construction', '--workdir', str(tmp_path / 'example')]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['runtime'] == 'composed-v9-m7-governed-external'
    assert report['loopback_http_requests'] == 8
    assert report['fixture_settled_micro_cny'] == 304
    assert report['construction_artifacts'] == 4
    assert report['recorded_replay_passed']
    assert report['external_model_requests'] == 0



def test_command_evaluation_reuses_currency_bound_git_artifacts(tmp_path, local_endpoint, monkeypatch):
    import subprocess
    from test_composed_worktree_framework import prepare, TASK as COMMAND_TASK
    from test_composed_worktree_executor import git
    prepare(tmp_path)
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer(json.dumps({'artifact': 'VALUE = 0.5\n',
        'hypothesis': 'Fixture hypothesis'})) for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint, worktree=tmp_path)
    result = fw.evolve(COMMAND_TASK)
    assert result['runtime'] == 'composed-v9-m7-governed-external'
    assert fw.inspect()['governance']['completed'] == 2
    artifacts = records(fw, 'materialization_completed')
    assert len(artifacts) == len(local_endpoint.requests) == 4
    for artifact in artifacts:
        assert git(tmp_path / 'repo', 'show', artifact['artifact']['commit'] + ':candidate.py') == 'VALUE = 0.5'
    before = campaign.snapshot()
    assert before['settled_upper_bound_micro_cny'] == 152
    popen = subprocess.Popen
    def forbidden_command(args, *rest, **kwargs):
        if isinstance(args, (list, tuple)) and any(str(a).endswith('/command_worker.py') for a in args):
            raise AssertionError('recorded replay started command worker')
        return popen(args, *rest, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', forbidden_command)
    assert fw.replay(COMMAND_TASK)['replay_certificate']['passed']
    assert campaign.snapshot() == before
    assert len(local_endpoint.requests) == 4


def test_external_audit_rejects_funsearch_recipe_without_frozen_policy(tmp_path, local_endpoint, monkeypatch):
    import core.composition.construction_audit as audit_module
    from core.x1.checkpoint import payload_digest
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend(answer() for _ in range(4))
    fw, _ = build(tmp_path / 'run', campaign, local_endpoint)
    fw.evolve(TASK)
    bridge = fw._composed.governed.external
    rows = copy.deepcopy(bridge._root_rows())
    arguments = {payload_digest(r['prepared']['context']):
                 json.loads(r['prepared']['wire_body'])['messages'][0]['content'] for r in bridge._records()}
    monkeypatch.setattr(audit_module, '_prompt_request', lambda *_args: {'recipe': {'kind': 'funsearch'}})
    with pytest.raises(ValueError, match='frozen FunSearch policy'):
        audit_module.audit_construction(rows, bridge._run.construction,
            logical_run_id=bridge._run.logical_run_id, provider_arguments=arguments)
