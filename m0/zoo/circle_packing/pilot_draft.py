"""Create a credential-free pilot draft for an exact clean checkout.

This command does not freeze the campaign, reserve funds or start a cell.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from zoo.circle_packing.pilot_plan import build_draft_plan, validate_source_preflight
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def _write_private_json(path, value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _read_private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or \
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 32 * 1024 * 1024:
            raise ValueError('pilot bundle file must be private and bounded')
        raw = stream.read(32 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    if len(raw) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('pilot bundle file changed during reading')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate pilot bundle key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite pilot bundle')))


def _sync_source_tree(source):
    """Durably persist the exported files and their directory entries."""
    def onerror(error):
        raise error
    for directory, dirs, files in os.walk(source, topdown=False, followlinks=False, onerror=onerror):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError('source snapshot contains a symlink')
        for name in files:
            fd = os.open(Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('source snapshot file is not a private regular file')
                os.fsync(fd)
            finally:
                os.close(fd)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    for directory in (Path(source).parent, Path(source).parent.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def freeze_source_bundle(ledger, *, plan, expected_plan_ref, checkout, directory):
    """Persist original source evidence before anchoring it to the campaign.

    An existing complete bundle may resume the same interrupted freeze. It may
    not be used to replace an already anchored source or grant a cell.
    """
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.clean_source import export_clean_source, verify_clean_source
    from zoo.circle_packing.frozen_source import _validate_lock
    from zoo.circle_packing.pilot_plan import validate_draft_cell

    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('source freeze requires the original campaign and plan')
    root, checkout = Path(directory), Path(checkout)
    if not root.is_absolute() or not checkout.is_absolute():
        raise ValueError('source freeze paths must be absolute')
    validate_draft_cell(ledger, plan, 'vendor-0', expected_plan_ref=expected_plan_ref)
    parent = root.parent.resolve(strict=True)
    checkout = checkout.resolve(strict=True)
    root = parent / root.name
    info = parent.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or \
            root.is_symlink() or root == checkout or root in checkout.parents or checkout in root.parents or \
            root == ledger.path.resolve(strict=True) or root in ledger.path.resolve(strict=True).parents:
        raise ValueError('source bundle requires a fresh private separate location')
    if not root.exists():
        root.mkdir(mode=0o700)
        _write_private_json(root / 'plan.json', plan)
        result = export_clean_source(ledger, plan, 'vendor-0', checkout=checkout,
                                     destination=root / 'source', expected_plan_ref=expected_plan_ref)
        _validate_lock(plan, result['manifest'])
        _write_private_json(root / 'source-manifest.json', result['manifest'])
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('source bundle must be a private directory')
    if _read_private_json(root / 'plan.json') != plan:
        raise ValueError('source bundle plan differs from the requested plan')
    manifest = _read_private_json(root / 'source-manifest.json')
    tree_ref = 'sha256:' + payload_digest(manifest)
    _validate_lock(plan, manifest)
    verify_clean_source(root / 'source', manifest, expected_tree_ref=tree_ref)
    validate_source_preflight(ledger, plan, 'vendor-0', checkout=checkout, expected_plan_ref=expected_plan_ref)
    env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0'}
    try:
        tree = subprocess.check_output(['git', '-C', str(checkout), 'ls-tree', '-r', '-l', '-z',
                                        '--full-tree', plan['source_commit']], env=env,
                                       stderr=subprocess.DEVNULL, timeout=30)
        entries = []
        for raw in tree.split(b'\0'):
            if raw:
                header, name = raw.split(b'\t', 1)
                mode, kind, oid, size = header.decode('ascii').split()
                if kind != 'blob':
                    raise ValueError('pinned source tree contains a non-blob entry')
                entries.append((name.decode('utf-8'), mode, oid, int(size)))
        observed = [(row['path'], row['mode'], row['oid'], row['size']) for row in manifest]
        if observed != entries:
            raise ValueError('source manifest differs from the pinned Git tree')
    except (OSError, subprocess.SubprocessError, UnicodeError, KeyError, TypeError) as error:
        raise ValueError('cannot verify the pinned source tree') from error
    expected = {'plan_ref': expected_plan_ref, 'tree_ref': tree_ref,
                'wallclock_seconds': plan['limits']['wallclock_seconds'], 'require_runtime': True}
    binding = ledger.circle_pilot_binding()
    if binding is None:
        _sync_source_tree(root / 'source')
        verify_clean_source(root / 'source', manifest, expected_tree_ref=tree_ref)
        ledger.freeze_circle_pilot(expected_plan_ref, tree_ref, plan['limits']['wallclock_seconds'],
                                   require_runtime=True)
        binding = ledger.circle_pilot_binding()
    if binding != expected:
        raise ValueError('campaign is frozen to a different source bundle')
    return {'scope': 'frozen_source_bundle', 'plan_ref': expected_plan_ref, 'tree_ref': tree_ref,
            'source_root': str(root / 'source'), 'source_manifest': str(root / 'source-manifest.json')}


def write_pilot_draft(ledger, *, checkout, destination):
    """Write one non-overwriting plan using the current ledger and clean Git tree."""
    if type(ledger) is not CampaignBudget:
        raise ValueError('pilot draft requires the original campaign')
    root, destination = Path(checkout), Path(destination)
    if not root.is_absolute() or not destination.is_absolute():
        raise ValueError('checkout and destination must be absolute')
    try:
        root = root.resolve(strict=True)
        parent = destination.parent.resolve(strict=True)
        if destination.is_symlink() or destination.exists() or not destination.name or \
                destination.name in ('.', '..') or root == parent or root in parent.parents or \
                destination == ledger.path.resolve(strict=True):
            raise ValueError('pilot draft destination must be fresh and separate')
        info = parent.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('pilot draft requires a private destination directory')
        state = ledger.snapshot()
        if state['pending_calls'] or state.get('protected_micro_cny', 0) or \
                state.get('protection_breaches', []) or ledger.circle_pilot_binding() is not None:
            raise ValueError('pilot draft requires a quiescent unfrozen campaign')
        env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0'}
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                         env=env, stderr=subprocess.DEVNULL, timeout=30).decode('ascii').strip()
        lock = hashlib.sha256((root / 'm0' / 'uv.lock').read_bytes()).hexdigest()
        plan = build_draft_plan(ledger.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)
        ref = 'sha256:' + plan['draft_sha256']
        validate_source_preflight(ledger, plan, 'mori-0', checkout=root, expected_plan_ref=ref)
        if ledger.snapshot()['journal_head'] != state['journal_head']:
            raise ValueError('campaign changed during pilot draft preparation')
        encoded = json.dumps(plan, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent_fd)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return {'scope': 'non_executable_pilot_draft', 'plan_ref': ref,
                'plan_path': str(parent / destination.name), 'source_commit': commit,
                'campaign_head': state['journal_head'], 'remaining_micro_cny': state['remaining_micro_cny']}
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError('cannot prepare a pilot draft from the current checkout') from error


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ledger', 'checkout', 'destination'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(write_pilot_draft(CampaignBudget(args.ledger), checkout=args.checkout,
                                       destination=args.destination), sort_keys=True))


if __name__ == '__main__':
    main()
