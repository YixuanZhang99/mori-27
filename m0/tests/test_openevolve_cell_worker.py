"""Real isolated controller worker with one original campaign claim."""
import time
import os
from pathlib import Path
import subprocess
import shutil
import json
import threading
import sys

import pytest

from core.composition.recovery import ContinuationStore
from test_openevolve_cell_deadline import _lifecycle
from zoo.circle_packing.cell_deadline import CellDeadline, DeadlineExpired


pytestmark = pytest.mark.linux


def setup(tmp_path, seconds):
    clock = ContinuationStore(tmp_path / 'clock.jsonl')
    lifecycle = _lifecycle(clock.path)
    deadline = CellDeadline.start(clock, lifecycle=lifecycle, cell_id='vendor-0',
                                  plan_ref='sha256:' + 'a' * 64, seconds=seconds)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    return deadline, workspace


def test_worker_runs_once_and_original_campaign_retains_claim(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 30)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
                             ['/usr/bin/python3', '-c', "print('completed')"])
    assert result['state'] == 'completed' and result['returncode'] == 0
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is not None
    with pytest.raises(ValueError, match='worker'):
        run_cell_worker(deadline, tmp_path / 'other', workspace,
                        ['/usr/bin/python3', '-c', "print('duplicate')"])


def test_expired_worker_does_not_start_or_consume_claim(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 1)
    time.sleep(1.1)
    with pytest.raises(DeadlineExpired):
        run_cell_worker(deadline, tmp_path / 'worker', workspace,
                        ['/usr/bin/python3', '-c', "open('unexpected','w').write('started')"])
    assert not (workspace / 'unexpected').exists()
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None


def test_expiry_stops_worker_and_preserves_unresolved_result(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 2)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
        ['/usr/bin/python3', '-c', "import time; time.sleep(5); open('late','w').write('late')"])
    assert result['state'] == 'expired_unresolved'
    time.sleep(0.2)
    assert not (workspace / 'late').exists()
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is not None


def test_result_becomes_ineligible_if_deadline_expires_while_reading_it(tmp_path, monkeypatch):
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 2)
    wait = ProcessJournal.wait
    def slow_wait(self, *args):
        result = wait(self, *args)
        time.sleep(2.1)
        return result
    monkeypatch.setattr(ProcessJournal, 'wait', slow_wait)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
                             ['/usr/bin/python3', '-c', "print('completed')"])
    assert result['state'] == 'expired_unresolved'


def test_failed_process_start_journal_does_not_leave_running_worker(tmp_path, monkeypatch):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 30)
    append = ContinuationStore.append
    def fail_started(self, kind, payload):
        if kind == 'executor_process_started':
            time.sleep(0.4)
            raise OSError('fixture journal failure')
        return append(self, kind, payload)
    monkeypatch.setattr(ContinuationStore, 'append', fail_started)
    with pytest.raises(OSError, match='journal failure'):
        run_cell_worker(deadline, tmp_path / 'worker', workspace,
            ['/usr/bin/python3', '-c', "import time; time.sleep(1); open('escaped','w').write('alive')"])
    time.sleep(1.2)
    assert not (workspace / 'escaped').exists()


def test_supervisor_crash_stops_worker_without_restarting_it(tmp_path):
    deadline, workspace = setup(tmp_path, 20)
    source = Path(__file__).resolve().parents[1]
    script = """
import sys
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.cell_worker import run_cell_worker
from zoo.mle_bench_lite.cny_budget import CampaignBudget
clock, campaign, directory, workspace = sys.argv[1:]
deadline = CellDeadline.restore(ContinuationStore(clock), lifecycle=CellLifecycle(CampaignBudget(campaign)),
    cell_id='vendor-0', plan_ref='sha256:' + 'a' * 64, seconds=20)
run_cell_worker(deadline, directory, workspace, ['/usr/bin/python3', '-c',
    "import time; open('ready','w').write('ready'); time.sleep(3); open('escaped','w').write('alive')"])
"""
    process = subprocess.Popen([sys.executable, '-c', script, str(tmp_path / 'clock.jsonl'),
        str(tmp_path / 'campaign.db'), str(tmp_path / 'worker'), str(workspace)],
        env={'PATH': os.defpath, 'PYTHONPATH': str(source)}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        until = time.monotonic() + 10
        while time.monotonic() < until and not (workspace / 'ready').exists():
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode())
            time.sleep(0.02)
        assert (workspace / 'ready').exists()
        process.kill()
        process.wait(timeout=5)
        time.sleep(3.3)
        assert not (workspace / 'escaped').exists()
        assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is not None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_watchdog_does_not_append_currency_journal_on_every_poll(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 30)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
                             ['/usr/bin/python3', '-c', 'import time; time.sleep(1.5)'])
    assert result['state'] == 'completed'
    observations = list(ContinuationStore(tmp_path / 'clock.jsonl').read('circle_cell_deadline_observed'))
    assert len(observations) <= 5


