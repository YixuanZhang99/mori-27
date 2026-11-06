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
import sys
import tempfile
import time
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
def prepared_cell(tmp_path, request, monkeypatch):
    cache = os.environ['MORI_TEST_OFFLINE_CACHE']
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    if getattr(request, 'param', None) in ('reference_fake_live', 'reference_fake_live_stall',
                                           'reference_fake_live_inflight', 'reference_fake_live_timeout',
                                           'coordinator_fake_vendor', 'paired_fake_live',
                                           'reference_fake_live_sandbox_timeout', 'reference_fake_live_final_timeout'):
        host = checkout / 'm0/zoo/circle_packing/host_runtime.py'
        worker = checkout / 'm0/zoo/circle_packing/reference_live_worker.py'
        code = host.read_text()
        gate = "    raise ValueError('live pilot gate is not complete')"
        assert code.count(gate) == 1
        host.write_text(code.replace(gate, '    return None'))
        code = worker.read_text()
        insertion = '    with authority:'
        assert code.count(insertion) == 1
        fake = '''    import socket as test_socket, urllib.request as test_request
    assert '/mori-cell-' in open('/proc/self/cgroup').read(), 'reference host was not contained'
    original_connect = test_socket.socket.connect
    def local_only(sock, address):
        if sock.family != test_socket.AF_UNIX: raise AssertionError('external network forbidden')
        return original_connect(sock, address)
    test_socket.socket.connect = local_only
    diff = ("<<<<<<< SEARCH\\n    # Initialize arrays for 26 circles\\n    n = 26\\n=======\\n"
            "    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\\n"
            "    r = np.full(26, .07)\\n    return c, r, float(np.sum(r))\\n>>>>>>> REPLACE\\n")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({'model': config['plan']['model'],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
                'choices': [{'finish_reason': 'stop', 'message': {'content': diff}}]}).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == config['base_url'] + '/chat/completions'
            assert request.get_header('Authorization') == 'Bearer fixture-only-secret'
            return Response()
    test_request.build_opener = lambda *args: Opener()
'''
        if request.param in ('reference_fake_live_inflight', 'reference_fake_live_timeout'):
            needle = '            return Response()'
            assert fake.count(needle) == 1
            fake = fake.replace(needle, "            import time as test_time\n"
                "            (Path(config['output']).parent / 'provider-inflight').write_text('ready')\n"
                "            test_time.sleep(60)\n" + needle)
        if request.param == 'reference_fake_live_stall':
            fake += ("    import time as test_time\n"
                     "    (Path(config['output']).parent / 'reference-ready').write_text('ready')\n"
                     "    test_time.sleep(60)\n")
        worker.write_text(code.replace(insertion, fake + insertion))
        subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/host_runtime.py',
                        'm0/zoo/circle_packing/reference_live_worker.py'], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet',
                        '-m', 'offline reference live host test'], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if getattr(request, 'param', None) in ('supervised_fake_live', 'supervised_fake_live_stall',
                                           'supervised_fake_live_inflight', 'supervised_fake_live_timeout',
                                           'coordinator_fake_mori', 'paired_fake_live',
                                           'supervised_fake_live_sandbox_timeout', 'supervised_fake_live_final_timeout'):
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
        if request.param in ('supervised_fake_live_inflight', 'supervised_fake_live_timeout'):
            needle = '            return Response()'
            assert fake.count(needle) == 1
            fake = fake.replace(needle, "            import time as test_time\n"
                "            (Path(config['output']).parent / 'provider-inflight').write_text('ready')\n"
                "            test_time.sleep(60)\n" + needle)
        if request.param == 'supervised_fake_live_stall':
            fake += ("    import time as test_time\n"
                     "    (Path(config['output']).parent / 'controller-ready').write_text('ready')\n"
                     "    test_time.sleep(60)\n")
        worker.write_text(code.replace(gate, '    return None').replace(insertion, fake + insertion))
        subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/mori_live_worker.py'], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet',
                        '-m', 'offline supervised live test'], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if getattr(request, 'param', None) in ('reference_fake_live_timeout', 'supervised_fake_live_timeout',
                                           'reference_fake_live_sandbox_timeout', 'supervised_fake_live_sandbox_timeout',
                                           'reference_fake_live_final_timeout', 'supervised_fake_live_final_timeout'):
        # Shorten only this disposable source and plan; production keeps 2700 s.
        from core.x1.checkpoint import payload_digest
        from zoo.circle_packing import pilot_plan
        pilot = checkout / 'm0/zoo/circle_packing/pilot_plan.py'
        source_text = pilot.read_text()
        assert source_text.count("'wallclock_seconds': 2700") == 1
        final_timeout = request.param in ('reference_fake_live_final_timeout', 'supervised_fake_live_final_timeout')
        seconds = 60 if final_timeout else 45
        source_text = source_text.replace("'wallclock_seconds': 2700", f"'wallclock_seconds': {seconds}")
        if final_timeout:
            assert source_text.count('iterations = 6') == 1
            source_text = source_text.replace('iterations = 6', 'iterations = 1')
        pilot.write_text(source_text)
        subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/pilot_plan.py'], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet',
                        '-m', 'offline shortened deadline test'], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        original_plan = pilot_plan.build_draft_plan
        def short_plan(*args, **kwargs):
            value = original_plan(*args, **kwargs)
            value['limits']['wallclock_seconds'] = seconds
            if final_timeout:
                value['iterations'] = 1
                value['limits']['token'] = 4 * (1048576 + 16384)
                value['limits']['eval_count'] = 7
                value['limits']['node'] = 3
            del value['draft_sha256']
            value['draft_sha256'] = payload_digest(value)
            return value
        monkeypatch.setattr(pilot_plan, 'build_draft_plan', short_plan)
        monkeypatch.setattr(sys.modules[__name__], 'build_draft_plan', short_plan)
    if getattr(request, 'param', None) in ('reference_fake_live_final_timeout', 'supervised_fake_live_final_timeout'):
        if request.param == 'reference_fake_live_final_timeout':
            target = checkout / 'm0/zoo/circle_packing/host_runtime.py'
            needle = "        deadline.check()\n        authority.dispatch.audit()"
            injected = ("        Path(worker_directory).parent.joinpath('before-final-marker').write_text('ready')\n"
                        "        import time as test_time\n        test_time.sleep(90)\n" + needle)
        else:
            target = checkout / 'm0/core/composition/final_evaluation.py'
            needle = "        runtime.store.append('metric_final_frozen', frozen)"
            injected = (needle + "\n        import time as test_time\n"
                        "        runtime.workdir.joinpath('before-final-marker').write_text('ready')\n"
                        "        test_time.sleep(90)")
        code = target.read_text()
        assert code.count(needle) == 1
        target.write_text(code.replace(needle, injected))
        subprocess.run(['git', '-C', str(checkout), 'add', str(target.relative_to(checkout))], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet',
                        '-m', 'offline before-final deadline test'], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if getattr(request, 'param', None) in ('reference_fake_live_sandbox_timeout', 'supervised_fake_live_sandbox_timeout'):
        stage = checkout / 'm0/zoo/circle_packing/stage.py'
        code = stage.read_text()
        original = "_WRAPPER = '''import importlib.util, json, os, sys"
        injected = "_WRAPPER = '''import time\nopen('sandbox-start', 'w').write('running')\ntime.sleep(60)\nimport importlib.util, json, os, sys"
        assert code.count(original) == 1
        stage.write_text(code.replace(original, injected))
        subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/stage.py'], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet',
                        '-m', 'offline sandbox deadline test'], check=True)
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
    clock_path = tmp_path / 'clock.jsonl'
    clock = None if getattr(request, 'param', None) in ('coordinator_fake_mori', 'coordinator_fake_vendor') else \
        CellDeadline.start(ContinuationStore(clock_path), lifecycle=CellLifecycle(ledger),
            cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    output = tmp_path / 'mori'
    config = {'plan': plan, 'ref': ref, 'runtime_manifest': frozen['manifest'],
        'source_manifest': exported['manifest'], 'campaign_id': campaign_id, 'seed': 0,
        'source': str(source / 'm0'), 'runtime': str(runtime), 'ledger': str(ledger.path),
        'clock': str(clock_path), 'output': str(output),
        'base_url': ledger.manifest_binding()['provider_base_url']}
    return config, ledger, clock, runner


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['coordinator_fake_mori', 'coordinator_fake_vendor'], indirect=True)
def test_live_cell_coordinator_starts_one_clock_and_runs_frozen_host(prepared_cell, tmp_path, request, monkeypatch):
    from zoo.circle_packing.live_cell import start_live_cell
    config, ledger, clock, _runner = prepared_cell
    assert clock is None
    reference = request.node.callspec.params['prepared_cell'] == 'coordinator_fake_vendor'
    arm = 'vendor' if reference else 'mori'
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    with tempfile.TemporaryDirectory(prefix='mori-cell-', dir='/tmp') as workspace:
        if reference:
            config = {**config, 'output': str(tmp_path / 'reference-host'),
                      'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        directory = tmp_path / 'coordinator-supervisor'
        result = start_live_cell(arm, config, directory=directory, api_key='fixture-only-secret')
        assert result['returncode'] == 0 and not result['timeout'] and not result['wrapper_error'], result['stderr']
        report = json.loads(result['stdout'])
        assert report['mode'] == 'live' and report['performance_claim'] is False
        claim = ledger.cell_deadline_claim(f'{arm}-0')
        assert claim is not None and claim['plan_ref'] == config['ref']
        before = ledger.snapshot()['journal_head']
        with pytest.raises(ValueError):
            start_live_cell(arm, config, directory=tmp_path / 'retry', api_key='fixture-only-secret')
        assert ledger.snapshot()['journal_head'] == before


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['coordinator_fake_mori', 'coordinator_fake_vendor'], indirect=True)
def test_resume_original_unstarted_cell_runs_under_its_existing_clock(prepared_cell, tmp_path, request, monkeypatch):
    from zoo.circle_packing.live_cell import resume_unstarted_live_cell
    config, ledger, clock, _runner = prepared_cell
    assert clock is None
    reference = request.node.callspec.params['prepared_cell'] == 'coordinator_fake_vendor'
    arm = 'vendor' if reference else 'mori'
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    with tempfile.TemporaryDirectory(prefix='mori-resume-', dir='/tmp') as workspace:
        if reference:
            config = {**config, 'output': str(tmp_path / 'reference-host'),
                      'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        lifecycle = CellLifecycle(ledger)
        monkeypatch.setattr(lifecycle, 'create', lambda _: (_ for _ in ()).throw(SystemExit('before claim')))
        with pytest.raises(SystemExit):
            CellDeadline.start(ContinuationStore(config['clock']), lifecycle=lifecycle,
                cell_id=f'{arm}-0', plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
        saved = next(row['payload'] for row in ContinuationStore(config['clock']).read()
                     if row['kind'] == 'circle_cell_deadline_started')
        assert ledger.cell_deadline_claim(f'{arm}-0') is None
        result = resume_unstarted_live_cell(arm, config, directory=tmp_path / 'resumed-supervisor',
                                            api_key='fixture-only-secret')
        assert result['returncode'] == 0 and not result['timeout'] and not result['wrapper_error'], result['stderr']
        claim = ledger.cell_deadline_claim(f'{arm}-0')
        assert claim['record_sha256'] == saved['record_sha256']
        events = list(ContinuationStore(config['clock']).read())
        assert [row['payload'] for row in events if row['kind'] == 'circle_cell_deadline_started'] == [saved]
        with pytest.raises(ValueError, match='already.*claim'):
            resume_unstarted_live_cell(arm, config, directory=tmp_path / 'repeated', api_key='fixture-only-secret')


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live_timeout', 'reference_fake_live_timeout'], indirect=True)
def test_outer_deadline_during_provider_call_preserves_pending(prepared_cell, tmp_path, request, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from zoo.circle_packing.mori_supervisor import launch_live_controller, launch_reference_live_controller
    config, ledger, clock, _runner = prepared_cell
    reference = request.node.callspec.params['prepared_cell'] == 'reference_fake_live_timeout'
    if reference:
        clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
            cell_id='vendor-0', plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    with tempfile.TemporaryDirectory(prefix='mori-timeout-', dir='/tmp') as workspace:
        if reference:
            config = {**config, 'clock': str(clock._store.path), 'output': str(tmp_path / 'reference-host'),
                      'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        launch = launch_reference_live_controller if reference else launch_live_controller
        directory = tmp_path / 'timeout-supervisor'
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(launch, config, deadline=clock, directory=directory, api_key='fixture-only-secret')
            marker, end = tmp_path / 'provider-inflight', time.monotonic() + 35
            while not marker.exists() and time.monotonic() < end:
                if future.done():
                    future.result()
                    raise AssertionError('supervisor exited before fake request reached transport')
                time.sleep(.05)
            assert marker.exists()
            before = ledger.snapshot()
            assert len(before['pending_calls']) == 1
            assert before['reserved_micro_cny'] > 0
            result = future.result(timeout=65)
        assert result['timeout'] is True
        after = ledger.snapshot()
        assert after['pending_calls'] == before['pending_calls']
        assert after['reserved_micro_cny'] == before['reserved_micro_cny']
        assert after['settled_upper_bound_micro_cny'] == before['settled_upper_bound_micro_cny']
        events = list(ContinuationStore(directory / 'controller.jsonl').read())
        kinds = [event['kind'] for event in events]
        assert kinds.count('executor_process_started') == 1
        assert kinds.index('executor_containment_verified') < kinds.index('executor_process_finished')
        start = next(event['payload'] for event in events if event['kind'] == 'executor_process_started')
        assert not Path(start['containment_binding']['containment_group']).exists()


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live_sandbox_timeout',
                                           'reference_fake_live_sandbox_timeout'], indirect=True)
def test_outer_deadline_terminates_active_sandbox(prepared_cell, tmp_path, request, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from zoo.circle_packing.mori_supervisor import launch_live_controller, launch_reference_live_controller
    config, ledger, clock, _runner = prepared_cell
    reference = request.node.callspec.params['prepared_cell'] == 'reference_fake_live_sandbox_timeout'
    if reference:
        clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
            cell_id='vendor-0', plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    with tempfile.TemporaryDirectory(prefix='mori-sandbox-timeout-', dir='/tmp') as workspace:
        if reference:
            config = {**config, 'clock': str(clock._store.path), 'output': str(tmp_path / 'reference-host'),
                      'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        launch = launch_reference_live_controller if reference else launch_live_controller
        directory = tmp_path / 'sandbox-timeout-supervisor'
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(launch, config, deadline=clock, directory=directory, api_key='fixture-only-secret')
            end = time.monotonic() + 35
            markers = []
            while time.monotonic() < end:
                markers = list(tmp_path.rglob('sandbox-start')) + list(Path(workspace).rglob('sandbox-start'))
                if markers:
                    break
                if future.done():
                    raise AssertionError(f'supervisor exited before sandbox started: {future.result()}')
                time.sleep(.05)
            assert markers and markers[0].read_text() == 'running'
            before = ledger.snapshot()
            result = future.result(timeout=65)
        assert result['timeout'] is True
        after = ledger.snapshot()
        assert after['pending_calls'] == before['pending_calls']
        assert after['settled_upper_bound_micro_cny'] == before['settled_upper_bound_micro_cny']
        events = list(ContinuationStore(directory / 'controller.jsonl').read())
        kinds = [row['kind'] for row in events]
        assert kinds.count('executor_process_started') == 1
        assert kinds.index('executor_containment_verified') < kinds.index('executor_process_finished')
        start = next(row['payload'] for row in events if row['kind'] == 'executor_process_started')
        assert not Path(start['containment_binding']['containment_group']).exists()
        assert not (Path(config['output']) / 'replay-input.json').exists()
        assert not (Path(config['output']) / 'reference-currency.json').exists()


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live_final_timeout',
                                           'reference_fake_live_final_timeout'], indirect=True)
def test_outer_deadline_before_final_validation_keeps_result_unfinished(prepared_cell, tmp_path, request, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from zoo.circle_packing.mori_supervisor import launch_live_controller, launch_reference_live_controller
    config, ledger, clock, _runner = prepared_cell
    reference = request.node.callspec.params['prepared_cell'] == 'reference_fake_live_final_timeout'
    if reference:
        clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
            cell_id='vendor-0', plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    with tempfile.TemporaryDirectory(prefix='mori-final-timeout-', dir='/tmp') as workspace:
        if reference:
            config = {**config, 'clock': str(clock._store.path), 'output': str(tmp_path / 'reference-host'),
                      'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        launch = launch_reference_live_controller if reference else launch_live_controller
        directory = tmp_path / 'final-timeout-supervisor'
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(launch, config, deadline=clock, directory=directory, api_key='fixture-only-secret')
            end = time.monotonic() + 50
            markers = []
            while time.monotonic() < end:
                markers = list(tmp_path.rglob('before-final-marker'))
                if markers:
                    break
                if future.done():
                    raise AssertionError(f'supervisor exited before final boundary: {future.result()}')
                time.sleep(.05)
            assert markers and markers[0].read_text() == 'ready'
            before = ledger.snapshot()
            result = future.result(timeout=75)
        assert result['timeout'] is True
        after = ledger.snapshot()
        assert after['pending_calls'] == before['pending_calls']
        assert after['settled_upper_bound_micro_cny'] == before['settled_upper_bound_micro_cny']
        if reference:
            run = ledger.reference_authority_claim('vendor-0')['currency_run_id']
            assert ledger.reference_selection(run) is None
        else:
            events = list(ContinuationStore(Path(config['output']) / 'framework' / 'x1.jsonl').read())
            assert len([row for row in events if row['kind'] == 'metric_final_frozen']) == 1
            assert not [row for row in events if row['kind'] == 'metric_final_completed']
        events = list(ContinuationStore(directory / 'controller.jsonl').read())
        kinds = [row['kind'] for row in events]
        assert kinds.index('executor_containment_verified') < kinds.index('executor_process_finished')
        start = next(row['payload'] for row in events if row['kind'] == 'executor_process_started')
        assert not Path(start['containment_binding']['containment_group']).exists()


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live_inflight', 'reference_fake_live_inflight'], indirect=True)
def test_inflight_provider_interruption_preserves_original_pending_charge(prepared_cell, tmp_path, request):
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.mori_supervisor import reconcile_live_containment
    config, ledger, clock, _runner = prepared_cell
    reference = request.node.callspec.params['prepared_cell'] == 'reference_fake_live_inflight'
    cell = 'vendor-0' if reference else 'mori-0'
    if reference:
        clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
            cell_id=cell, plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
    with tempfile.TemporaryDirectory(prefix='mori-inflight-', dir='/tmp') as workspace:
        if reference:
            config = {**config, 'clock': str(clock._store.path), 'output': str(tmp_path / 'reference-host'),
                      'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        setup, directory = tmp_path / 'inflight-config.json', tmp_path / 'inflight-supervisor'
        setup.write_text(json.dumps(config))
        script = '''import json,sys
from pathlib import Path
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline,CellLifecycle
from zoo.circle_packing.mori_supervisor import launch_live_controller,launch_reference_live_controller
from zoo.mle_bench_lite.cny_budget import CampaignBudget
c=json.loads(Path(sys.argv[1]).read_text()); l=CampaignBudget(c['ledger']); cell=sys.argv[3]
d=CellDeadline.restore(ContinuationStore(c['clock']),lifecycle=CellLifecycle(l),
    cell_id=cell,plan_ref=c['ref'],seconds=c['plan']['limits']['wallclock_seconds'])
launch=(launch_reference_live_controller if cell.startswith('vendor-') else launch_live_controller)
launch(c,deadline=d,directory=Path(sys.argv[2]),api_key='fixture-only-secret')
'''
        env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'PYTHONHASHSEED': '0',
               'PYTHONDONTWRITEBYTECODE': '1'}
        owner = subprocess.Popen([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
            str(setup), str(directory), cell], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            marker, end = tmp_path / 'provider-inflight', time.monotonic() + 120
            while not marker.exists() and time.monotonic() < end:
                if owner.poll() is not None:
                    raise AssertionError('supervisor exited before fake request reached transport')
                time.sleep(.05)
            assert marker.exists()
            before = ledger.snapshot()
            assert len(before['pending_calls']) == 1
            assert before['reserved_micro_cny'] > 0
            owner.kill(); owner.wait(timeout=10)
            end = time.monotonic() + 10
            while True:
                try:
                    result = reconcile_live_containment(config, deadline=clock, directory=directory)
                    break
                except RuntimeError as error:
                    if 'running original process' not in str(error) or time.monotonic() >= end:
                        raise
                    time.sleep(.05)
            assert result['state'] == 'group_cleaned_cell_unresolved'
            after = ledger.snapshot()
            assert after['pending_calls'] == before['pending_calls']
            assert after['reserved_micro_cny'] == before['reserved_micro_cny']
            assert after['settled_upper_bound_micro_cny'] == before['settled_upper_bound_micro_cny']
            journal = ProcessJournal(ContinuationStore(directory / 'controller.jsonl'))
            assert len(journal.started()) == 1 and not journal.finished_ids()
            with pytest.raises(RuntimeError, match='containment'):
                journal.recover(journal.started()[0])
        finally:
            if owner.poll() is None:
                owner.kill(); owner.wait()
            owner.stdout.close(); owner.stderr.close()


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['paired_fake_live'], indirect=True)
def test_supervised_pair_recalculates_both_arms_at_one_campaign_head(prepared_cell, tmp_path, monkeypatch):
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_runtime import reference_budget_config
    from zoo.circle_packing.mori_final import audit_anchored_mori_geometry
    from zoo.circle_packing.mori_supervisor import launch_live_controller, launch_reference_live_controller
    from zoo.circle_packing.pilot_matrix import snapshot_matrix
    from zoo.circle_packing.pair_audit import audit_pair_snapshot, audit_supervised_pair_snapshot
    from zoo.circle_packing.supervisor_audit import audit_supervisor_result
    from zoo.circle_packing.reference_recovery import recover_reference_snapshot
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView

    config, ledger, mori_clock, _runner = prepared_cell
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
    mori = launch_live_controller(config, deadline=mori_clock, directory=tmp_path / 'mori-supervisor',
                                  api_key='fixture-only-secret')
    assert mori['returncode'] == 0 and not mori['timeout'] and not mori['wrapper_error'], mori['stderr']
    mori_report = json.loads(mori['stdout'])
    vendor_clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'),
        lifecycle=CellLifecycle(ledger), cell_id='vendor-0', plan_ref=config['ref'],
        seconds=config['plan']['limits']['wallclock_seconds'])
    with tempfile.TemporaryDirectory(prefix='mori-pair-', dir='/tmp') as workspace:
        vendor_config = {**config, 'clock': str(vendor_clock._store.path), 'output': str(tmp_path / 'reference'),
                         'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(workspace).resolve())}
        vendor = launch_reference_live_controller(vendor_config, deadline=vendor_clock,
            directory=tmp_path / 'reference-supervisor', api_key='fixture-only-secret')
        assert vendor['returncode'] == 0 and not vendor['timeout'] and not vendor['wrapper_error'], vendor['stderr']
        vendor_report = json.loads(vendor['stdout'])
        reference_bundle = json.loads((Path(vendor_config['output']) / 'reference-currency.json').read_text())
        assert payload_digest(reference_bundle) == vendor_report['currency_bundle_sha256']
        mori_rows = list(ContinuationStore(Path(config['output']) / 'framework' / 'x1.jsonl').read())
        vendor_rows = list(ContinuationStore(Path(vendor_config['output']) / 'events.jsonl').read())
        context = next(row['payload']['invocation']['external_context'] for row in mori_rows
                       if row['kind'] == 'composed_provider_started')
        mori_run, mori_physical_ref = context['currency_run_id'], context['physical_plan_ref']
        vendor_run = ledger.reference_authority_claim('vendor-0')['currency_run_id']
        vendor_physical_ref = next(row['payload']['plan_ref'] for row in vendor_rows
                                   if row['kind'] == 'governed_control_started')
        head = ledger.snapshot()['journal_head']
        def view(run_id, plan_ref):
            return RecordedCurrencyView(ledger.export_governance_evidence(run_id, plan_ref),
                                        expected_run_id=run_id, expected_head=head)
        mori_view, vendor_view = view(mori_run, mori_physical_ref), view(vendor_run, vendor_physical_ref)
        recorded_mori = RecordedCellClock(mori_clock.export_evidence(), mori_view.cell_deadline_claim('mori-0'))
        recorded_vendor = RecordedCellClock(vendor_clock.export_evidence(), vendor_view.cell_deadline_claim('vendor-0'))
        audited_mori_report = audit_supervisor_result(config, directory=tmp_path / 'mori-supervisor',
            view=mori_view, clock=recorded_mori)
        audited_vendor_report = audit_supervisor_result(vendor_config, directory=tmp_path / 'reference-supervisor',
            view=vendor_view, clock=recorded_vendor)
        assert audited_mori_report == mori_report
        assert audited_vendor_report == vendor_report
        with pytest.raises(ValueError):
            audit_supervisor_result({**config, 'seed': 1}, directory=tmp_path / 'mori-supervisor',
                                    view=mori_view, clock=recorded_mori)
        with pytest.raises(ValueError):
            audit_supervisor_result(config, directory=tmp_path / 'reference-supervisor',
                                    view=mori_view, clock=recorded_mori)
        from types import SimpleNamespace
        original_events = list(ContinuationStore(tmp_path / 'mori-supervisor' / 'controller.jsonl').read())
        without_containment = [row for row in original_events if row['kind'] != 'executor_containment_verified']
        import copy
        wrong_terminal = copy.deepcopy(original_events)
        next(row for row in wrong_terminal if row['kind'] == 'executor_process_finished')['payload']['recovered'] = True
        for events in (without_containment, wrong_terminal):
            with monkeypatch.context() as patch:
                patch.setattr('zoo.circle_packing.supervisor_audit.ContinuationStore',
                              lambda _: SimpleNamespace(read=lambda: iter(events)))
                with pytest.raises(ValueError):
                    audit_supervisor_result(config, directory=tmp_path / 'mori-supervisor',
                                            view=mori_view, clock=recorded_mori)
        assert ledger.snapshot()['journal_head'] == head
        def forbidden(*args, **kwargs):
            raise AssertionError('independent pair audit attempted external work')
        monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
        monkeypatch.setattr('zoo.circle_packing.domain.CirclePackingDomain.evaluate', forbidden)
        monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', forbidden)
        mori_audit = audit_anchored_mori_geometry(mori_rows, view=mori_view, clock=recorded_mori,
            run_id=mori_run, plan=config['plan'], expected_plan_ref=config['ref'], expected_rows_sha256=payload_digest(mori_rows))
        options, stamp, governance = reference_budget_config(config['plan'], ledger.manifest_binding(), seed=0)
        vendor_audit = recover_reference_snapshot(vendor_view, recorded_vendor, vendor_run, plan=config['plan'],
            expected_plan_ref=config['ref'], worker_directory=vendor_config['worker_directory'],
            options=options, stamp=stamp, governance=governance, rows=vendor_rows)
        assert mori_audit['measurement'] == mori_report['final_measurement'] and mori_report['replay_passed']
        assert vendor_audit['metrics'] == vendor_report['selected_program']['metrics']
        assert vendor_audit['selection_frozen'] and vendor_audit['performance_claim'] is False
        admissions = vendor_audit['admission_trace']
        assert admissions['scope'] == 'host_observed_reference_admissions'
        assert admissions['events'][0]['kind'] == 'seed'
        from zoo.circle_packing.reference_best_audit import audit_reference_best
        # This tests the algorithm against host observations only. Independent
        # evidence binding and full-run certification are separate work.
        host_measurements = {row['id']: {'program_ref': row['program_ref'], 'metrics': row['metrics']}
                             for row in admissions['events'] if row['kind'] != 'migrant'}
        best = audit_reference_best(admissions['events'], evaluated=host_measurements,
                                    selected_id=vendor_report['selected_program']['id'])
        assert best['complete_run_certified'] is False
        trace = vendor_audit['iteration_trace']
        assert trace['scope'] == 'reference_submitted_future_outcomes' and len(trace['iterations']) == 6
        assert trace['controller_run']['stop_reason'] == 'iteration_limit'
        assert trace['controller_run']['reported_completed_iterations'] == 6
        assert len({item['iteration'] for item in trace['iterations']}) == 6
        assert all(item['state'] not in ('unresolved', 'not_submitted') for item in trace['iterations'])
        for item in trace['iterations']:
            parent_path = Path(workspace) / 'host-run' / 'parent-programs' / (item['sampled_parent_sha256'] + '.py')
            assert hashlib.sha256(parent_path.read_bytes()).hexdigest() == item['sampled_parent_sha256']
            assert item['sampled_parent_id']
        prompt_bindings = trace['prompt_bindings']
        provider_requests = {row['payload']['request_sha256'] for row in vendor_rows
                             if row['kind'] == 'composed_provider_started'}
        assert len(prompt_bindings) == 6
        assert all(item['request_sha256'] in provider_requests for item in prompt_bindings)
        assert len(trace['request_bindings']) == 6
        assert trace['stage_bindings']
        receipts = {item['stage_request_id'] for item in trace['iterations'] if 'stage_request_id' in item}
        stage_ids = {row['payload']['request_id'] for row in vendor_rows if row['kind'] == 'host_stage_started'}
        assert receipts and receipts <= stage_ids
        vendor_currency = vendor_view.audit_run(vendor_run, vendor_physical_ref)
        assert not vendor_currency['pending_calls'] and vendor_currency['settled_upper_bound_micro_cny'] > 0
        assert mori_audit['settled_upper_bound_micro_cny'] > 0
        matrix = snapshot_matrix(ledger, config['plan'], expected_plan_ref=config['ref'], expected_head=head)
        assert len(matrix['cells']) == 6
        assert [row['state'] for row in matrix['cells']].count('claimed_outcome_unverified') == 2
        assert [row['state'] for row in matrix['cells']].count('not_claimed') == 4
        pair = audit_pair_snapshot(seed=0, plan=config['plan'], expected_plan_ref=config['ref'],
            mori_rows=mori_rows, mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view,
            mori_clock=recorded_mori, mori_run_id=mori_run, reference_rows=vendor_rows,
            reference_view=vendor_view, reference_clock=recorded_vendor, reference_run_id=vendor_run,
            reference_worker_directory=vendor_config['worker_directory'], reference_bundle=reference_bundle)
        assert pair['performance_claim'] is False and len(pair['cells']) == 6
        assert [row['state'] for row in pair['cells']].count('audited_final_snapshot') == 2
        assert [row['state'] for row in pair['cells']].count('not_claimed') == 4
        assert pair['mori']['sum_radii'] == mori_report['final_measurement']['sum_radii']
        assert pair['reference']['sum_radii'] == vendor_report['selected_program']['metrics']['sum_radii']
        assert any(item['receipt_state'] == 'matched' for item in pair['reference_iteration_receipts']['iterations'])
        provider_links = pair['reference_iteration_provider']['iterations']
        assert len(provider_links) == 6 and all(item['state'] == 'matched' for item in provider_links)
        assert pair['reference_iteration_provider']['unattributed_provider_bindings'] == []
        assert any(item['state'] == 'matched' for item in pair['reference_iteration_stages']['stages'])
        coverage = pair['reference_run_coverage']
        assert coverage['controller_stop_reason'] == 'iteration_limit' and len(coverage['iterations']) == 6
        assert coverage['complete_run_certified'] is False
        assert any(item['submission_state'] == 'worker_error' for item in coverage['iterations'])
        assert pair['reference_accounting_coverage']['iteration_accounting_complete'] is False
        assert any(reason.endswith('_error_phase_unverified')
                   for reason in pair['reference_accounting_coverage']['reasons'])
        assert pair['reference_accounting_coverage']['complete_run_certified'] is False
        supervised = audit_supervised_pair_snapshot(mori_config=config, reference_config=vendor_config,
            mori_supervisor_directory=tmp_path / 'mori-supervisor',
            reference_supervisor_directory=tmp_path / 'reference-supervisor', seed=0,
            plan=config['plan'], expected_plan_ref=config['ref'], mori_rows=mori_rows,
            mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view, mori_clock=recorded_mori,
            mori_run_id=mori_run, reference_rows=vendor_rows, reference_view=vendor_view,
            reference_clock=recorded_vendor, reference_run_id=vendor_run,
            reference_worker_directory=vendor_config['worker_directory'], reference_bundle=reference_bundle)
        assert supervised['scope'] == 'paired_supervised_anchored_final_snapshots'
        assert supervised['mori']['candidate'] == mori_report['candidate']
        assert supervised['performance_claim'] is False
        patches = supervised['reference_patch_outcomes']['iterations']
        assert len(patches) == 6
        assert all(item['patch_state'] == 'candidate' or item['worker_error_explained'] for item in patches)
        assert supervised['reference_accounting_coverage']['iteration_accounting_complete'] is True
        assert supervised['reference_accounting_coverage']['complete_run_certified'] is False
        replay_input = json.loads((Path(config['output']) / 'replay-input.json').read_text())
        replay_payload = {'mori_config': config, 'reference_config': vendor_config,
            'mori_directory': str(tmp_path / 'mori-supervisor'),
            'reference_directory': str(tmp_path / 'reference-supervisor'),
            'mori_rows': mori_rows, 'reference_rows': vendor_rows,
            'mori_view': json.loads(mori_view._evidence), 'reference_view': json.loads(vendor_view._evidence),
            'mori_clock': mori_clock.export_evidence(), 'reference_clock': vendor_clock.export_evidence(),
            'mori_run': mori_run, 'reference_run': vendor_run, 'reference_bundle': reference_bundle,
            'replay_input': replay_input, 'head': head}
        replay_payload_path = tmp_path / 'paired-replay-input.json'
        replay_payload_path.write_text(json.dumps(replay_payload))
        script = '''import copy,json,os,socket,sys
from pathlib import Path
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.pair_audit import record_first_pair_audit
from zoo.circle_packing import pair_recorded
from zoo.circle_packing.mori_cycle_audit import audit_completed_mori_cycles
from zoo.circle_packing.pilot_plan import require_first_pair_audit
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
def forbidden(*args, **kwargs): raise AssertionError('paired replay attempted external work')
socket.socket.connect=forbidden
GovernedCNYProvider.perform_request=forbidden
CirclePackingDomain.evaluate=forbidden
p=json.loads(Path(sys.argv[1]).read_text()); c=p['mori_config']; v=p['reference_config']
ledger=CampaignBudget(c['ledger'])
runner=SandboxRunner.for_campaign_runtime(ledger,runtime=c['runtime'],manifest=c['runtime_manifest'],base_python='/usr/bin/python3.12')
mv=RecordedCurrencyView(p['mori_view'],expected_run_id=p['mori_run'],expected_head=p['head'])
rv=RecordedCurrencyView(p['reference_view'],expected_run_id=p['reference_run'],expected_head=p['head'])
mc=RecordedCellClock(p['mori_clock'],mv.cell_deadline_claim('mori-0'))
rc=RecordedCellClock(p['reference_clock'],rv.cell_deadline_claim('vendor-0'))
args=dict(mori_config=c,reference_config=v,mori_supervisor_directory=p['mori_directory'],
 reference_supervisor_directory=p['reference_directory'],seed=0,plan=c['plan'],expected_plan_ref=c['ref'],
 mori_rows=p['mori_rows'],mori_rows_sha256=payload_digest(p['mori_rows']),mori_view=mv,mori_clock=mc,
 mori_run_id=p['mori_run'],reference_rows=p['reference_rows'],reference_view=rv,reference_clock=rc,
 reference_run_id=p['reference_run'],reference_worker_directory=v['worker_directory'],reference_bundle=p['reference_bundle'])
cycles=audit_completed_mori_cycles(p['replay_input'],expected_input_sha256=payload_digest(p['replay_input']),
 view=mv,clock=mc,run_id=p['mori_run'],plan=c['plan'],expected_plan_ref=c['ref'])
assert cycles['scope']=='caller_pinned_mori_cycle_commits' and len(cycles['cycles'])==7
assert [row['cycle'] for row in cycles['cycles']]==list(range(7))
assert any(row['evaluation_status']!='ok' for row in cycles['cycles'])
missing=copy.deepcopy(p['replay_input'])
missing['rows']=[row for row in missing['rows'] if not (row['kind']=='composed_cycle_started' and row['payload']['cycle']==3)]
try:
 audit_completed_mori_cycles(missing,expected_input_sha256=payload_digest(missing),view=mv,clock=mc,
                             run_id=p['mori_run'],plan=c['plan'],expected_plan_ref=c['ref'])
except ValueError: pass
else: raise AssertionError('missing original cycle accepted')
bad=copy.deepcopy(p['replay_input']); bad['rows'].pop()
try:
 record_first_pair_audit(replay_input=bad,ledger=ledger,runner=runner,replay_output=Path(sys.argv[2]+'-bad'),**args)
except ValueError: pass
else: raise AssertionError('altered replay accepted')
assert not Path(sys.argv[2]+'-bad').exists()
assert ledger.snapshot()['journal_head']==p['head'] and ledger.first_pair_audit() is None
try: require_first_pair_audit(1, ledger=ledger, expected_plan_ref=c['ref'])
except ValueError: pass
else: raise AssertionError('later seed accepted without an audit')
sys.argv=['pair_recorded',p['mori_directory'],p['reference_directory'],json.dumps(p['head']),sys.argv[2]]
os.environ['DEEPSEEK_API_KEY']='fixture-only-secret'
pair_recorded.main()
assert 'DEEPSEEK_API_KEY' not in os.environ
proof=ledger.first_pair_audit()
result=proof['result']
assert result['scope']=='paired_supervised_snapshots_with_independent_replay'
assert result['mori_cycle_coverage']==cycles
assert result['replay']['passed'] and result['replay']['external_calls']==0
assert result['replay']['candidate']==result['mori']['candidate']
assert result['performance_claim'] is False and ledger.first_pair_audit()==proof
assert ledger.snapshot()['journal_head']['seq']==p['head']['seq']+1
for seed in (1,2):
 try: require_first_pair_audit(seed, ledger=ledger, expected_plan_ref=c['ref'])
 except ValueError: pass
 else: raise AssertionError('final snapshots alone must not admit later seeds')
try: require_first_pair_audit(1, ledger=ledger, expected_plan_ref='sha256:'+'0'*64)
except ValueError: pass
else: raise AssertionError('audit for a different plan accepted')
try: ledger._record_first_pair_audit(proof, expected_head=p['head'])
except ValueError: pass
else: raise AssertionError('duplicate or stale pair audit accepted')
current=ledger.snapshot()['journal_head']
updated=copy.deepcopy(proof)
updated['result']['journal_head']=current
ledger._record_first_pair_audit(updated,expected_head=current)
assert ledger.first_pair_audit()==updated and ledger.snapshot()['journal_head']['seq']==current['seq']+1
bad_identity=copy.deepcopy(updated); bad_identity['mori_rows_sha256']='0'*64
current=ledger.snapshot()['journal_head']; bad_identity['result']['journal_head']=current
try: ledger._record_first_pair_audit(bad_identity,expected_head=current)
except ValueError: pass
else: raise AssertionError('superseding audit changed original evidence identity')
assert ledger.snapshot()['journal_head']==current
'''
        env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'PYTHONHASHSEED': '0',
               'PYTHONDONTWRITEBYTECODE': '1'}
        independent = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
            str(replay_payload_path), str(tmp_path / 'paired-independent-replay')], env=env, cwd=tmp_path,
            capture_output=True, text=True, timeout=240)
        assert independent.returncode == 0, independent.stderr
        with pytest.raises(ValueError):
            audit_pair_snapshot(seed=1, plan=config['plan'], expected_plan_ref=config['ref'],
                mori_rows=mori_rows, mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view,
                mori_clock=recorded_mori, mori_run_id=mori_run, reference_rows=vendor_rows,
                reference_view=vendor_view, reference_clock=recorded_vendor, reference_run_id=vendor_run,
                reference_worker_directory=vendor_config['worker_directory'], reference_bundle=reference_bundle)
        with pytest.raises(ValueError):
            audit_pair_snapshot(seed=0, plan=config['plan'], expected_plan_ref=config['ref'],
                mori_rows=mori_rows, mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view,
                mori_clock=recorded_mori, mori_run_id=mori_run, reference_rows=vendor_rows,
                reference_view=mori_view, reference_clock=recorded_vendor, reference_run_id=vendor_run,
                reference_worker_directory=vendor_config['worker_directory'], reference_bundle=reference_bundle)
        import copy
        altered_bundle = copy.deepcopy(reference_bundle)
        altered_bundle['calls'][0]['prepared']['bound']['reserved_micro_cny'] += 1
        with pytest.raises(ValueError):
            audit_pair_snapshot(seed=0, plan=config['plan'], expected_plan_ref=config['ref'],
                mori_rows=mori_rows, mori_rows_sha256=payload_digest(mori_rows), mori_view=mori_view,
                mori_clock=recorded_mori, mori_run_id=mori_run, reference_rows=vendor_rows,
                reference_view=vendor_view, reference_clock=recorded_vendor, reference_run_id=vendor_run,
                reference_worker_directory=vendor_config['worker_directory'], reference_bundle=altered_bundle)
        for root in (tmp_path / 'mori-supervisor', Path(config['output']), tmp_path / 'reference-supervisor',
                     Path(vendor_config['output']), Path(vendor_config['worker_directory']), Path(workspace)):
            for file in root.rglob('*'):
                if file.is_file() and not file.is_symlink():
                    assert b'fixture-only-secret' not in file.read_bytes(), f'fixture key persisted in {file}'


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['reference_fake_live_stall'], indirect=True)
def test_killed_reference_supervisor_cleans_group_without_retry(prepared_cell, tmp_path):
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.mori_supervisor import reconcile_live_containment
    config, ledger, _clock, _runner = prepared_cell
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
    with tempfile.TemporaryDirectory(prefix='mori-ref-', dir='/tmp') as path:
        config = {**config, 'clock': str(clock._store.path), 'output': str(tmp_path / 'reference-host'),
                  'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(path).resolve())}
        setup, directory = tmp_path / 'reference-config.json', tmp_path / 'reference-supervisor'
        setup.write_text(json.dumps(config))
        script = '''import json,sys
from pathlib import Path
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline,CellLifecycle
from zoo.circle_packing.mori_supervisor import launch_reference_live_controller
from zoo.mle_bench_lite.cny_budget import CampaignBudget
c=json.loads(Path(sys.argv[1]).read_text()); l=CampaignBudget(c['ledger'])
d=CellDeadline.restore(ContinuationStore(c['clock']),lifecycle=CellLifecycle(l),
    cell_id='vendor-0',plan_ref=c['ref'],seconds=c['plan']['limits']['wallclock_seconds'])
launch_reference_live_controller(c,deadline=d,directory=Path(sys.argv[2]),api_key='fixture-only-secret')
'''
        env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'PYTHONHASHSEED': '0',
               'PYTHONDONTWRITEBYTECODE': '1'}
        owner = subprocess.Popen([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
                                  str(setup), str(directory)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            marker, end = tmp_path / 'reference-ready', time.monotonic() + 60
            while not marker.exists() and time.monotonic() < end:
                if owner.poll() is not None:
                    raise AssertionError('reference supervisor exited before host became ready')
                time.sleep(.05)
            assert marker.exists()
            owner.kill(); owner.wait(timeout=10)
            end = time.monotonic() + 10
            while True:
                try:
                    result = reconcile_live_containment(config, deadline=clock, directory=directory)
                    break
                except RuntimeError as error:
                    if 'running original process' not in str(error) or time.monotonic() >= end:
                        raise
                    time.sleep(.05)
            assert result['state'] == 'group_cleaned_cell_unresolved'
            journal = ProcessJournal(ContinuationStore(directory / 'controller.jsonl'))
            started = journal.started()
            assert len(started) == 1 and not journal.finished_ids()
            with pytest.raises(RuntimeError, match='containment'):
                journal.recover(started[0])
            assert ledger.reference_host_claim('vendor-0') is not None
            assert ledger.reference_authority_claim('vendor-0') is not None
            assert ledger.cell_worker_claim('vendor-0') is None
            assert not ledger.snapshot()['pending_calls']
            with pytest.raises(ValueError, match='host'):
                ledger.claim_reference_host('vendor-0', clock._record['record_sha256'], 'b' * 64)
        finally:
            if owner.poll() is None:
                owner.kill(); owner.wait()
            owner.stdout.close(); owner.stderr.close()


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['reference_fake_live'], indirect=True)
def test_reference_supervisor_runs_live_host_with_fake_transport_and_original_authorities(prepared_cell, tmp_path,
                                                                                       monkeypatch):
    from zoo.circle_packing.mori_supervisor import launch_reference_live_controller
    config, ledger, _clock, _runner = prepared_cell
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref=config['ref'], seconds=config['plan']['limits']['wallclock_seconds'])
    with tempfile.TemporaryDirectory(prefix='mori-ref-', dir='/tmp') as path:
        config = {**config, 'clock': str(clock._store.path), 'output': str(tmp_path / 'reference-host'),
                  'worker_directory': str(tmp_path / 'reference-worker'), 'workspace': str(Path(path).resolve())}
        monkeypatch.setattr('zoo.circle_packing.host_runtime._require_reference_live_gate', lambda: None)
        directory = tmp_path / 'reference-supervisor'
        process = launch_reference_live_controller(config, deadline=clock, directory=directory,
                                                    api_key='fixture-only-secret')
        assert process['returncode'] == 0 and not process['timeout'] and not process['wrapper_error'], process['stderr']
        result = json.loads(process['stdout'])
        assert result['mode'] == 'live' and result['performance_claim'] is False and result['state'] == 'completed'
        assert result['selected_program']['metrics']['validity'] == 1.0
        from core.x1.checkpoint import payload_digest
        from zoo.circle_packing.reference_currency import audit_reference_currency
        bundle = json.loads((Path(config['output']) / 'reference-currency.json').read_text())
        assert payload_digest(bundle) == result['currency_bundle_sha256']
        rows = list(ContinuationStore(Path(config['output']) / 'events.jsonl').read())
        def forbidden(*args, **kwargs):
            raise AssertionError('independent reference currency audit attempted live work')
        monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
        monkeypatch.setattr('zoo.circle_packing.host_physical.run_stage', forbidden)
        audited = audit_reference_currency(bundle, rows=rows, expected_head=ledger.snapshot()['journal_head'],
                                            expected_plan_ref=config['ref'], plan=config['plan'], seed=0)
        assert audited['settled_upper_bound_micro_cny'] == config['plan']['iterations'] * 38
        script = '''import json,socket,sys
from pathlib import Path
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.reference_currency import audit_reference_currency
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
def forbidden(*args,**kwargs): raise AssertionError('reference audit attempted external work')
socket.socket.connect=forbidden
GovernedCNYProvider.perform_request=forbidden
c=json.loads(Path(sys.argv[1]).read_text()); b=json.loads(Path(sys.argv[2]).read_text())
rows=list(ContinuationStore(sys.argv[3]).read())
print(json.dumps(audit_reference_currency(b,rows=rows,expected_head=json.loads(sys.argv[4]),
    expected_plan_ref=c['ref'],plan=c['plan'],seed=c['seed']),sort_keys=True))
'''
        audit_env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'PYTHONHASHSEED': '0',
                     'PYTHONDONTWRITEBYTECODE': '1'}
        independent = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
            str(directory / 'config.json'), str(Path(config['output']) / 'reference-currency.json'),
            str(Path(config['output']) / 'events.jsonl'), json.dumps(ledger.snapshot()['journal_head'])],
            env=audit_env, cwd=tmp_path, capture_output=True, text=True, timeout=120)
        assert independent.returncode == 0, independent.stderr
        assert json.loads(independent.stdout) == audited
        assert ledger.snapshot()['settled_upper_bound_micro_cny'] == config['plan']['iterations'] * 38
        assert not ledger.snapshot()['pending_calls']
        assert ledger.reference_host_claim('vendor-0') is not None
        assert ledger.cell_worker_claim('vendor-0') is not None
        events = list(ContinuationStore(directory / 'controller.jsonl').read())
        kinds = [event['kind'] for event in events]
        assert kinds.index('executor_containment_verified') < kinds.index('executor_process_finished')
        for root in (directory, Path(config['output']), Path(config['worker_directory']), Path(path)):
            for file in root.rglob('*'):
                if file.is_file() and not file.is_symlink():
                    assert b'fixture-only-secret' not in file.read_bytes(), f'fixture key persisted in {file}'


