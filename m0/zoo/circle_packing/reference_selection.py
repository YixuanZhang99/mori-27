"""Read the pinned upstream controller's saved winner after it has exited.

These checks bind its report to its saved files; they do not authenticate the
worker's selection or prevent a same-user writer from changing the workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate reference artifact field')
        value[key] = item
    return value


def _read_file(directory, name, limit):
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(name, flags, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError('reference artifact must be a bounded single-link regular file')
        parts, remaining = [], limit + 1
        while remaining:
            part = os.read(fd, remaining)
            if not part:
                break
            parts.append(part)
            remaining -= len(part)
        data = b''.join(parts)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('reference artifact changed during reading')
        return data
    finally:
        os.close(fd)


def read_reference_selection(workspace, selected):
    """Check the worker report against bounded, no-follow upstream files."""
    if type(selected) is not dict or set(selected) != {'id', 'program_ref', 'metrics'} or \
            type(selected['id']) is not str or not selected['id'] or type(selected['metrics']) is not dict:
        raise ValueError('invalid reference selection')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directories = []
    try:
        directory = os.open(Path(workspace), flags)
        directories.append(directory)
        for name in ('host-run', 'host', 'best'):
            directory = os.open(name, flags, dir_fd=directory)
            directories.append(directory)
        source = _read_file(directory, 'best_program.py', 1024 * 1024)
        info = json.loads(_read_file(directory, 'best_program_info.json', 65536).decode('utf-8'),
                          object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        program = source.decode('utf-8')
        if not program.strip() or type(info) is not dict or info.get('id') != selected['id'] or \
                json.dumps(info.get('metrics'), sort_keys=True, allow_nan=False) != \
                json.dumps(selected['metrics'], sort_keys=True, allow_nan=False) or \
                selected['program_ref'] != 'sha256:' + hashlib.sha256(source).hexdigest():
            raise ValueError('reference report differs from saved program or metadata')
        return {'saved_program_ref': selected['program_ref']}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, RecursionError) as error:
        raise ValueError('reference artifact cannot be safely read') from error
    finally:
        for fd in reversed(directories):
            os.close(fd)