def test_watchdog_clock_regression_stops_worker_and_fails_closed(tmp_path, monkeypatch):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 30)
    monkeypatch.setattr('zoo.circle_packing.cell_worker._clock_ns', lambda: 0)
    with pytest.raises(ValueError, match='regressed'):
        run_cell_worker(deadline, tmp_path / 'worker', workspace,
            ['/usr/bin/python3', '-c', "import time; time.sleep(1); open('late','w').write('alive')"])
    time.sleep(1.2)
    assert not (workspace / 'late').exists()


def test_worker_cannot_start_when_launch_crosses_cell_deadline(tmp_path, monkeypatch):
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 2)
    launch = ProcessJournal.launch
    def delayed_launch(self, *args, **kwargs):
        time.sleep(2.1)
        result = launch(self, *args, **kwargs)
        time.sleep(0.5)
        return result
    monkeypatch.setattr(ProcessJournal, 'launch', delayed_launch)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
                             ['/usr/bin/python3', '-c', "open('late','w').write('started')"])
    assert result['state'] == 'expired_unresolved'
    assert not (workspace / 'late').exists()


def test_wrapper_enforces_deadline_while_start_record_is_blocked(tmp_path, monkeypatch):
    from core.executor.process import ProcessJournal
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 3)
    launch = ProcessJournal.launch
    append = ContinuationStore.append
    def delayed_launch(self, *args, **kwargs):
        time.sleep(1.5)
        return launch(self, *args, **kwargs)
    def blocked_append(self, kind, payload):
        if kind == 'executor_process_started':
            time.sleep(2.8)
        return append(self, kind, payload)
    monkeypatch.setattr(ProcessJournal, 'launch', delayed_launch)
    monkeypatch.setattr(ContinuationStore, 'append', blocked_append)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
        ['/usr/bin/python3', '-c', "import time; time.sleep(1.9); open('late','w').write('alive')"])
    assert result['state'] == 'expired_unresolved'
    assert not (workspace / 'late').exists()


def test_deadline_stops_target_even_if_identity_recording_stalls(tmp_path, monkeypatch):
    import core.executor.process as process_module
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 2)
    source = Path(process_module.__file__).parent
    copied = tmp_path / 'fixture-executor'
    copied.mkdir()
    for name in ('process_wrapper.py', 'seccomp.py', 'process_identity.py'):
        shutil.copy(source / name, copied / name)
    wrapper = copied / 'process_wrapper.py'
    original = wrapper.read_text()
    needle = '    try:\n        ticks = _start_ticks(target.pid)'
    assert needle in original
    wrapper.write_text(original.replace(needle, '    try:\n        time.sleep(3)\n        ticks = _start_ticks(target.pid)'))
    monkeypatch.setattr(process_module, '__file__', str(copied / 'process.py'))
    append = ContinuationStore.append
    def blocked_append(self, kind, payload):
        if kind == 'executor_process_started':
            time.sleep(3.5)
        return append(self, kind, payload)
    monkeypatch.setattr(ContinuationStore, 'append', blocked_append)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
        ['/usr/bin/python3', '-c', "import time; time.sleep(2.4); open('late','w').write('alive')"])
    assert result['state'] == 'expired_unresolved'
    assert not (workspace / 'late').exists()


def test_watchdog_creation_failure_stops_target(tmp_path, monkeypatch):
    import core.executor.process_wrapper as wrapper
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    spec = {'args': [sys.executable, '-c', "import time; time.sleep(1); open('late','w').write('alive')"],
            'cwd': str(tmp_path), 'time_limit': 10, 'resource_limits': {}, 'seccomp_policy': None,
            'seccomp_delivery': None, 'absolute_deadline': {'boot_id': boot,
                'deadline_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME) + 10_000_000_000},
            'stdout_path': str(tmp_path / 'stdout'), 'stderr_path': str(tmp_path / 'stderr'),
            'result_path': str(tmp_path / 'result.json'), 'target_path': str(tmp_path / 'target.json')}
    source = tmp_path / 'spec.json'
    source.write_text(json.dumps(spec))
    monkeypatch.setattr(sys, 'argv', ['wrapper', str(source)])
    def fail_start(_thread):
        raise RuntimeError('fixture cannot start watcher')
    monkeypatch.setattr(wrapper.threading.Thread, 'start', fail_start)
    assert wrapper.main() == 127
    time.sleep(1.2)
    assert not (tmp_path / 'late').exists()


def test_target_waits_for_watchdog_before_running(tmp_path, monkeypatch):
    import core.executor.process as process_module
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 2)
    source = Path(process_module.__file__).parent
    copied = tmp_path / 'fixture-executor'
    copied.mkdir()
    for name in ('process_wrapper.py', 'seccomp.py', 'process_identity.py'):
        shutil.copy(source / name, copied / name)
    wrapper = copied / 'process_wrapper.py'
    original = wrapper.read_text()
    needle = '                    watcher.start()'
    assert needle in original
    wrapper.write_text(original.replace(needle, '                    time.sleep(3)\n' + needle))
    monkeypatch.setattr(process_module, '__file__', str(copied / 'process.py'))
    append = ContinuationStore.append
    def blocked_append(self, kind, payload):
        if kind == 'executor_process_started':
            time.sleep(3.5)
        return append(self, kind, payload)
    monkeypatch.setattr(ContinuationStore, 'append', blocked_append)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
        ['/usr/bin/python3', '-c', "import time; time.sleep(2.4); open('late','w').write('alive')"])
    assert result['state'] == 'expired_unresolved'
    assert not (workspace / 'late').exists()


