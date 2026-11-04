"""Same-search schedules retain all other frozen M7 settings."""
import copy
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

from zoo.mle_bench_lite.composed_agent import build_governed_profile
from zoo.mle_bench_lite.cny_budget import POLICY


def test_two_control_schedules_differ_only_by_schedule():
    kwargs = {'variant': 'full', 'token_budget': 5_000_000, 'seed': 3, 'iterations': 3,
              'max_completion_tokens': 16384}
    one = build_governed_profile(**kwargs, control_cycles=[0])
    two = build_governed_profile(**kwargs, control_cycles=[0, 2])
    assert one == build_governed_profile(**kwargs)
    assert one['governance']['controls']['after_main_cycles'] == [0]
    assert two['governance']['controls']['after_main_cycles'] == [0, 2]
    normalized = copy.deepcopy(two)
    normalized['governance']['controls']['after_main_cycles'] = [0]
    assert normalized == one


@pytest.mark.parametrize('cycles', [[], [1], [0, 0], [0, -1], [0, 5], [0, True], [0, 2, 1], '0'])
def test_invalid_control_schedules_fail_before_execution(cycles):
    with pytest.raises(ValueError, match='control'):
        build_governed_profile(variant='full', token_budget=5_000_000, seed=1, iterations=3,
                               max_completion_tokens=16384, control_cycles=cycles)


def test_two_controls_require_capacity_to_reach_last_control():
    bound = POLICY['context_tokens'] + 16384
    with pytest.raises(ValueError, match='capacity'):
        build_governed_profile(variant='full', token_budget=4 * bound - 1, seed=1, iterations=3,
                               max_completion_tokens=16384, control_cycles=[0, 2])
    assert build_governed_profile(variant='full', token_budget=4 * bound, seed=1, iterations=3,
        max_completion_tokens=16384, control_cycles=[0, 2])['governance']['controls']['after_main_cycles'] == [0, 2]


@pytest.mark.parametrize('iterations,cycles', [(0, [0, 1]), (3, [0, 4]), (3, [0, 1, 2, 3])])
def test_unreachable_node_schedules_are_rejected(iterations, cycles):
    with pytest.raises(ValueError, match='node capacity'):
        build_governed_profile(variant='full', token_budget=10_000_000, seed=1, iterations=iterations,
                               max_completion_tokens=16384, control_cycles=cycles)


def test_agent_cli_passes_explicit_schedule_only_for_m7(tmp_path, monkeypatch, capsys):
    from zoo.mle_bench_lite import composed_agent
    observed = {}
    def fixture(**kwargs):
        observed.update(kwargs)
        return {'fixture': True}
    monkeypatch.setattr(composed_agent, 'run_governed_agent', fixture)
    args = ['--workspace', str(tmp_path / 'workspace'), '--task', 'spooky-author-identification',
            '--variant', 'full', '--model', 'deepseek-flash', '--token-budget', '5000000',
            '--control-cycles', '0', '2']
    assert composed_agent.main(['--runtime', 'm7', *args]) == 0
    assert observed['control_cycles'] == [0, 2]
    assert 'fixture' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        composed_agent.main(['--runtime', 'legacy', *args])


