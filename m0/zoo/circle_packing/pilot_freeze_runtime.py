"""Prepare or recover the original frozen runtime without model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile

from zoo.circle_packing.frozen_runtime import _runtime_manifest, prepare_frozen_runtime, verify_frozen_runtime
from zoo.circle_packing.frozen_source import verify_frozen_source
from zoo.circle_packing.pilot_draft import _read_private_json
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def _persist_manifest(path, manifest):
    """Publish a complete fsynced file without overwriting an existing path."""
    data = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    fd, name = tempfile.mkstemp(prefix='.mori-runtime-manifest-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _repair_manifest_links(path, manifest):
    """Remove only our same-inode publication leftovers after verifying bytes."""
    expected = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    stat.S_IMODE(before.st_mode) != 0o600 or before.st_size != len(expected)):
                raise ValueError('runtime manifest is not a matching private file')
            if before.st_nlink == 1:
                return
            chunks, remaining = [], len(expected) + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(fd)
            if (b''.join(chunks) != expected or
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)):
                raise ValueError('runtime manifest differs from its original binding')
            leftovers = []
            for name in os.listdir(parent_fd):
                if name.startswith('.mori-runtime-manifest-'):
                    candidate = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if (candidate.st_dev, candidate.st_ino) == (before.st_dev, before.st_ino):
                        leftovers.append(name)
            if len(leftovers) != before.st_nlink - 1:
                raise ValueError('runtime manifest has unrecognized hard links')
            for name in leftovers:
                candidate = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (candidate.st_dev, candidate.st_ino) != (before.st_dev, before.st_ino):
                    raise ValueError('runtime manifest publication changed during recovery')
                os.unlink(name, dir_fd=parent_fd)
            if os.fstat(fd).st_nlink != 1:
                raise ValueError('runtime manifest hard links remain unresolved')
            os.fsync(parent_fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def freeze_runtime_bundle(ledger, *, plan, expected_plan_ref, source_root, source_manifest,
                          runtime, manifest_path, uv_cache):
    """Bind the offline runtime or reconstruct its already-anchored manifest."""
    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('runtime preparation requires the original campaign and plan')
    source, runtime, output = Path(source_root), Path(runtime), Path(manifest_path)
    if not all(path.is_absolute() for path in (source, runtime, output)):
        raise ValueError('runtime preparation paths must be absolute')
    parent = output.parent.resolve(strict=True)
    info = parent.stat()
    output = parent / output.name
    source = source.resolve(strict=True)
    runtime = runtime.parent.resolve(strict=True) / runtime.name
    ledger_path = ledger.path.resolve(strict=True)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or \
            output.is_symlink() or output == ledger_path or \
            output == source or source in output.parents or \
            output == runtime or runtime in output.parents:
        raise ValueError('runtime manifest requires a private separate location')
    policy = ledger.manifest_binding()
    source_info = verify_frozen_source(ledger, plan, snapshot=source, manifest=source_manifest,
        expected_plan_ref=expected_plan_ref, expected_campaign_id=policy['campaign_id'])
    binding = ledger.circle_runtime_binding()
    if binding is None:
        if output.exists():
            raise ValueError('unbound runtime manifest already exists')
        result = prepare_frozen_runtime(ledger, plan, snapshot=source, source_manifest=source_manifest,
            expected_plan_ref=expected_plan_ref, expected_campaign_id=policy['campaign_id'],
            destination=runtime, base_python='/usr/bin/python3.12', uv_cache=uv_cache)
        manifest = result['manifest']
    else:
        if binding['plan_ref'] != expected_plan_ref or binding['tree_ref'] != source_info['tree_ref']:
            raise ValueError('runtime belongs to a different frozen pilot')
        manifest = _runtime_manifest(runtime, '/usr/bin/python3.12', plan['dependency_lock_sha256'])
    verified = verify_frozen_runtime(ledger, runtime=runtime, manifest=manifest, base_python='/usr/bin/python3.12')
    if output.exists():
        _repair_manifest_links(output, manifest)
        if _read_private_json(output) != manifest:
            raise ValueError('runtime manifest differs from its original binding')
    else:
        _persist_manifest(output, manifest)
    return {'scope': 'frozen_runtime_bundle', 'runtime_ref': verified['runtime_ref'],
            'runtime': str(runtime), 'runtime_manifest': str(output)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ledger', 'plan', 'expected-plan-ref', 'source-root', 'source-manifest',
                 'runtime', 'manifest-path', 'uv-cache'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    result = freeze_runtime_bundle(CampaignBudget(args.ledger), plan=_read_private_json(Path(args.plan)),
        expected_plan_ref=args.expected_plan_ref, source_root=args.source_root,
        source_manifest=_read_private_json(Path(args.source_manifest)), runtime=args.runtime,
        manifest_path=args.manifest_path, uv_cache=args.uv_cache)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
