"""Export a draft's tracked Git blobs without copying workspace-only files.

This creates a clean snapshot, not an immutable execution environment or an
authorization to run the pilot. The supervisor must still protect and bind it.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.pilot_plan import validate_source_preflight

_MAX_BLOB = 64 * 1024 * 1024
_MAX_TOTAL = 256 * 1024 * 1024


def export_clean_source(ledger, plan, cell_id, *, checkout, destination, expected_plan_ref):
    """Write exact regular blobs from the pinned commit into a fresh private tree."""
    binding = validate_source_preflight(ledger, plan, cell_id, checkout=checkout,
                                        expected_plan_ref=expected_plan_ref)
    root = Path(checkout).resolve(strict=True)
    requested = Path(destination)
    parent = requested.parent.resolve(strict=True)
    info = parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('source destination requires a private owned parent')
    dest = parent / requested.name
    if not requested.name or requested.name in ('.', '..') or dest.exists() or dest.is_symlink() or \
            dest == root or root in dest.parents or dest in root.parents or \
            dest in ledger.path.resolve().parents:
        raise ValueError('source destination must be fresh and separate')
    env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0'}
    try:
        raw = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '-l', '-z',
            '--full-tree', plan['source_commit']], env=env, stderr=subprocess.DEVNULL, timeout=30)
        entries, total = [], 0
        for item in raw.split(b'\0'):
            if not item:
                continue
            header, name = item.split(b'\t', 1)
            mode, kind, oid, size = header.decode('ascii').split()
            path = name.decode('utf-8')
            parts = PurePosixPath(path).parts
            if mode == '120000':
                raise ValueError('source snapshot does not permit symlinks')
            if mode not in {'100644', '100755'} or kind != 'blob' or not re.fullmatch(r'[0-9a-f]{40}', oid) or \
                    not parts or path.startswith('/') or any(part in ('.', '..', '.git') for part in parts) or \
                    str(PurePosixPath(path)) != path:
                raise ValueError('source snapshot contains an unsupported tree entry')
            length = int(size)
            total += length
            if length < 0 or length > _MAX_BLOB or total > _MAX_TOTAL:
                raise ValueError('source snapshot exceeds file size limits')
            entries.append({'path': path, 'mode': mode, 'oid': oid, 'size': length})
        if not entries:
            raise ValueError('source snapshot is empty')
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError('cannot inspect source commit') from error
    try:
        dest.mkdir(mode=0o700)
    except OSError as error:
        raise ValueError('source destination cannot be created') from error
    process = None
    try:
        process = subprocess.Popen(['git', '-C', str(root), 'cat-file', '--batch'], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for entry in entries:
            process.stdin.write((entry['oid'] + '\n').encode('ascii'))
            process.stdin.flush()
            header = process.stdout.readline(256).decode('ascii').strip().split()
            if header != [entry['oid'], 'blob', str(entry['size'])]:
                raise ValueError('source blob differs from the pinned tree')
            path = dest.joinpath(*PurePosixPath(entry['path']).parts)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            digest = hashlib.sha1(b'blob ' + str(entry['size']).encode('ascii') + b'\0', usedforsecurity=False)
            digest256 = hashlib.sha256()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o700 if entry['mode'] == '100755' else 0o600)
            with os.fdopen(fd, 'wb') as output:
                left = entry['size']
                while left:
                    chunk = process.stdout.read(min(left, 1024 * 1024))
                    if not chunk:
                        raise ValueError('source blob was truncated')
                    output.write(chunk)
                    digest.update(chunk)
                    digest256.update(chunk)
                    left -= len(chunk)
            if process.stdout.read(1) != b'\n' or digest.hexdigest() != entry['oid']:
                raise ValueError('source blob failed its object identity check')
            entry['sha256'] = digest256.hexdigest()
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise ValueError('source object reader failed')
        return {**binding, 'tree_ref': 'sha256:' + payload_digest(entries), 'manifest': entries,
                'file_count': len(entries), 'total_bytes': total}
    except BaseException:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        shutil.rmtree(dest)
        raise


def verify_clean_source(snapshot, manifest, *, expected_tree_ref):
    """Compare every snapshot path and byte with an independently retained manifest."""
    if type(manifest) is not list or not manifest or type(expected_tree_ref) is not str or \
            expected_tree_ref != 'sha256:' + payload_digest(manifest):
        raise ValueError('source snapshot manifest differs from its trusted identity')
    root = Path(snapshot)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('source snapshot root must be a directory')
    expected, expected_dirs = {}, set()
    for entry in manifest:
        if type(entry) is not dict or set(entry) != {'path', 'mode', 'oid', 'size', 'sha256'} or \
                type(entry['path']) is not str or type(entry['size']) is not int or \
                not 0 <= entry['size'] <= _MAX_BLOB or type(entry['mode']) is not str or \
                entry['mode'] not in {'100644', '100755'} or \
                type(entry['oid']) is not str or not re.fullmatch(r'[0-9a-f]{40}', entry['oid']) or \
                type(entry['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
            raise ValueError('invalid source snapshot manifest entry')
        path = PurePosixPath(entry['path'])
        if path.is_absolute() or str(path) != entry['path'] or not path.parts or \
                any(part in ('.', '..', '.git') for part in path.parts) or entry['path'] in expected:
            raise ValueError('invalid source snapshot path')
        expected[entry['path']] = entry
        expected_dirs.update(str(parent) for parent in path.parents if str(parent) != '.')
    if sum(entry['size'] for entry in manifest) > _MAX_TOTAL:
        raise ValueError('source snapshot exceeds file size limits')
    seen, seen_dirs = set(), set()
    try:
        def onerror(error):
            raise error
        for directory, directories, files in os.walk(root, followlinks=False, onerror=onerror):
            for name in directories:
                path = Path(directory) / name
                if path.is_symlink():
                    raise ValueError('source snapshot contains a symlink')
                seen_dirs.add(path.relative_to(root).as_posix())
            for name in files:
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                entry = expected.get(relative)
                if entry is None or path.is_symlink():
                    raise ValueError('source snapshot contains an unexpected path')
                initial = path.lstat()
                if not stat.S_ISREG(initial.st_mode):
                    raise ValueError('source snapshot contains a non-regular file')
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or \
                            (initial.st_dev, initial.st_ino) != (before.st_dev, before.st_ino) or \
                            before.st_size != entry['size'] or \
                            bool(before.st_mode & stat.S_IXUSR) != (entry['mode'] == '100755'):
                        raise ValueError('source snapshot file differs from the manifest')
                    digest = hashlib.sha1(b'blob ' + str(entry['size']).encode('ascii') + b'\0',
                                          usedforsecurity=False)
                    digest256 = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        digest256.update(chunk)
                    after = os.fstat(stream.fileno())
                    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
                            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or \
                            digest.hexdigest() != entry['oid'] or digest256.hexdigest() != entry['sha256']:
                        raise ValueError('source snapshot bytes changed')
                seen.add(relative)
    except OSError as error:
        raise ValueError('cannot verify source snapshot') from error
    if seen != set(expected) or seen_dirs != expected_dirs:
        raise ValueError('source snapshot is missing files or contains extra directories')
    return {'tree_ref': expected_tree_ref, 'file_count': len(seen)}
