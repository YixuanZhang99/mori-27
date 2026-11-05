"""Resident controls use the same public Framework and real command backend."""
from __future__ import annotations

import copy
from pathlib import Path
import subprocess

import pytest

from core.composition.defaults import default_registry
from core.loop import Framework, LoopConfig
from core.composition.worktree import MeasuredCommandError
from test_composed_worktree_executor import git
from test_composed_worktree_framework import LocalProvider, TASK, prepare, profile
from test_governed_runtime import CAPABILITY


class BoundLocalProvider(LocalProvider):
    def __init__(self, root, *, fail_candidate=False):
        super().__init__(root)
        self.fail_candidate = fail_candidate

    def governance_binding(self):
        return copy.deepcopy(CAPABILITY)

    def __call__(self, prompt):
        artifact = super().__call__(prompt)
        return 'VALUE = -1\n' if self.fail_candidate else artifact


def governed_worktree(root, *, stop=None, resume=False, tokens=10000,
                      failed_slot=None, schedule=(0, 1, 2)):
    registry = default_registry()
    providers = []

    def fresh_provider(context, options):
        slot = context.invocation_scope['slot_id']
        path = root / 'provider-sessions' / slot
        path.mkdir(parents=True, exist_ok=True)
        provider = BoundLocalProvider(path, fail_candidate=slot == failed_slot)
        providers.append(provider)
        return provider

    registry.register('provider', 'worktree-control-fixture', fresh_provider,
                      governance=CAPABILITY)
    assembly = profile(root)
    assembly['budget']['options']['limits']['global']['token'] = tokens
    assembly['governance'] = {'schema_version': 1, 'controls': {
        'after_main_cycles': list(schedule), 'seed': 1,
        'provider': {'name': 'worktree-control-fixture'},
        'domain': copy.deepcopy(assembly['domain']),
        'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': None},
        'reservations': {
            'operator': {'token': 5, 'node': 1, 'eval_count': 0},
            'evaluation': {'token': 7, 'node': 0, 'eval_count': 1}}}}
    main = BoundLocalProvider(root)
    config = LoopConfig(max_generations=1, total_budget=100000, intent_cost=2000,
        reeval_floor=0, baseline_every=2, stop_after_generation=stop,
        resume_from_checkpoint=resume)
    framework = Framework.from_profile(assembly, main, None, config, str(root / 'run'),
                                       component_registry=registry)
    return framework, main, providers


def payloads(framework, kind):
    return [row['payload'] for row in framework.store.read(kind)]


def physical_execution_files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for pattern in ('**/provider-calls.jsonl', '**/target.json', '**/process-result.json')
            for path in root.glob(pattern)}


def test_resident_worktree_controls_interleave_and_reconcile_separate_artifacts(tmp_path):
    prepare(tmp_path)
    framework, main, providers = governed_worktree(tmp_path)
    result = framework.evolve(TASK)
    report = framework.inspect()['governance']
    assert result['runtime'] == 'composed-v7-governed'
    assert main.calls == 2 and [provider.calls for provider in providers] == [1, 1, 1]
    terminals = payloads(framework, 'governed_control_terminal')
    assert [row['main_cycles'] for row in terminals] == [0, 1, 2]
    assert report['planned'] == report['completed'] == 3
    assert report['failed'] == report['pending'] == report['unresolved'] == 0
    assert report['budget']['reconciled'] is True
    accounts = report['budget']['accounts']
    assert set(accounts) == {'explore', 'exploit', 'reeval', 'control', 'repair', 'handoff', 'overhead'}
    assert accounts['control'] == {'token': 36, 'node': 3, 'eval_count': 3}
    assert accounts['explore'] == accounts['exploit'] == {'token': 12, 'node': 1, 'eval_count': 1}
    assert accounts['reeval'] == {'token': 21, 'node': 0, 'eval_count': 3}
    assert result['ledger']['global']['used'] == {'token': 81, 'node': 5, 'eval_count': 8}
    assert not report['budget']['open_intents']
    control_ids = {row['candidate_id'] for row in terminals}
    assert control_ids.isdisjoint(framework._composed.frontier.nodes)
    assert result['best_candidate_id'] not in control_ids
    assert len(payloads(framework, 'worktree_process_started')) == 8
    operations = payloads(framework, 'worktree_operation_prepared')
    paths = []
    for row in operations:
        candidate = row['binding']['proposal']['candidate']['id']
        path = Path(row['worktree_path'])
        paths.append(path)
        if candidate in control_ids:
            assert path.is_relative_to(tmp_path / 'worktrees' / 'controls')
        else:
            assert path.parent == tmp_path / 'worktrees'
    assert len(set(paths)) == 8
    for row in terminals:
        commit = row['evidence']['evidence']['branch_ref']
        assert git(tmp_path / 'repo', 'show', commit + ':candidate.py') == 'VALUE = 0.5'
        assert git(tmp_path / 'repo', 'show', commit + ':invocations.txt') == 'called'