def test_control_timing_marks_early_drain_and_rejects_wrong_slots():
    from zoo.mle_bench_lite.governance_intensity import control_timing
    from core.x1.checkpoint import payload_digest
    logical_run_id = 'test-run'
    def completed(cycle):
        candidate = f'candidate-{cycle}'
        measured = {'candidate_id': candidate}
        evidence = {'cycle': cycle, 'proposal': {'candidate': {'id': candidate}}, 'evidence': measured,
                    'evidence_ref': 'sha256:' + payload_digest({'logical_run_id': logical_run_id,
                        'evidence': {'schema_version': 1, 'evidence': measured}})}
        decision = {'candidate_id': candidate, 'incumbent': None, 'evidence': measured, 'decision': {'admit': True}}
        return [{'kind': 'composed_cycle_started', 'payload': {'cycle': cycle}},
                {'kind': 'composed_evidence', 'payload': evidence},
                {'kind': 'composed_decision', 'payload': {**decision, 'event_id': 'sha256:' + payload_digest(decision)}},
                {'kind': 'composed_checkpoint', 'payload': {'next_cycle': cycle + 1}}]
    plan = {'plan_ref': 'sha256:' + 'a' * 64, 'slots': [
        {'slot_id': 'control-0000', 'after_main_cycles': 0},
        {'slot_id': 'control-0001', 'after_main_cycles': 2}]}
    start0 = {'kind': 'governed_control_started', 'payload':
              {'slot_id': 'control-0000', 'plan_ref': plan['plan_ref'], 'main_cycles': 0}}
    start1 = {'kind': 'governed_control_started', 'payload':
              {'slot_id': 'control-0001', 'plan_ref': plan['plan_ref'], 'main_cycles': 2}}
    one, two = completed(0), completed(1)
    assert control_timing(plan, [0, 2], [start0, *one, *two, start1], logical_run_id=logical_run_id)['all_on_schedule'] is True
    stop = {'kind': 'governed_main_stopped', 'payload': {'main_cycles': 1, 'disposition': 'ordinary'}}
    early = [start0, *one, stop, {**start1, 'payload': {**start1['payload'], 'main_cycles': 1}}]
    result = control_timing(plan, [0, 2], early, logical_run_id=logical_run_id)
    assert result['all_on_schedule'] is False and result['slots'][1]['drained_early'] is True
    with pytest.raises(ValueError, match='control'):
        control_timing(plan, [0, 2], [start0, start0], logical_run_id=logical_run_id)
    with pytest.raises(ValueError, match='committed'):
        control_timing(plan, [0, 2], [start0, *one, stop, start1], logical_run_id=logical_run_id)
    with pytest.raises(ValueError, match='committed'):
        control_timing(plan, [0, 2], [start0, *one, start1, *two], logical_run_id=logical_run_id)
    forged_checkpoint = {'kind': 'composed_checkpoint', 'payload': {'next_cycle': 2}}
    with pytest.raises(ValueError, match='cycle evidence'):
        control_timing(plan, [0, 2], [start0, *one, forged_checkpoint, start1], logical_run_id=logical_run_id)
    with pytest.raises(ValueError, match='decision'):
        control_timing(plan, [0, 2], [start0, one[0], one[2], one[1], one[3], *two, start1],
                       logical_run_id=logical_run_id)


def test_comparison_plan_and_commands_freeze_same_search():
    from zoo.mle_bench_lite import pilot
    plan = pilot._plan('deepseek-flash', 5_000_000, 600, 120, 3, [1], list(pilot.DEFAULT_TASKS),
        spending_ledger_path='/tmp/fixture-ledger', runtime='m7', comparison='governance-intensity')
    assert plan['arms'] == ['one_control', 'two_controls'] and plan['expected_runs'] == 6
    assert plan['comparison']['search_variant'] == 'full'
    profiles = [pilot._comparison_profile(arm, 5_000_000, 1, 3, max_completion_tokens=16384)
                for arm in plan['arms']]
    adjusted = copy.deepcopy(profiles[1])
    adjusted['governance']['controls']['after_main_cycles'] = [0]
    assert profiles[0] == adjusted
    for arm, cycles in [('one_control', ['0']), ('two_controls', ['0', '2'])]:
        command = shlex.split(pilot._comparison_command('deepseek-flash', 5_000_000, 120, 3,
            arm=arm, spending_ledger_path='/tmp/fixture-ledger'))
        assert command[command.index('--variant') + 1] == 'full'
        assert command[command.index('--control-cycles') + 1:] == cycles
    with pytest.raises(ValueError, match='m7'):
        pilot._plan('deepseek-flash', 5_000_000, 600, 120, 3, [1], list(pilot.DEFAULT_TASKS),
                    runtime='legacy', comparison='governance-intensity')


