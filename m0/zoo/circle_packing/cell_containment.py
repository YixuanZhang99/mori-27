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
    info = group.stat()
    identity = {'device': info.st_dev, 'inode': info.st_ino}
    try:
        yield group
    finally:
        if group.exists():
            finish_cell_group(group, expected_identity=identity)


def finish_cell_group(group, *, expected_identity):
    """Kill and remove the group before recording a successful process result."""
    fd = os.open(group, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if expected_identity != {'device': info.st_dev, 'inode': info.st_ino}:
            raise ValueError('cell containment group identity changed')
        def read_events():
            event_fd = os.open('cgroup.events', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(event_fd, 'r') as stream:
                return stream.read().splitlines()
        kill_fd = os.open('cgroup.kill', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(kill_fd, 'w') as stream:
            stream.write('1')
        end = time.monotonic() + 10
        while time.monotonic() < end and 'populated 0' not in read_events():
            time.sleep(.02)
        if 'populated 0' not in read_events():
            raise RuntimeError('cell containment could not confirm termination')
        current = os.stat(group, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('cell containment group identity changed')
        group.rmdir()
    finally:
        os.close(fd)


def contained_command(group, command):
    """Join before executing the trusted controller or any of its work."""
    bootstrap = ("import os,sys; group=sys.argv.pop(1); "
                 "open(group+'/cgroup.procs','w').write(str(os.getpid())); "
                 "os.execv(sys.argv[1],sys.argv[1:])")
    return [command[0], '-c', bootstrap, str(group), *command]
