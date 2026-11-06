"""Prepare a real-provider Mori controller without dispatching any work.

This uses a new temporary ledger and a fake credential. It does not enable a
live pilot or exercise the user's existing campaign.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import urllib.request

import pytest

from core.composition.recovery import ContinuationStore
from core.executor.sandbox import sandbox_child_path
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
from zoo.circle_packing.frozen_source import freeze_source_plan
from zoo.circle_packing.mori_controller import build_controller
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


@pytest.fixture
def prepared_cell(tmp_path, request):
    cache = os.environ['MORI_TEST_OFFLINE_CACHE']
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    if getattr(request, 'param', None) == 'supervised_fake_live':
        worker = checkout / 'm0/zoo/circle_packing/mori_live_worker.py'
        code = worker.read_text()
        gate = "    raise ValueError('live pilot gate is not complete')"
        insertion = '    outcome = framework.evolve(TASK)'
        assert code.count(gate) == code.count(insertion) == 1
        # A separate, disposable source commit opens the gate only for this
        # fake-transport test. Production source and the user's key are untouched.
        fake = '''    import json as test_json, socket as test_socket, urllib.request as test_request
    assert '/mori-cell-' in open('/proc/self/cgroup').read(), 'worker was not contained before search'
    def no_network(*args, **kwargs):
        raise AssertionError('test forbids network connections')
    test_socket.socket.connect = no_network
    diff = ("<<<<<<< SEARCH\\n    # Initialize arrays for 26 circles\\n    n = 26\\n=======\\n"
            "    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\\n"
            "    r = np.full(26, .07)\\n    return c, r, float(np.sum(r))\\n>>>>>>> REPLACE\\n")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return test_json.dumps({'model': config['plan']['model'],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
                'choices': [{'finish_reason': 'stop', 'message': {'content': diff}}]}).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == config['base_url'] + '/chat/completions'
            assert request.get_header('Authorization') == 'Bearer fixture-only-secret'
            return Response()
    test_request.build_opener = lambda *args: Opener()
'''
        worker.write_text(code.replace(gate, '    return None').replace(insertion, fake + insertion))
        subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/mori_live_worker.py'], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet',
                        '-m', 'offline supervised live test'], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    lock = hashlib.sha256((checkout / 'm0' / 'uv.lock').read_bytes()).hexdigest()
    plan = build_draft_plan(ledger.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)
    ref, campaign_id = 'sha256:' + plan['draft_sha256'], ledger.manifest_binding()['campaign_id']
    source, runtime = tmp_path / 'source', tmp_path / 'runtime'
    exported = freeze_source_plan(ledger, plan, checkout=checkout, destination=source,
        expected_plan_ref=ref, expected_campaign_id=campaign_id, require_runtime=True)
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=source, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    output = tmp_path / 'mori'
    config = {'plan': plan, 'ref': ref, 'runtime_manifest': frozen['manifest'],
        'source_manifest': exported['manifest'], 'campaign_id': campaign_id, 'seed': 0,
        'source': str(source / 'm0'), 'runtime': str(runtime), 'ledger': str(ledger.path),
        'clock': str(clock._store.path), 'output': str(output),
        'base_url': ledger.manifest_binding()['provider_base_url']}
    return config, ledger, clock, runner


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live'], indirect=True)
def test_live_supervisor_runs_real_entry_with_test_source_and_no_network(prepared_cell, tmp_path, monkeypatch):
    from zoo.circle_packing.mori_supervisor import launch_live_controller
    config, ledger, clock, _runner = prepared_cell
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    directory = tmp_path / 'live-supervisor'
    result = launch_live_controller(config, deadline=clock, directory=directory, api_key='fixture-only-secret')
    assert result['returncode'] == 0 and not result['timeout'] and not result.get('wrapper_error'), result['stderr']
    report = json.loads(result['stdout'])
    assert report['mode'] == 'live' and report['performance_claim'] is False
    assert report['candidate'] and report['final_state'] == 'completed' and report['replay_passed']
    assert report['final_measurement']['validity'] == 1.0
    snapshot = ledger.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] > 0
    assert snapshot['settled_upper_bound_micro_cny'] % 38 == 0
    assert not snapshot['pending_calls']
    assert ledger.cell_worker_claim('mori-0')['deadline_ref'] == clock._record['record_sha256']
    for root in (directory, Path(config['output'])):
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                assert b'fixture-only-secret' not in path.read_bytes(), f'fixture credential persisted in {path}'


@pytest.mark.linux
def test_real_provider_composition_requires_no_network_or_candidate_execution(prepared_cell, monkeypatch):
    config, ledger, clock, runner = prepared_cell
    plan, output = config['plan'], Path(config['output'])
    def forbidden(*args, **kwargs):
        raise AssertionError('preparation attempted external or candidate work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(SandboxRunner, 'execute', forbidden)
    framework, provider, profile, adapters = build_controller(
        config, ledger=ledger, clock=clock, runner=runner, api_key='fixture-only-secret')
    assert framework is not None and callable(adapters)
    assert provider.manifest_binding()['base_url'] == ledger.manifest_binding()['provider_base_url']
    assert provider.manifest_binding()['requested_model'] == plan['model']
    assert profile['budget']['options']['limits']['global']['token'] == plan['limits']['token']
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 0
    assert not ledger.snapshot()['pending_calls']
    if output.exists():
        for path in output.rglob('*'):
            if path.is_file() and not path.is_symlink():
                assert b'fixture-only-secret' not in path.read_bytes(), f'fixture credential persisted in {path}'


@pytest.mark.linux
def test_real_provider_mode_runs_six_rounds_with_network_blocked(prepared_cell, tmp_path):
    config, ledger, _clock, _runner = prepared_cell
    setup = tmp_path / 'setup.json'
    setup.write_text(json.dumps(config))
    script = r'''
import json, os, pathlib, socket, sys, urllib.request
import core.loop
from zoo.circle_packing import mori_live_worker

config = json.loads(pathlib.Path(sys.argv[1]).read_text())
plan = config['plan']
assert sys.executable == str(pathlib.Path(config['runtime']) / 'bin' / 'python')
assert pathlib.Path(core.loop.__file__).resolve() == pathlib.Path(config['source']) / 'core' / 'loop.py'
calls = []
def forbidden(*args, **kwargs):
    raise AssertionError('unexpected external work')
socket.socket.connect = forbidden
diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
        '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
        '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
class Response:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self):
        return json.dumps({'model': plan['model'],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
            'choices': [{'finish_reason': 'stop', 'message': {'content': diff}}]}).encode()
class Opener:
    def open(self, request, timeout):
        assert request.full_url == config['base_url'] + '/chat/completions'
        assert request.get_header('Authorization') == 'Bearer fixture-only-secret'
        calls.append(1)
        return Response()
urllib.request.build_opener = lambda *args: Opener()
# Only this offline test bypasses the incomplete live gate.
mori_live_worker._require_live_gate = lambda _: None
result = mori_live_worker.run(config)
assert 'DEEPSEEK_API_KEY' not in os.environ
measurement = result['final_measurement']
print(json.dumps({'candidate': result['candidate'], 'state': result['final_state'],
    'metrics': {'test/validity': measurement['validity'], 'test/sum_radii': measurement['sum_radii']},
    'calls': len(calls), 'replay': result['replay_passed']}))
'''
    code = tmp_path / 'blocked_transport.py'
    code.write_text(script)
    env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'DEEPSEEK_API_KEY': 'fixture-only-secret',
           'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    process = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-B', str(code), str(setup)],
                             cwd=tmp_path, env=env, capture_output=True, text=True, timeout=240)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['candidate'] and result['state'] == 'completed' and result['replay']
    assert result['metrics']['test/validity'] == 1.0
    assert result['metrics']['test/sum_radii'] > 0
    assert 1 <= result['calls'] <= 2 * config['plan']['iterations'] + 2
    snapshot = ledger.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == result['calls'] * 38
    assert not snapshot['pending_calls']
    for path in Path(config['output']).rglob('*'):
        if path.is_file() and not path.is_symlink():
            assert b'fixture-only-secret' not in path.read_bytes(), f'fixture credential persisted in {path}'


@pytest.mark.linux
def test_reference_real_provider_path_with_test_gate_override_and_no_network(prepared_cell, tmp_path, monkeypatch):
    """Exercise real-provider wiring with a fake transport and test-only gate override."""
    from zoo.circle_packing.host_runtime import (build_reference_authorities, run_reference_cell_fixture,
                                                run_reference_cell_live)
    config, ledger, _mori_clock, runner = prepared_cell
    plan = config['plan']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref=config['ref'], seconds=plan['limits']['wallclock_seconds'])
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({'model': plan['model'],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
                'choices': [{'finish_reason': 'stop', 'message': {'content': diff}}]}).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == config['base_url'] + '/chat/completions'
            assert request.get_header('Authorization') == 'Bearer fixture-only-secret'
            wire = json.loads(request.data)
            assert wire['model'] == plan['model'] and wire['max_tokens'] == plan['max_completion_tokens']
            assert [message['role'] for message in wire['messages']] == ['system', 'user']
            calls.append(1)
            return Response()
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    original_connect = socket.socket.connect
    def local_only(sock, address):
        if sock.family != socket.AF_UNIX:
            raise AssertionError('test forbids external socket connections')
        return original_connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)
    authority = build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=plan,
        expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'], deadline=clock,
        snapshot=Path(config['source']).parent, source_manifest=config['source_manifest'], runner=runner,
        api_key='fixture-only-secret', base_url=config['base_url'], mode='live_preparation')
    try:
        with pytest.raises(ValueError, match='fixture requires'):
            run_reference_cell_fixture(authority, clock, tmp_path / 'worker', tmp_path / 'unused',
                snapshot=Path(config['source']).parent, source_manifest=config['source_manifest'],
                frozen_plan=plan, expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'],
                runtime=config['runtime'], runtime_manifest=config['runtime_manifest'],
                base_python='/usr/bin/python3.12')
        with pytest.raises(ValueError, match='live pilot gate'):
            run_reference_cell_live(authority, clock, tmp_path / 'worker', tmp_path / 'unused',
                snapshot=Path(config['source']).parent, source_manifest=config['source_manifest'],
                frozen_plan=plan, expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'],
                runtime=config['runtime'], runtime_manifest=config['runtime_manifest'],
                base_python='/usr/bin/python3.12')
        assert not ledger.reference_authority_claim('vendor-0')['work_started']
        assert not calls and not (tmp_path / 'worker').exists()
        # Only this offline test bypasses the unfinished live gate. It uses a
        # disposable ledger, fake key, intercepted transport and no network.
        monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
        with tempfile.TemporaryDirectory(prefix='mori-reference-', dir='/tmp') as path:
            workspace = Path(path).resolve()
            result = run_reference_cell_live(authority, clock, tmp_path / 'worker', workspace,
                snapshot=Path(config['source']).parent, source_manifest=config['source_manifest'],
                frozen_plan=plan, expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'],
                runtime=config['runtime'], runtime_manifest=config['runtime_manifest'],
                base_python='/usr/bin/python3.12')
            assert result['state'] == 'completed' and result['mode'] == 'live' and result['performance_claim'] is False
            assert result['selected_program']['metrics']['validity'] == 1.0
            for root in (tmp_path / 'reference', tmp_path / 'worker', workspace):
                for file in root.rglob('*'):
                    if file.is_file() and not file.is_symlink():
                        assert b'fixture-only-secret' not in file.read_bytes(), f'fixture key persisted in {file}'
        assert len(calls) == plan['iterations']
        assert ledger.snapshot()['settled_upper_bound_micro_cny'] == len(calls) * 38
        assert not ledger.snapshot()['pending_calls']
        run_id = authority.dispatch.ready.authority_binding['currency_run_id']
        assert ledger.reference_selection(run_id) is not None
        from dataclasses import asdict
        from zoo.circle_packing.cell_deadline import RecordedCellClock
        from zoo.circle_packing.reference_recovery import recover_reference_snapshot
        from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
        evidence = ledger.export_governance_evidence(run_id, authority.dispatch.ready.physical_plan_ref)
        view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=ledger.snapshot()['journal_head'])
        recorded_clock = RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim('vendor-0'))
        def no_work(*args, **kwargs):
            raise AssertionError('recorded recovery attempted external work')
        monkeypatch.setattr(GovernedCNYProvider, 'perform_request', no_work)
        monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', no_work)
        monkeypatch.setattr('zoo.circle_packing.stage.run_stage', no_work)
        recovered = recover_reference_snapshot(view, recorded_clock, run_id, plan=plan,
            expected_plan_ref=config['ref'], worker_directory=tmp_path / 'worker',
            options=authority.budget.options, stamp=asdict(authority.budget.stamp),
            governance=authority.budget._governed.config, rows=list(authority.budget.store.read()))
        assert recovered['metrics'] == result['selected_program']['metrics']
        assert recovered['selection_frozen'] and recovered['performance_claim'] is False
    finally:
        authority.close()