def test_comparison_refuses_campaign_without_full_worst_case_capacity(tmp_path, monkeypatch):
    from zoo.mle_bench_lite import pilot
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    monkeypatch.setenv('OPENAI_API_BASE', 'https://api.deepseek.com')
    ledger = CampaignBudget.create(tmp_path / 'fixture.db', limit_micro_cny=5_000_000)
    before = ledger.snapshot()
    plan = pilot._plan('deepseek-flash', 5_000_000, 600, 120, 3, [1], list(pilot.DEFAULT_TASKS),
        spending_ledger_path=ledger.path, runtime='m7', comparison='governance-intensity')
    with pytest.raises(ValueError, match='worst-case'):
        pilot._bind_campaign(plan, ledger.path)
    assert ledger.snapshot() == before


def test_comparison_summary_uses_control_labels_and_rejects_early_drain():
    from zoo.mle_bench_lite import pilot
    spec = {'task_ids': ['task'], 'seeds': [1], 'arms': ['one_control', 'two_controls'],
            'expected_runs': 2, 'model': 'fixture', 'comparison': {'kind': 'governance-intensity'}}
    rows = [{'task_id': 'task', 'seed': 1, 'arm': arm, 'status': 'graded', 'actual_model': 'fixture',
             'dataset_identity': 'same', 'metric_direction': 'minimize',
             'official_result': {'score': score, 'valid_submission': True},
             'actual_costs': {'token': tokens, 'wallclock': 1},
             'usage_audit': {'actual_models': ['fixture'], 'known_tokens': tokens,
                             'complete': True, 'costs_complete': True,
                             'control_timing': {'all_on_schedule': on_schedule}}}
            for arm, score, tokens, on_schedule in [('one_control', 0.5, 10, True),
                                                     ('two_controls', 0.6, 12, True)]]
    report = pilot._summary_report(spec, rows, True)
    assert report['pilot_complete'] and report['pairs'][0]['score_delta_two_minus_one'] == pytest.approx(0.1)
    assert report['pairs'][0]['token_delta_two_minus_one'] == 2
    rows[1]['usage_audit']['control_timing']['all_on_schedule'] = False
    report = pilot._summary_report(spec, rows, True)
    assert not report['pilot_complete'] and not report['pairs'][0]['complete']
    rows[1]['usage_audit']['control_timing']['all_on_schedule'] = True
    report = pilot._summary_report(spec, [rows[0], rows[0]], True)
    assert not report['pilot_complete'] and not report['pairs'][0]['complete']


def test_comparison_grading_requires_every_intact_frozen_slot(tmp_path):
    from zoo.mle_bench_lite import pilot
    spec = {'task_ids': ['task'], 'seeds': [1], 'arms': ['one_control', 'two_controls'], 'expected_runs': 2}
    rows = []
    for arm in spec['arms']:
        frozen = tmp_path / 'task' / 'seed_1' / arm / 'frozen' / 'submission.csv'
        frozen.parent.mkdir(parents=True)
        frozen.write_text('prediction\n1\n')
        rows.append({'task_id': 'task', 'seed': 1, 'arm': arm, 'status': 'frozen',
            'submission_sha256': pilot.file_digest(frozen), 'dataset_identity': 'same',
            'metric_direction': 'minimize', 'usage_audit': {'complete': True, 'costs_complete': True,
                'control_timing': {'all_on_schedule': True}}})
    class Ledger:
        state = {'journal_schema_version': 2, 'pending_calls': [], 'protection_breaches': [],
                 'reserved_micro_cny': 0, 'protected_micro_cny': 0}
        def snapshot(self):
            return self.state
    ledger = Ledger()
    pilot._comparison_grading_ready(spec, rows, tmp_path, ledger)
    with pytest.raises(ValueError, match='frozen'):
        pilot._comparison_grading_ready(spec, rows[:1], tmp_path, ledger)
    ledger.state['pending_calls'] = ['unresolved']
    with pytest.raises(ValueError, match='campaign'):
        pilot._comparison_grading_ready(spec, rows, tmp_path, ledger)
    ledger.state['pending_calls'] = []
    (tmp_path / 'task/seed_1/two_controls/frozen/submission.csv').write_text('changed')
    with pytest.raises(ValueError, match='submission'):
        pilot._comparison_grading_ready(spec, rows, tmp_path, ledger)


