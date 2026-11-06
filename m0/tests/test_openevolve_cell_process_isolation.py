"""Exercise existing Linux executor containment before cell-supervisor wiring."""
import json
from pathlib import Path
import time

import pytest

from core.executor.process import ProcessJournal
from core.executor.process_identity import process_alive, start_ticks
from core.executor.sandbox import BubblewrapSandbox
from core.x1.store import AppendOnlyStore


pytestmark = pytest.mark.linux


def launch_detached_child(tmp_path, *, timeout):
    sandbox = BubblewrapSandbox()
    journal = ProcessJournal(AppendOnlyStore(tmp_path / 'process.jsonl'))
    # The child deliberately leaves the target's session.  A process-group
    # kill alone would not stop it; the enclosing PID namespace must do so.
    program = ("import os,time; p=os.fork(); "
               "(os.setsid(), print('ready:%s' % os.getpid(),flush=True), time.sleep(5), "
               "open('escaped','w').write('alive'), os._exit(0)) "
               "if p == 0 else time.sleep(30)")
    args = sandbox.wrap(['/usr/bin/python3', '-c', program], tmp_path)
    process, record = journal.launch(args, tmp_path, {}, timeout,
        {'candidate_id': 'fixture', 'attempt': 1}, seccomp_policy=sandbox.seccomp_spec())
    try:
        deadline = time.monotonic() + 8
        output = Path(record['stdout_path'])
        while time.monotonic() < deadline and (not output.exists() or 'ready:' not in output.read_text()):
            if process.poll() is not None:
                raise AssertionError(Path(record['stderr_path']).read_text())
            time.sleep(0.02)
        assert output.exists() and 'ready:' in output.read_text()
        target = json.loads(Path(record['target_path']).read_text())['pid']
        namespace_pid = int(output.read_text().split('ready:', 1)[1].splitlines()[0])
        # Locate the detached child by its own namespace PID and retain its host
        # birth identity so PID reuse cannot masquerade as termination.
        pending, child = [target], None
        while pending:
            pid = pending.pop()
            try:
                status = Path(f'/proc/{pid}/status').read_text()
                namespace = next(line for line in status.splitlines() if line.startswith('NSpid:')).split()[1:]
                if len(namespace) >= 2 and namespace[-1] == str(namespace_pid):
                    child = (pid, start_ticks(pid))
                    break
                pending.extend(int(value) for value in Path(f'/proc/{pid}/task/{pid}/children').read_text().split())
            except (OSError, StopIteration):
                continue
        assert child is not None and child[1] is not None and process_alive(*child)
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        journal.terminate_target(record)
        raise
    return journal, process, record, child


def assert_child_stopped(child):
    deadline = time.monotonic() + 5
    while process_alive(*child) and time.monotonic() < deadline:
        time.sleep(0.02)
    if Path(f'/proc/{child[0]}').exists() and start_ticks(child[0]) is None:
        raise AssertionError('cannot verify detached child process identity')
    assert not process_alive(*child)


def test_existing_executor_timeout_stops_detached_namespace_child(tmp_path):
    journal, process, record, child = launch_detached_child(tmp_path, timeout=3)
    result = journal.wait(process, record)
    assert result['timeout'] is True
    assert_child_stopped(child)
    time.sleep(5.2)
    assert not (tmp_path / 'escaped').exists()


def test_existing_executor_crash_leaves_lost_result_and_stops_detached_child(tmp_path):
    journal, process, record, child = launch_detached_child(tmp_path, timeout=30)
    process.kill()
    process.wait(timeout=5)
    try:
        assert_child_stopped(child)
        time.sleep(5.2)
        assert not (tmp_path / 'escaped').exists()
    finally:
        assert journal.recover(record)['status'] == 'lost'


def test_detached_child_can_write_without_termination(tmp_path):
    journal, process, record, child = launch_detached_child(tmp_path, timeout=30)
    try:
        deadline = time.monotonic() + 8
        marker = tmp_path / 'escaped'
        while time.monotonic() < deadline and (not marker.exists() or marker.read_text() != 'alive'):
            time.sleep(0.02)
        assert marker.read_text() == 'alive'
    finally:
        process.kill()
        process.wait(timeout=5)
        assert journal.recover(record)['status'] == 'lost'
