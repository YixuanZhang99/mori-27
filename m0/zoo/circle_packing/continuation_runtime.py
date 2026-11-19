"""Prepare an offline runtime for a continuation without granting authority."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import uuid

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.continuation_source import prepare_continuation_source
from zoo.circle_packing.frozen_runtime import _runtime_manifest, _sync_runtime_tree, _validate_install_inputs
from zoo.circle_packing.pilot_draft import _read_private_json
from zoo.circle_packing.pilot_freeze_runtime import _persist_manifest, _repair_manifest_links
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def _separate(left, right):
    return left != right and left not in right.parents and right not in left.parents


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _manifest_envelope(manifest, draft_sha256, tree_ref):
    return {'schema_version': 1, 'draft_sha256': draft_sha256, 'tree_ref': tree_ref, 'runtime': manifest}


def _recover_manifest_links(path, root, base, lock_sha256, draft_sha256, tree_ref):
    """Repair only same-inode manifest publication leftovers of a known runtime."""
    if path.lstat().st_nlink == 1:
        return
    for candidate in root.iterdir():
        if re.fullmatch(r'runtime-[0-9a-f]{32}', candidate.name) and candidate.is_dir() and not candidate.is_symlink():
            try:
                manifest = _runtime_manifest(candidate, base, lock_sha256)
                _repair_manifest_links(path, _manifest_envelope(manifest, draft_sha256, tree_ref))
                return
            except (ValueError, OSError):
                continue
    raise ValueError('runtime manifest publication cannot be recovered')


def prepare_continuation_runtime(ledger, draft, *, checkout, source_directory, directory, uv_cache, base_python):
    """Install or verify one durable runtime; this does not bind a campaign."""
    if type(ledger) is not CampaignBudget or type(draft) is not dict:
        raise ValueError('runtime preparation requires the original campaign and draft')
    requested, source_request, checkout_request, cache_request, base_request = map(
        Path, (directory, source_directory, checkout, uv_cache, base_python))
    if not all(path.is_absolute() for path in (requested, source_request, checkout_request, cache_request, base_request)) \
            or requested.name in ('', '.', '..') or source_request.name in ('', '.', '..'):
        raise ValueError('runtime preparation paths must be absolute')
    parent = requested.parent.resolve(strict=True)
    root = parent / requested.name
    source_root = source_request.parent.resolve(strict=True) / source_request.name
    checkout_root = checkout_request.resolve(strict=True)
    cache = cache_request.resolve(strict=True)
    base = base_request.resolve(strict=True)
    ledger_path = ledger.path.resolve(strict=True)
    info = parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or \
            root.is_symlink() or not cache.is_dir() or Path('/usr') not in base.parents or not base.is_file() or \
            not all(_separate(root, path) for path in (source_root, checkout_root, cache, ledger_path)) or \
            not _separate(cache, source_root) or not _separate(cache, ledger_path):
        raise ValueError('runtime requires private, separate source, cache and campaign paths')
    source = prepare_continuation_source(ledger, draft, checkout=checkout_root, directory=source_root)
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('runtime bundle must be a private owned directory')
    lock_fd = os.open(root / '.prepare.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or \
                stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_nlink != 1:
            raise ValueError('runtime preparation lock is invalid')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        manifest_path = root / 'runtime-manifest.json'
        if manifest_path.exists():
            _recover_manifest_links(manifest_path, root, base, draft['dependency_lock_sha256'],
                                    draft['draft_sha256'], source['tree_ref'])
            envelope = _read_private_json(manifest_path)
            try:
                if type(envelope) is not dict or set(envelope) != {'schema_version', 'draft_sha256', 'tree_ref', 'runtime'} or \
                        type(envelope['schema_version']) is not int or envelope['schema_version'] != 1 or \
                        envelope['draft_sha256'] != draft['draft_sha256'] or envelope['tree_ref'] != source['tree_ref']:
                    raise ValueError('runtime manifest belongs to another draft or source')
                manifest = envelope['runtime']
                runtime = Path(manifest['root'])
                if not runtime.is_absolute() or runtime.parent != root or \
                        re.fullmatch(r'runtime-[0-9a-f]{32}', runtime.name) is None or runtime.is_symlink() or \
                        manifest['base_python'] != str(base) or manifest['lock_sha256'] != draft['dependency_lock_sha256']:
                    raise ValueError('runtime manifest differs from its draft or bundle')
            except (KeyError, TypeError) as error:
                raise ValueError('runtime manifest is invalid') from error
        else:
            uv = shutil.which('uv')
            if uv is None:
                raise ValueError('offline runtime installation requires uv')
            _validate_install_inputs(Path(source['source_root']) / 'm0')
            runtime = root / ('runtime-' + uuid.uuid4().hex)
            env = {'PATH': os.defpath, 'HOME': str(parent), 'UV_CACHE_DIR': str(cache), 'UV_PYTHON': str(base),
                   'UV_PROJECT_ENVIRONMENT': str(runtime), 'UV_OFFLINE': '1', 'UV_NO_CONFIG': '1',
                   'UV_LINK_MODE': 'copy', 'PYTHONDONTWRITEBYTECODE': '1'}
            try:
                version = subprocess.check_output([str(base), '-I', '-S', '-c',
                    "import sys; print('%d.%d' % sys.version_info[:2])"], env=env,
                    stderr=subprocess.DEVNULL, timeout=30).decode('ascii').strip()
                if version != '3.12':
                    raise ValueError('runtime requires Python 3.12')
                subprocess.run([uv, 'sync', '--project', str(Path(source['source_root']) / 'm0'),
                    '--locked', '--offline', '--no-build', '--no-dev', '--no-install-project', '--link-mode', 'copy'],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=True)
            except (OSError, subprocess.SubprocessError, UnicodeError) as error:
                raise ValueError('offline locked runtime installation failed') from error
            manifest = _runtime_manifest(runtime, base, draft['dependency_lock_sha256'])
            _sync_runtime_tree(runtime)
            _sync_directory(parent)
            if _runtime_manifest(runtime, base, draft['dependency_lock_sha256']) != manifest:
                raise ValueError('runtime changed during durability verification')
            prepare_continuation_source(ledger, draft, checkout=checkout_root, directory=source_root)
            _persist_manifest(manifest_path, _manifest_envelope(manifest, draft['draft_sha256'], source['tree_ref']))
        actual = _runtime_manifest(runtime, base, draft['dependency_lock_sha256'])
        if actual != manifest:
            raise ValueError('runtime differs from its published manifest')
        _sync_runtime_tree(runtime)
        _sync_directory(parent)
        if _runtime_manifest(runtime, base, draft['dependency_lock_sha256']) != manifest:
            raise ValueError('runtime changed during recovery verification')
        if prepare_continuation_source(ledger, draft, checkout=checkout_root, directory=source_root) != source:
            raise ValueError('source evidence changed during runtime preparation')
        return {'scope': 'continuation_runtime_prepared_not_bound', 'draft_sha256': draft['draft_sha256'],
                'tree_ref': source['tree_ref'], 'runtime_ref': 'sha256:' + payload_digest(manifest),
                'runtime': str(runtime), 'runtime_manifest': str(manifest_path)}
    finally:
        os.close(lock_fd)
