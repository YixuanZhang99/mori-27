"""An isolated worker must stop even when its wrapper cannot run."""
import os
from pathlib import Path
import signal
import json
import sys
import time

import pytest

from core.executor.process import ProcessJournal
from core.executor.process_identity import process_alive
from core.executor.sandbox import BubblewrapSandbox
from core.x1.store import AppendOnlyStore


pytestmark = pytest.mark.linux


def test_deadline_stops_worker_while_wrapper_is_suspended(tmp_path):
    sandbox = BubblewrapSandbox()
    journal = ProcessJournal(AppendOnlyStore(tmp_path / 'events.jsonl'))
    command = ['/usr/bin/python3', '-c',
               "import time; open('ready','w').write('ready'); time.sleep(3); open('late','w').write('late')"]
    args = sandbox.wrap(command, tmp_path)
    absolute = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'deadline_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME) + 2_000_000_000}
    wrapper, record = journal.launch(args, tmp_path, {}, 20, {'candidate_id': 'cell', 'attempt': 1},
                                     seccomp_policy=sandbox.seccomp_spec(), absolute_deadline=absolute)
    try:
        until = time.monotonic() + 1.5
        while not (tmp_path / 'ready').exists() and time.monotonic() < until:
            time.sleep(.01)
        assert (tmp_path / 'ready').exists()
        target = json.loads(Path(record['target_path']).read_text())
        assert process_alive(target['pid'], target['start_ticks'])
        os.kill(wrapper.pid, signal.SIGSTOP)
        time.sleep(3.2)
        assert not process_alive(target['pid'], target['start_ticks'])
        assert not (tmp_path / 'late').exists()
    finally:
        os.kill(wrapper.pid, signal.SIGCONT)
        wrapper.wait(timeout=5)
        journal.terminate_target(record)


def test_worker_stops_if_independent_guard_exits(tmp_path):
    sandbox = BubblewrapSandbox()
    journal = ProcessJournal(AppendOnlyStore(tmp_path / 'events.jsonl'))
    command = ['/usr/bin/python3', '-c',
               "import time; open('ready','w').write('ready'); time.sleep(2); open('late','w').write('late')"]
    args = sandbox.wrap(command, tmp_path)
    absolute = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'deadline_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME) + 10_000_000_000}
    wrapper, record = journal.launch(args, tmp_path, {}, 20, {'candidate_id': 'cell', 'attempt': 1},
                                     seccomp_policy=sandbox.seccomp_spec(), absolute_deadline=absolute)
    try:
        until = time.monotonic() + 5
        while not (tmp_path / 'ready').exists() and time.monotonic() < until:
            time.sleep(.01)
        assert (tmp_path / 'ready').exists()
        children = Path(f'/proc/{wrapper.pid}/task/{wrapper.pid}/children').read_text().split()
        guards = [int(pid) for pid in children if b'pidfd_open' in Path(f'/proc/{pid}/cmdline').read_bytes()]
        assert len(guards) == 1
        os.kill(guards[0], signal.SIGKILL)
        wrapper.wait(timeout=5)
        assert journal.completed_result(record)['wrapper_error'] is not None
        time.sleep(2.2)
        assert not (tmp_path / 'late').exists()
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
        wrapper.wait(timeout=5)
        journal.terminate_target(record)


def test_shorter_relative_timeout_survives_wrapper_suspension(tmp_path):
    sandbox = BubblewrapSandbox()
    journal = ProcessJournal(AppendOnlyStore(tmp_path / 'events.jsonl'))
    command = ['/usr/bin/python3', '-c',
               "import time; open('ready','w').write('ready'); time.sleep(2); open('late','w').write('late')"]
    absolute = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'deadline_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME) + 8_000_000_000}
    wrapper, record = journal.launch(sandbox.wrap(command, tmp_path), tmp_path, {}, 1,
        {'candidate_id': 'cell', 'attempt': 1}, seccomp_policy=sandbox.seccomp_spec(), absolute_deadline=absolute)
    try:
        until = time.monotonic() + .8
        while not (tmp_path / 'ready').exists() and time.monotonic() < until:
            time.sleep(.01)
        assert (tmp_path / 'ready').exists()
        os.kill(wrapper.pid, signal.SIGSTOP)
        time.sleep(2.2)
        assert not (tmp_path / 'late').exists()
    finally:
        os.kill(wrapper.pid, signal.SIGCONT)
        wrapper.wait(timeout=5)
        journal.terminate_target(record)


def test_guard_start_failure_never_releases_target(tmp_path, monkeypatch):
    import core.executor.process_wrapper as wrapper
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    spec = {'args': [sys.executable, '-c', "open('late','w').write('late')"],
            'cwd': str(tmp_path), 'time_limit': 10, 'resource_limits': {}, 'seccomp_policy': None,
            'seccomp_delivery': None, 'absolute_deadline': {'boot_id': boot,
                'deadline_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME) + 10_000_000_000},
            'stdout_path': str(tmp_path / 'stdout'), 'stderr_path': str(tmp_path / 'stderr'),
            'result_path': str(tmp_path / 'result.json'), 'target_path': str(tmp_path / 'target.json')}
    source = tmp_path / 'spec.json'
    source.write_text(json.dumps(spec))
    monkeypatch.setattr(sys, 'argv', ['wrapper', str(source)])
    monkeypatch.setattr(wrapper, '_GUARD', 'import sys; sys.exit(7)')
    assert wrapper.main() == 127
    assert not (tmp_path / 'late').exists()


@pytest.mark.parametrize('limit', [float('nan'), float('inf'), -1, True, '1', 10**1000])
def test_absolute_deadline_rejects_invalid_relative_timeout(tmp_path, limit):
    journal = ProcessJournal(AppendOnlyStore(tmp_path / 'events.jsonl'))
    absolute = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'deadline_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME) + 10_000_000_000}
    with pytest.raises(ValueError):
        journal.launch(['/bin/true'], tmp_path, {}, limit, {'candidate_id': 'cell', 'attempt': 1},
                       absolute_deadline=absolute)
