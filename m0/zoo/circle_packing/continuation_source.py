"""Prepare recoverable source evidence for a non-executable continuation draft."""
from __future__ import annotations

import fcntl
import ctypes
import errno
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.clean_source import export_clean_source, verify_clean_source
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.frozen_source import _validate_lock
from zoo.circle_packing.pilot_draft import _read_private_json, _sync_source_tree
from zoo.circle_packing.pilot_freeze_runtime import _persist_manifest, _repair_manifest_links
from zoo.circle_packing.pilot_plan import build_draft_plan, validate_source_preflight
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def _publish_source(source, destination):
    """Publish one directory atomically without replacing an existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux'):
        function = getattr(libc, 'renameat2', None)
        if function is None:
            raise OSError(errno.ENOTSUP, 'atomic no-replace publication is unavailable')
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    elif sys.platform == 'darwin':
        function = getattr(libc, 'renamex_np', None)
        if function is None:
            raise OSError(errno.ENOTSUP, 'atomic no-replace publication is unavailable')
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = function(os.fsencode(source), os.fsencode(destination), 4)
    else:
        raise OSError(errno.ENOTSUP, 'atomic no-replace publication is unavailable')
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def _verify_commit_manifest(checkout, commit, manifest):
    env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0'}
    try:
        raw = subprocess.check_output(['git', '-C', str(checkout), 'ls-tree', '-r', '-l', '-z',
                                       '--full-tree', commit], env=env, stderr=subprocess.DEVNULL, timeout=30)
        expected = []
        for item in raw.split(b'\0'):
            if item:
                header, path = item.split(b'\t', 1)
                mode, kind, oid, size = header.decode('ascii').split()
                if kind != 'blob':
                    raise ValueError('source commit has an unsupported entry')
                expected.append((path.decode('utf-8'), mode, oid, int(size)))
        observed = [(entry['path'], entry['mode'], entry['oid'], entry['size']) for entry in manifest]
        if observed != expected:
            raise ValueError('source manifest differs from the pinned commit')
    except (OSError, subprocess.SubprocessError, UnicodeError, KeyError, TypeError) as error:
        raise ValueError('cannot verify pinned source manifest') from error


def prepare_continuation_source(ledger, draft, *, checkout, directory):
    """Create or recover a synced Git snapshot; this does not grant authority."""
    if type(ledger) is not CampaignBudget or type(draft) is not dict:
        raise ValueError('continuation source requires a campaign and draft')
    try:
        inventory = ledger.circle_continuation_inventory(expected_head=draft['predecessor_head'])
        expected = build_continuation_draft(inventory, experiment_id=draft['experiment_id'],
            source_commit=draft['source_commit'], dependency_lock_sha256=draft['dependency_lock_sha256'],
            method_changes=draft['method_changes'])
    except (KeyError, TypeError) as error:
        raise ValueError('continuation draft is incomplete') from error
    if draft != expected:
        raise ValueError('continuation draft differs from the original campaign')
    checkout, requested = Path(checkout), Path(directory)
    if not checkout.is_absolute() or not requested.is_absolute() or requested.name in ('', '.', '..'):
        raise ValueError('source preparation requires absolute paths')
    checkout = checkout.resolve(strict=True)
    parent = requested.parent.resolve(strict=True)
    root = parent / requested.name
    info = parent.stat()
    ledger_path = ledger.path.resolve(strict=True)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or \
            root.is_symlink() or root == checkout or root in checkout.parents or checkout in root.parents or \
            root == ledger_path or root in ledger_path.parents:
        raise ValueError('source bundle requires a private separate location')
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('source bundle requires a private owned directory')
    lock_fd = os.open(root / '.prepare.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or \
                stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_nlink != 1:
            raise ValueError('source preparation lock is invalid')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        base = build_draft_plan(inventory['campaign'], source_commit=draft['source_commit'],
                                dependency_lock_sha256=draft['dependency_lock_sha256'])
        ref = 'sha256:' + base['draft_sha256']
        validate_source_preflight(ledger, base, 'vendor-0', checkout=checkout, expected_plan_ref=ref)
        draft_path, manifest_path, source = root / 'draft.json', root / 'source-manifest.json', root / 'source'
        if draft_path.exists():
            _repair_manifest_links(draft_path, draft)
            if _read_private_json(draft_path) != draft:
                raise ValueError('source bundle belongs to a different draft')
        else:
            _persist_manifest(draft_path, draft)
        if source.exists() and not manifest_path.exists():
            raise ValueError('published source has no original manifest')
        if not source.exists():
            stage = root / ('.source-staging-' + uuid.uuid4().hex)
            exported = export_clean_source(ledger, base, 'vendor-0', checkout=checkout,
                                           destination=stage, expected_plan_ref=ref)
            manifest = exported['manifest']
            if manifest_path.exists():
                _repair_manifest_links(manifest_path, manifest)
                if _read_private_json(manifest_path) != manifest:
                    raise ValueError('staged source differs from the original manifest')
            else:
                _persist_manifest(manifest_path, manifest)
            _sync_source_tree(stage)
            if source.is_symlink() or source.exists():
                raise ValueError('published source appeared during preparation')
            _publish_source(stage, source)
        # Also repair durability after a crash following publication. Verify
        # the source again after synchronizing its files and parent directories.
        _sync_source_tree(source)
        manifest = _read_private_json(manifest_path)
        tree_ref = 'sha256:' + payload_digest(manifest)
        _validate_lock(base, manifest)
        _verify_commit_manifest(checkout, draft['source_commit'], manifest)
        verify_clean_source(source, manifest, expected_tree_ref=tree_ref)
        ledger.circle_continuation_inventory(expected_head=draft['predecessor_head'])
        return {'scope': 'continuation_source_prepared_not_bound', 'draft_sha256': draft['draft_sha256'],
                'tree_ref': tree_ref, 'source_root': str(source), 'source_manifest': str(manifest_path)}
    finally:
        os.close(lock_fd)