def test_gate_stops_if_supervisor_dies_after_release(tmp_path):
    import core.executor.process as process_module
    deadline, workspace = setup(tmp_path, 20)
    source = Path(process_module.__file__).parent
    copied = tmp_path / 'fixture-executor'
    copied.mkdir()
    for name in ('process_wrapper.py', 'seccomp.py', 'process_identity.py'):
        shutil.copy(source / name, copied / name)
    wrapper = copied / 'process_wrapper.py'
    original = wrapper.read_text()
    needle = "        os.close(fd)\n        if open"
    assert needle in original
    wrapper.write_text(original.replace(needle,
        "        os.close(fd)\n        parent=int(open('/proc/%s/stat'%os.getppid()).read().split()[3])\n"
        "        os.kill(parent,9)\n        time.sleep(.2)\n        if open"))
    script = """
import sys
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.cell_worker import run_cell_worker
from zoo.mle_bench_lite.cny_budget import CampaignBudget
import core.executor.process as process
clock, campaign, directory, workspace, executor = sys.argv[1:]
process.__file__ = executor
deadline = CellDeadline.restore(ContinuationStore(clock), lifecycle=CellLifecycle(CampaignBudget(campaign)),
    cell_id='vendor-0', plan_ref='sha256:' + 'a'*64, seconds=20)
run_cell_worker(deadline, directory, workspace, ['/usr/bin/python3', '-c', "open('late','w').write('alive')"])
"""
    src = str(Path(__file__).resolve().parents[1])
    process = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'clock.jsonl'),
        str(tmp_path / 'campaign.db'), str(tmp_path / 'worker'), str(workspace), str(copied / 'process.py')],
        env={'PATH': os.defpath, 'PYTHONPATH': src}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
    assert process.returncode == -9
    time.sleep(1)
    assert not (workspace / 'late').exists()
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is not None


def test_isolated_worker_reaches_local_broker_without_provider_key(tmp_path, short_socket_dir):
    from zoo.circle_packing.cell_worker import run_cell_worker
    from zoo.circle_packing.host_transport import HostBroker
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path, token_path = workspace / 'broker.sock', workspace / 'token'
    token = 'a' * 64  # Disposable fixture capability, not a provider credential.
    token_path.write_text(token)
    token_path.chmod(0o600)
    observed = []
    def dispatch(request_id, argument):
        observed.append(argument)
        return {'state': 'ok', 'result': 'fixture patch',
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}}
    program = """import asyncio,os,sys
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
os.environ['MORI_CIRCLE_BROKER_SOCKET']=sys.argv[2]
os.environ['MORI_CIRCLE_BROKER_TOKEN']=open(sys.argv[3]).read().strip()
from zoo.circle_packing.host_transport import HostBridgeClient
client=HostBridgeClient(SimpleNamespace(name='fixture'))
result=asyncio.run(client.generate_with_context('system',[{'role':'user','content':'user'}]))
assert result=='fixture patch' and client.last_usage['total_tokens']==7
"""
    source = Path(__file__).resolve().parents[1]
    with HostBroker(socket_path, token, dispatch) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
            [sys.executable, '-c', program, str(source), str(socket_path), str(token_path)],
            readonly_source=source, readonly_runtime=Path(sys.prefix))
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert result['state'] == 'completed'
    assert observed[0]['host_messages'] == {'system': 'system', 'user': 'user'}
    # The disposable token is passed in a private file, not the durable process spec.
    specs = list((tmp_path / 'worker').rglob('spec.json'))
    assert len(specs) == 1 and token not in specs[0].read_text()


def test_readonly_source_is_not_writable_inside_worker(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 30)
    source = tmp_path / 'source'
    source.mkdir()
    target = source / 'module.py'
    target.write_text('original')
    program = """import pathlib,sys
try:
    pathlib.Path(sys.argv[1]).write_text('changed')
except OSError:
    pass
else:
    raise AssertionError('source was writable')
"""
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
        ['/usr/bin/python3', '-c', program, str(target)], readonly_source=source)
    assert result['state'] == 'completed'
    assert target.read_text() == 'original'


def test_readonly_source_must_not_contain_worker_authority(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    deadline, workspace = setup(tmp_path, 30)
    source = tmp_path / 'source'
    source.mkdir()
    with pytest.raises(ValueError, match='source'):
        run_cell_worker(deadline, source / 'worker', workspace, ['/bin/true'], readonly_source=source)
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None
