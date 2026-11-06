"""Linux cgroup-v2 feasibility probe; not a live-supervision implementation.

Run inside a writable delegated user scope. A passing probe alone does not
prove the application uses this containment or handles supervisor crashes.
"""
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import pytest


@pytest.mark.linux
def test_delegated_cgroup_kills_detached_descendant_and_becomes_empty():
    membership = Path('/proc/self/cgroup').read_text().strip().splitlines()
    v2 = [row[3:] for row in membership if row.startswith('0::/')]
    if len(v2) != 1:
        pytest.skip('a unified cgroup-v2 hierarchy is required')
    parent = Path('/sys/fs/cgroup') / v2[0].lstrip('/')
    if not os.access(parent, os.W_OK) or not (parent / 'cgroup.kill').exists():
        pytest.skip('run inside a writable delegated cgroup-v2 scope')
    group = parent / f'mori-test-{os.getpid()}'
    group.mkdir()
    child = None
    try:
        script = ("import os,sys,time; sys.stdin.readline(); p=os.fork(); "
                  "(os.setsid(), print('ready',flush=True), time.sleep(60), os._exit(0)) "
                  "if p==0 else time.sleep(60)")
        child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={'PATH': '/usr/bin:/bin'})
        (group / 'cgroup.procs').write_text(str(child.pid))
        child.stdin.write('go\n')
        child.stdin.flush()
        assert select.select([child.stdout], [], [], 10)[0] and child.stdout.readline().strip() == 'ready'
        assert 'populated 1' in (group / 'cgroup.events').read_text()
        (group / 'cgroup.kill').write_text('1')
        child.wait(timeout=10)
        deadline = time.monotonic() + 10
        while 'populated 0' not in (group / 'cgroup.events').read_text() and time.monotonic() < deadline:
            time.sleep(.02)
        assert 'populated 0' in (group / 'cgroup.events').read_text()
    finally:
        if group.exists():
            (group / 'cgroup.kill').write_text('1')
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        if group.exists():
            deadline = time.monotonic() + 10
            while 'populated 0' not in (group / 'cgroup.events').read_text() and time.monotonic() < deadline:
                time.sleep(.02)
            group.rmdir()