@pytest.mark.linux
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live'], indirect=True)
def test_live_supervisor_runs_real_entry_with_test_source_and_no_network(prepared_cell, tmp_path, monkeypatch):
    from zoo.circle_packing.mori_supervisor import launch_live_controller
    from zoo.circle_packing.mori_recorded import replay_mori_snapshot
    from zoo.circle_packing.mori_final import recalculate_mori_geometry, audit_anchored_mori_geometry
    config, ledger, clock, _runner = prepared_cell
    monkeypatch.setattr('zoo.circle_packing.mori_live_worker._require_live_gate', lambda _: None)
    directory = tmp_path / 'live-supervisor'
    result = launch_live_controller(config, deadline=clock, directory=directory, api_key='fixture-only-secret')
    assert result['returncode'] == 0 and not result['timeout'] and not result.get('wrapper_error'), result['stderr']
    events = list(ContinuationStore(directory / 'controller.jsonl').read())
    kinds = [event['kind'] for event in events]
    assert kinds.index('executor_containment_verified') < kinds.index('executor_process_finished')
    started = next(event['payload'] for event in events if event['kind'] == 'executor_process_started')
    from core.x1.checkpoint import payload_digest
    assert payload_digest(started['containment_binding']) == ledger.cell_worker_claim('mori-0')['worker_ref']
    assert not Path(started['containment_binding']['containment_group']).exists()
    report = json.loads(result['stdout'])
    assert report['mode'] == 'live' and report['performance_claim'] is False
    assert report['candidate'] and report['final_state'] == 'completed' and report['replay_passed']
    assert report['final_measurement']['validity'] == 1.0
    replay_path = Path(config['output']) / 'replay-input.json'
    assert replay_path.is_file()
    replay_input = json.loads(replay_path.read_text())
    from core.x1.checkpoint import payload_digest
    assert payload_digest(replay_input) == report['replay_input_sha256']
    replay_head = replay_input['currency_bundle']['currency_evidence']['journal_head']
    assert replay_head == ledger.snapshot()['journal_head']
    clock_before = Path(config['clock']).read_bytes()
    script = '''import os,socket,sys
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing import mori_recorded
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
def forbidden(*args,**kwargs): raise AssertionError('independent replay attempted external work')
socket.socket.connect=forbidden
GovernedCNYProvider.perform_request=forbidden
CirclePackingDomain.evaluate=forbidden
mori_recorded.main()
assert 'DEEPSEEK_API_KEY' not in os.environ
'''
    env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'PYTHONHASHSEED': '0',
           'PYTHONDONTWRITEBYTECODE': '1', 'DEEPSEEK_API_KEY': 'fixture-only-secret'}
    independent = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
        str(directory / 'config.json'), str(replay_path), report['replay_input_sha256'],
        json.dumps(replay_head), str(tmp_path / 'independent-replay')],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=240)
    assert independent.returncode == 0, independent.stderr
    replay_result = json.loads(independent.stdout)
    assert replay_result['passed'] and replay_result['external_calls'] == 0
    assert replay_result['candidate'] == report['candidate']
    assert ledger.snapshot()['journal_head'] == replay_head and Path(config['clock']).read_bytes() == clock_before
    rejected = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
        str(directory / 'config.json'), str(replay_path), '0' * 64, json.dumps(replay_head),
        str(tmp_path / 'rejected-replay')],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=240)
    assert rejected.returncode != 0 and not (tmp_path / 'rejected-replay').exists()
    assert ledger.snapshot()['journal_head'] == replay_head and Path(config['clock']).read_bytes() == clock_before
    wrong_head = {**replay_head, 'sha256': '0' * 64}
    rejected = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
        str(directory / 'config.json'), str(replay_path), report['replay_input_sha256'], json.dumps(wrong_head),
        str(tmp_path / 'wrong-head-replay')], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=240)
    assert rejected.returncode != 0 and not (tmp_path / 'wrong-head-replay').exists()
    assert ledger.snapshot()['journal_head'] == replay_head and Path(config['clock']).read_bytes() == clock_before
    rows = list(ContinuationStore(Path(config['output']) / 'framework' / 'x1.jsonl').read())
    from core.x1.checkpoint import payload_digest
    def forbidden(*args, **kwargs):
        raise AssertionError('geometry recalculation attempted external work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr('zoo.circle_packing.domain.CirclePackingDomain.evaluate', forbidden)
    verified = recalculate_mori_geometry(rows, expected_rows_sha256=payload_digest(rows),
                                         public_range_threshold=config['plan']['public_range_sum_radii'])
    assert verified['measurement'] == report['final_measurement']
    assert verified['candidate'] == report['candidate'] and verified['performance_claim'] is False
    context = next(row['payload']['invocation']['external_context'] for row in rows
                   if row['kind'] == 'composed_provider_started')
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    run_id, physical_plan_ref = context['currency_run_id'], context['physical_plan_ref']
    head = ledger.snapshot()['journal_head']
    evidence = ledger.export_governance_evidence(run_id, physical_plan_ref)
    view = RecordedCurrencyView(evidence, expected_run_id=run_id, expected_head=head)
    recorded_clock = RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim('mori-0'))
    anchored = audit_anchored_mori_geometry(rows, view=view, clock=recorded_clock, run_id=run_id,
        plan=config['plan'], expected_plan_ref=config['ref'], expected_rows_sha256=payload_digest(rows))
    assert anchored['measurement'] == report['final_measurement']
    assert anchored['settled_upper_bound_micro_cny'] == ledger.snapshot()['settled_upper_bound_micro_cny']
    assert anchored['performance_claim'] is False
    with pytest.raises(ValueError, match='pinned'):
        audit_anchored_mori_geometry(rows, view=RecordedCurrencyView(evidence), clock=recorded_clock, run_id=run_id,
            plan=config['plan'], expected_plan_ref=config['ref'], expected_rows_sha256=payload_digest(rows))
    with pytest.raises(ValueError, match='journal'):
        recalculate_mori_geometry(rows, expected_rows_sha256='0' * 64,
                                 public_range_threshold=config['plan']['public_range_sum_radii'])
    import copy
    altered = copy.deepcopy(rows)
    dev = next(row['payload']['evidence']['evidence'] for row in altered
               if row['kind'] == 'composed_physical_evidence' and row['payload']['request']['split_id'] == 'dev'
               and row['payload']['evidence']['evidence']['candidate_id'] == report['candidate'])
    dev['eval_result']['contract']['private']['data']['record']['geometry']['radii'][0] += .01
    with pytest.raises(ValueError):
        recalculate_mori_geometry(altered, expected_rows_sha256=payload_digest(altered),
                                 public_range_threshold=config['plan']['public_range_sum_radii'])
    altered = copy.deepcopy(rows)
    final = next(row['payload'] for row in altered if row['kind'] == 'metric_final_completed')
    final['evidence']['evidence']['eval_result']['metrics']['test/sum_radii'] += .01
    with pytest.raises(ValueError):
        recalculate_mori_geometry(altered, expected_rows_sha256=payload_digest(altered),
                                 public_range_threshold=config['plan']['public_range_sum_radii'])
    altered = copy.deepcopy(rows)
    final_intent = next(row['payload']['intent_id'] for row in altered
                        if row['kind'] == 'composed_physical_evidence'
                        and row['payload']['request']['split_id'] == 'final_audit')
    proof = next(row['payload'] for row in altered if row['kind'] == 'governed_work_eligibility'
                 and row['payload'].get('phase') == 'evaluation' and row['payload'].get('intent_id') == final_intent)
    proof['fingerprint'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError):
        audit_anchored_mori_geometry(altered, view=view, clock=recorded_clock, run_id=run_id,
            plan=config['plan'], expected_plan_ref=config['ref'], expected_rows_sha256=payload_digest(altered))
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
@pytest.mark.parametrize('prepared_cell', ['supervised_fake_live_stall'], indirect=True)
def test_killed_live_supervisor_leaves_cell_unresolved_and_group_can_be_cleaned(prepared_cell, tmp_path):
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.mori_supervisor import reconcile_live_containment
    config, ledger, clock, _runner = prepared_cell
    setup, directory = tmp_path / 'crash-config.json', tmp_path / 'crash-supervisor'
    setup.write_text(json.dumps(config))
    script = '''import json,sys
from pathlib import Path
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline,CellLifecycle
from zoo.circle_packing.mori_supervisor import launch_live_controller
from zoo.mle_bench_lite.cny_budget import CampaignBudget
c=json.loads(Path(sys.argv[1]).read_text()); l=CampaignBudget(c['ledger'])
d=CellDeadline.restore(ContinuationStore(c['clock']),lifecycle=CellLifecycle(l),
    cell_id='mori-0',plan_ref=c['ref'],seconds=c['plan']['limits']['wallclock_seconds'])
launch_live_controller(c,deadline=d,directory=Path(sys.argv[2]),api_key='fixture-only-secret')
'''
    env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'], 'PYTHONHASHSEED': '0',
           'PYTHONDONTWRITEBYTECODE': '1'}
    owner = subprocess.Popen([str(Path(config['runtime']) / 'bin' / 'python'), '-c', script,
                              str(setup), str(directory)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        marker, end = tmp_path / 'controller-ready', time.monotonic() + 60
        while not marker.exists() and time.monotonic() < end:
            if owner.poll() is not None:
                raise AssertionError('test supervisor exited before controller became ready')
            time.sleep(.05)
        assert marker.exists()
        owner.kill()
        owner.wait(timeout=10)
        end = time.monotonic() + 10
        while True:
            try:
                result = reconcile_live_containment(config, deadline=clock, directory=directory)
                break
            except RuntimeError as error:
                if 'running original process' not in str(error) or time.monotonic() >= end:
                    raise
                time.sleep(.05)
        assert result['state'] == 'group_cleaned_cell_unresolved'
        journal = ProcessJournal(ContinuationStore(directory / 'controller.jsonl'))
        started = journal.started()
        assert len(started) == 1 and not journal.finished_ids()
        with pytest.raises(RuntimeError, match='containment'):
            journal.recover(started[0])
        assert not ledger.snapshot()['pending_calls']
    finally:
        if owner.poll() is None:
            owner.kill(); owner.wait()
        owner.stdout.close(); owner.stderr.close()


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
    from zoo.circle_packing.host_runtime import (build_reference_authorities, reference_budget_config, run_reference_cell_fixture,
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
        from dataclasses import asdict
        options, stamp, governance = reference_budget_config(plan, ledger.manifest_binding(), seed=0)
        assert options == authority.budget.options and stamp == asdict(authority.budget.stamp)
        assert governance == authority.budget._governed.config
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
        from zoo.circle_packing.reference_currency import audit_reference_currency
        bundle = authority.bridge.reference_audit_bundle()
        currency = audit_reference_currency(bundle, rows=list(authority.budget.store.read()),
            expected_head=ledger.snapshot()['journal_head'], expected_plan_ref=config['ref'], plan=plan, seed=0)
        assert currency['settled_upper_bound_micro_cny'] == len(calls) * 38
        assert currency['invocations'] == len(calls) and currency['performance_claim'] is False
        import copy
        changed = copy.deepcopy(bundle)
        changed['calls'][0]['prepared']['bound']['reserved_micro_cny'] += 1
        with pytest.raises(ValueError):
            audit_reference_currency(changed, rows=list(authority.budget.store.read()),
                expected_head=ledger.snapshot()['journal_head'], expected_plan_ref=config['ref'], plan=plan, seed=0)
    finally:
        authority.close()