def test_comparison_campaign_lock_is_exclusive_and_rejects_symlink(tmp_path):
    from zoo.mle_bench_lite import pilot
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'fixture.db')
    with pilot._comparison_campaign_lock(ledger.path):
        with pytest.raises(ValueError, match='lock'):
            with pilot._comparison_campaign_lock(ledger.path):
                pass
    lock = tmp_path / 'authorized-pilot.lock'
    lock.unlink()
    lock.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises((OSError, ValueError)):
        with pilot._comparison_campaign_lock(ledger.path):
            pass


def test_public_comparison_holds_campaign_lock_while_running(tmp_path, monkeypatch):
    from zoo.mle_bench_lite import pilot
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create(tmp_path / 'fixture.db')
    def fixture(*args, **kwargs):
        with pytest.raises(ValueError, match='lock'):
            with pilot._comparison_campaign_lock(ledger.path):
                pass
        return {'fixture': True}
    monkeypatch.setattr(pilot, '_run_pilot_impl', fixture)
    assert pilot.run_pilot(tmp_path, tmp_path, tmp_path / 'out', model='fixture', token_budget=5_000_000,
        spending_ledger_path=ledger.path, runtime='m7', comparison='governance-intensity') == {'fixture': True}


def test_comparison_source_state_rejects_dirty_checkout(tmp_path):
    from zoo.mle_bench_lite import pilot
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'user.email', 'fixture@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'user.name', 'Fixture'], check=True)
    (tmp_path / 'source.py').write_text('value = 1\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'commit', '-qm', 'fixture'], check=True)
    state = pilot._comparison_source_state(Path(tmp_path))
    assert len(state['commit']) == 40 and state['scope'] == 'clean-checkout-not-runtime-attestation'
    (tmp_path / 'source.py').write_text('value = 2\n')
    with pytest.raises(ValueError, match='clean'):
        pilot._comparison_source_state(Path(tmp_path))
    subprocess.run(['git', '-C', str(tmp_path), 'checkout', '--', 'source.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'update-index', '--assume-unchanged', 'source.py'], check=True)
    (tmp_path / 'source.py').write_text('value = 3\n')
    with pytest.raises(ValueError, match='source bytes'):
        pilot._comparison_source_state(Path(tmp_path))


def test_comparison_child_rejects_wrong_source_before_agent(tmp_path, monkeypatch):
    from zoo.mle_bench_lite import composed_agent, pilot
    monkeypatch.setenv('MLE_COMPARISON_SOURCE_COMMIT', '1' * 40)
    monkeypatch.setattr(pilot, '_comparison_runtime_source', lambda: {'commit': '2' * 40})
    def unexpected(**_kwargs):
        pytest.fail('agent must not run when its source identity differs')
    monkeypatch.setattr(composed_agent, 'run_governed_agent', unexpected)
    with pytest.raises(ValueError, match='child source'):
        composed_agent.main(['--workspace', str(tmp_path), '--model', 'fixture', '--variant', 'full',
                             '--runtime', 'm7', '--control-cycles', '0'])


def test_formal_comparison_preflight_rejects_unverifiable_source(tmp_path, monkeypatch):
    from zoo.mle_bench_lite import pilot
    def fail_source():
        raise ValueError('unverifiable fixture source')
    monkeypatch.setattr(pilot, '_comparison_runtime_source', fail_source)
    result = pilot.preflight_pilot(tmp_path / 'official', tmp_path / 'data', model='deepseek-flash',
        token_budget=5_000_000, iterations=3, runtime='m7', comparison='governance-intensity',
        spending_ledger_path=tmp_path / 'missing.db')
    assert not result['ready']
    assert any(item['requirement'] == 'comparison_source' for item in result['missing'])


@pytest.mark.parametrize('endpoint,key,ledger', [
    ('https://api.deepseek.com', 'fixture-only', 'fixture-campaign.db'),
    ('http://127.0.0.1:1234', 'real-key-placeholder', 'fixture-campaign.db'),
    ('http://127.0.0.1:1234', 'fixture-only', 'campaign.db'),
])
def test_comparison_fixture_rejects_real_provider_or_ledger_before_launch(tmp_path, monkeypatch, endpoint, key, ledger):
    from zoo.mle_bench_lite import pilot
    monkeypatch.setenv('OPENAI_API_BASE', endpoint)
    monkeypatch.setenv('OPENAI_API_KEY', key)
    with pytest.raises(ValueError, match='fixtures require loopback'):
        pilot._run_pilot_impl(tmp_path / 'official', tmp_path / 'data', tmp_path / 'out',
            model='deepseek-flash', token_budget=5_000_000, iterations=3, runtime='m7',
            comparison='governance-intensity', grader_factory=lambda _task: None,
            spending_ledger_path=tmp_path / ledger)
    assert not (tmp_path / 'out').exists()


def test_comparison_fixture_rejects_any_caller_ledger(tmp_path):
    from zoo.mle_bench_lite import pilot
    with pytest.raises(ValueError, match='caller-supplied campaign ledger'):
        pilot.run_pilot(tmp_path, tmp_path, tmp_path / 'out', model='deepseek-flash', token_budget=5_000_000,
            runtime='m7', comparison='governance-intensity', grader_factory=lambda _task: None,
            spending_ledger_path=tmp_path / 'fixture-campaign.db')


def test_fixture_child_does_not_inherit_unrelated_credentials(tmp_path, monkeypatch):
    import shlex
    import sys
    from zoo.mle_bench_lite.runner import _execute_agent
    monkeypatch.setenv('SENTINEL_PRIVATE_CREDENTIAL', 'must-not-be-inherited')
    workspace, run_dir = tmp_path / 'workspace', tmp_path / 'run'
    workspace.mkdir(); run_dir.mkdir()
    code = "import os; print(os.getenv('SENTINEL_PRIVATE_CREDENTIAL', 'absent')); print(os.getenv('OPENAI_API_KEY'))"
    result = _execute_agent(shlex.join([sys.executable, '-c', code]), workspace, 'fixture', 1, 'one_control',
                            10, run_dir, {'MLE_FIXTURE_ENV_ONLY': '1'})
    assert result['agent_returncode'] == 0
    assert (run_dir / 'stdout.log').read_text().splitlines() == ['absent', 'fixture-only']


def test_comparison_child_path_preserves_parent_selected_sandbox(tmp_path, monkeypatch):
    from zoo.mle_bench_lite import pilot
    sandbox_dir = tmp_path / 'sandbox-bin'
    sandbox_dir.mkdir()
    executable = sandbox_dir / 'bwrap'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(sandbox_dir) + os.pathsep + os.defpath)
    selected = getattr(pilot, '_comparison_sandbox_path', None)
    assert callable(selected), 'comparison must preserve the selected sandbox executable'
    child_path = selected()
    assert child_path.split(os.pathsep)[0] == str(sandbox_dir)
    assert shutil.which('bwrap', path=child_path) == str(executable)
    from zoo.mle_bench_lite.runner import _execute_agent
    workspace, run_dir = tmp_path / 'workspace', tmp_path / 'run'
    workspace.mkdir(); run_dir.mkdir()
    import sys
    command = shlex.join([sys.executable, '-c', "import shutil;print(shutil.which('bwrap'))"])
    result = _execute_agent(command, workspace, 'fixture', 1, 'one_control', 10, run_dir,
                            {'MLE_FIXTURE_ENV_ONLY':'1', 'PATH':child_path})
    assert result['agent_returncode'] == 0
    assert (run_dir / 'stdout.log').read_text().strip() == str(executable)