def test_governed_worktree_pause_and_repeated_resume_do_not_repeat_calls(tmp_path):
    prepare(tmp_path)
    first, main, controls = governed_worktree(tmp_path, stop=0)
    first.evolve(TASK)
    assert main.calls == 1 and [provider.calls for provider in controls] == [1, 1, 0]
    assert first.inspect()['governance']['pending'] == 1
    assert len(payloads(first, 'worktree_process_started')) == 4
    resumed, fresh_main, fresh_controls = governed_worktree(tmp_path, resume=True)
    result = resumed.evolve(TASK)
    assert fresh_main.calls == 1 and [provider.calls for provider in fresh_controls] == [0, 0, 1]
    assert resumed.inspect()['governance']['completed'] == 3
    assert result['ledger']['global']['used'] == {'token': 81, 'node': 5, 'eval_count': 8}
    before = physical_execution_files(tmp_path)
    complete, final_main, final_controls = governed_worktree(tmp_path, resume=True)
    assert complete.evolve(TASK) == result
    assert final_main.calls == 0 and all(provider.calls == 0 for provider in final_controls)
    assert physical_execution_files(tmp_path) == before


def test_governed_worktree_replay_never_launches_a_provider_or_command(tmp_path, monkeypatch):
    prepare(tmp_path)
    framework, main, controls = governed_worktree(tmp_path)
    result = framework.evolve(TASK)
    before = physical_execution_files(tmp_path)
    popen = subprocess.Popen

    def forbid_new_command(args, *positional, **keywords):
        if isinstance(args, (list, tuple)) and any(str(arg).endswith('/command_worker.py') for arg in args):
            raise AssertionError('recorded replay attempted a new command process')
        return popen(args, *positional, **keywords)

    def forbid_new_provider(self, prompt):
        raise AssertionError('recorded replay attempted a new provider request')

    monkeypatch.setattr(subprocess, 'Popen', forbid_new_command)
    monkeypatch.setattr(BoundLocalProvider, '__call__', forbid_new_provider)
    replayed = framework.replay()
    certificate = replayed['replay_certificate']
    assert certificate['passed'] is True
    assert certificate['mode'] == 'recorded_outcomes' and certificate['external_calls'] == 0
    assert certificate['receipt_chain_match'] and certificate['transcript_consumed']
    assert replayed['ledger'] == result['ledger']
    assert main.calls == 2 and [provider.calls for provider in controls[:3]] == [1, 1, 1]
    assert all(provider.calls == 0 for provider in controls[3:])
    assert physical_execution_files(tmp_path) == before


def test_measured_failed_control_remains_failed_while_exhaustion_drains_other_slots(tmp_path):
    prepare(tmp_path)
    evaluator = tmp_path / 'repo' / 'evaluate.py'
    source = evaluator.read_text().replace("'status':'ok'", "'status':('failed_to_run' if value < 0 else 'ok')")
    source = source.replace("'executor_status':'scored'",
                            "'executor_status':('failed_to_run' if value < 0 else 'scored')")
    evaluator.write_text(source)
    git(tmp_path / 'repo', 'add', 'evaluate.py')
    git(tmp_path / 'repo', 'commit', '--quiet', '-m', 'measured failed candidate fixture')
    framework, main, providers = governed_worktree(tmp_path, tokens=38, failed_slot='control-0000')
    framework.evolve(TASK)
    report = framework.inspect()['governance']
    assert main.calls == 0 and [provider.calls for provider in providers] == [1, 1, 1]
    assert report['planned'] == 3 and report['completed'] == 2 and report['failed'] == 1
    assert report['pending'] == report['unresolved'] == 0
    terminals = payloads(framework, 'governed_control_terminal')
    assert [row['status'] for row in terminals] == ['failed', 'evaluated', 'evaluated']
    assert [row['main_cycles'] for row in terminals] == [0, 0, 0]
    assert report['budget']['accounts']['control'] == {'token': 36, 'node': 3, 'eval_count': 3}
    assert not report['budget']['open_intents']
    assert len(payloads(framework, 'worktree_process_started')) == 3
    assert not framework._composed.frontier.nodes


def test_known_cost_invalid_control_identity_stops_both_lanes_without_draining(tmp_path):
    prepare(tmp_path)
    evaluator = tmp_path / 'repo' / 'evaluate.py'
    source = evaluator.read_text().replace("binding=request['binding']",
        "binding=request['binding']\nif value < 0: binding['candidate_id']='forged-control'")
    evaluator.write_text(source)
    git(tmp_path / 'repo', 'add', 'evaluate.py')
    git(tmp_path / 'repo', 'commit', '--quiet', '-m', 'invalid control identity fixture')
    framework, main, providers = governed_worktree(tmp_path, failed_slot='control-0000')
    with pytest.raises(MeasuredCommandError):
        framework.evolve(TASK)
    assert main.calls == 0 and [provider.calls for provider in providers] == [1, 0, 0]
    budget = framework._composed.budget.audit_governance()
    assert budget['accounts']['control'] == {'token': 12, 'node': 1, 'eval_count': 1}
    assert not budget['open_intents']
    assert not payloads(framework, 'governed_control_terminal')
    assert len(payloads(framework, 'worktree_process_started')) == 1
    assert not framework._composed.frontier.nodes
