"""Delegated cgroup containment for a trusted cell controller.

This is not a crash-recovery certificate or a substitute for sandboxing the
untrusted candidate. A lost supervisor leaves the cell unresolved.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import sys
import time


@contextmanager
def delegated_cell_group():
    if sys.platform != 'linux':
        raise ValueError('cell containment requires Linux cgroup v2')
    rows = Path('/proc/self/cgroup').read_text().splitlines()
    memberships = [line[3:] for line in rows if line.startswith('0::/')]
    root = Path('/sys/fs/cgroup').resolve(strict=True)
    if len(memberships) != 1:
        raise ValueError('cell containment requires a unified cgroup')
    parent = (root / memberships[0].lstrip('/')).resolve(strict=True)
    if root not in parent.parents or not os.access(parent, os.W_OK) or not (parent / 'cgroup.kill').is_file():
        raise ValueError('cell containment requires a writable delegated cgroup')
    group = parent / ('mori-cell-' + secrets.token_hex(16))
    group.mkdir(mode=0o700)
    try:
        yield group
    finally:
        if group.exists():
            finish_cell_group(group)


def finish_cell_group(group):
    """Kill and remove the group before recording a successful process result."""
    (group / 'cgroup.kill').write_text('1')
    end = time.monotonic() + 10
    while time.monotonic() < end and 'populated 0' not in (group / 'cgroup.events').read_text().splitlines():
        time.sleep(.02)
    if 'populated 0' not in (group / 'cgroup.events').read_text().splitlines():
        raise RuntimeError('cell containment could not confirm termination')
    group.rmdir()


def contained_command(group, command):
    """Join before executing the trusted controller or any of its work."""
    bootstrap = ("import os,sys; group=sys.argv.pop(1); "
                 "open(group+'/cgroup.procs','w').write(str(os.getpid())); "
                 "os.execv(sys.argv[1],sys.argv[1:])")
    return [command[0], '-c', bootstrap, str(group), *command]
