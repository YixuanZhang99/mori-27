"""Verify prepared continuation artifacts and bind them in fixture campaigns only."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.clean_source import verify_clean_source
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import _sync_directory
from zoo.circle_packing.continuation_source import _verify_commit_manifest
from zoo.circle_packing.frozen_runtime import _runtime_manifest, _sync_runtime_tree
from zoo.circle_packing.frozen_source import _validate_lock
from zoo.circle_packing.pilot_draft import _read_private_json, _sync_source_tree
from zoo.circle_packing.pilot_plan import build_draft_plan, validate_source_preflight
from zoo.mle_bench_lite.cny_budget import CampaignBudget


@contextmanager
def _locked_existing_bundle(requested):
    root = Path(requested)
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
        raise ValueError('binding requires an existing canonical bundle')
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('binding requires a private owned bundle')
    fd = os.open(root / '.prepare.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        lock = os.fstat(fd)
        if not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.getuid() or \
                stat.S_IMODE(lock.st_mode) != 0o600 or lock.st_nlink != 1:
            raise ValueError('binding bundle lock is invalid')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield root
    finally:
        os.close(fd)


def bind_fixture_continuation(ledger, draft, *, checkout, source_directory, runtime_directory, base_python):
    """Bind verified prepared artifacts to an exact fixture head; never admit a cell."""
    if type(ledger) is not CampaignBudget or not ledger.is_fixture_campaign():
        raise ValueError('continuation artifact binding is restricted to fixture campaigns')
    if type(draft) is not dict:
        raise ValueError('fixture binding requires a continuation draft')
    try:
        existing = ledger.circle_continuation_binding(draft['experiment_id'])
        if existing is None:
            inventory = ledger.circle_continuation_inventory(expected_head=draft['predecessor_head'])
        else:
            if existing['draft'] != draft:
                raise ValueError('fixture continuation identity is already bound to a different draft')
            from zoo.circle_packing.historical_prefix import _temporary_verified_prefix
            with _temporary_verified_prefix(ledger, expected_head=draft['predecessor_head']) as prefix:
                inventory = CampaignBudget(prefix).circle_continuation_inventory(expected_head=draft['predecessor_head'])
        expected = build_continuation_draft(inventory, experiment_id=draft['experiment_id'],
            source_commit=draft['source_commit'], dependency_lock_sha256=draft['dependency_lock_sha256'],
            method_changes=draft['method_changes'])
        if draft != expected:
            raise ValueError('fixture continuation draft differs from the original campaign')
        checkout_root = Path(checkout).resolve(strict=True)
        base = Path(base_python).resolve(strict=True)
        if not Path(checkout).is_absolute() or not Path(base_python).is_absolute() or \
                Path('/usr') not in base.parents or not base.is_file():
            raise ValueError('fixture binding requires an absolute checkout and system Python')
        base_plan = build_draft_plan(inventory['campaign'], source_commit=draft['source_commit'],
                                     dependency_lock_sha256=draft['dependency_lock_sha256'])
        validate_source_preflight(ledger, base_plan, 'vendor-0', checkout=checkout_root,
                                  expected_plan_ref='sha256:' + base_plan['draft_sha256'])
    except (KeyError, TypeError) as error:
        raise ValueError('fixture continuation draft is invalid') from error
    source_request, runtime_request = Path(source_directory), Path(runtime_directory)
    if not source_request.is_absolute() or not runtime_request.is_absolute():
        raise ValueError('fixture binding paths must be absolute')
    source_path, runtime_path = source_request.resolve(strict=True), runtime_request.resolve(strict=True)
    if source_path == runtime_path or source_path in runtime_path.parents or runtime_path in source_path.parents:
        raise ValueError('fixture binding paths must be separate')
    if not (source_path / 'draft.json').is_file() or not (source_path / 'source-manifest.json').is_file() or \
            not (runtime_path / 'runtime-manifest.json').is_file() or \
            (source_path / 'runtime-manifest.json').exists() or (source_path / 'runtime-manifest.json').is_symlink() or \
            (runtime_path / 'draft.json').exists() or (runtime_path / 'draft.json').is_symlink():
        raise ValueError('fixture binding bundle roles differ')
    # Runtime preparation holds its runtime lock while checking source; keep
    # the same role order so these two operations cannot deadlock.
    with ExitStack() as locks:
        for requested in (runtime_request, source_request):
            locks.enter_context(_locked_existing_bundle(requested))
        source_bundle, runtime_bundle = source_path, runtime_path
        ledger_path = ledger.path.resolve(strict=True)
        for left, right in ((source_bundle, runtime_bundle), (source_bundle, checkout_root),
                            (runtime_bundle, checkout_root), (source_bundle, ledger_path),
                            (runtime_bundle, ledger_path)):
            if left == right or left in right.parents or right in left.parents:
                raise ValueError('fixture binding paths must be separate')
        stored_draft = _read_private_json(source_bundle / 'draft.json')
        source_manifest = _read_private_json(source_bundle / 'source-manifest.json')
        envelope = _read_private_json(runtime_bundle / 'runtime-manifest.json')
        if stored_draft != draft or type(envelope) is not dict or \
                set(envelope) != {'schema_version', 'draft_sha256', 'tree_ref', 'runtime'} or \
                type(envelope['schema_version']) is not int or envelope['schema_version'] != 1:
            raise ValueError('fixture binding manifests differ from the original draft')
        tree_ref = 'sha256:' + payload_digest(source_manifest)
        if envelope['draft_sha256'] != draft['draft_sha256'] or envelope['tree_ref'] != tree_ref:
            raise ValueError('fixture runtime belongs to a different draft or source')
        manifest = envelope['runtime']
        try:
            runtime = Path(manifest['root'])
            if type(manifest) is not dict or not runtime.is_absolute() or runtime.parent != runtime_bundle or \
                    re.fullmatch(r'runtime-[0-9a-f]{32}', runtime.name) is None or runtime.is_symlink() or \
                    manifest['base_python'] != str(base) or manifest['lock_sha256'] != draft['dependency_lock_sha256']:
                raise ValueError('fixture runtime manifest differs from its bundle')
        except (KeyError, TypeError) as error:
            raise ValueError('fixture runtime manifest is invalid') from error
        source = source_bundle / 'source'
        _validate_lock(base_plan, source_manifest)
        _verify_commit_manifest(checkout_root, draft['source_commit'], source_manifest)
        verify_clean_source(source, source_manifest, expected_tree_ref=tree_ref)
        if _runtime_manifest(runtime, base, draft['dependency_lock_sha256']) != manifest:
            raise ValueError('fixture runtime differs from its recorded manifest')
        _sync_source_tree(source)
        _sync_runtime_tree(runtime)
        _sync_directory(runtime_bundle.parent)
        verify_clean_source(source, source_manifest, expected_tree_ref=tree_ref)
        if _runtime_manifest(runtime, base, draft['dependency_lock_sha256']) != manifest or \
                _read_private_json(source_bundle / 'draft.json') != draft or \
                _read_private_json(source_bundle / 'source-manifest.json') != source_manifest or \
                _read_private_json(runtime_bundle / 'runtime-manifest.json') != envelope:
            raise ValueError('fixture artifacts changed during verification')
        event = {'kind': 'bind_circle_continuation', 'schema_version': 2,
                 'previous_head': draft['predecessor_head'], 'draft': draft, 'tree_ref': tree_ref,
                 'runtime_ref': 'sha256:' + payload_digest(manifest),
                 'python_sha256': manifest['base_python_sha256'], 'runtime_manifest_sha256': payload_digest(envelope)}
        with ledger._transaction() as (db, _policy, state):
            current = state['governance']['circle_continuations'].get(draft['experiment_id'])
            if existing is not None:
                expected_binding = {key: value for key, value in event.items() if key not in ('kind', 'schema_version')}
                if current != existing or current != expected_binding:
                    raise ValueError('fixture continuation recovery differs from its original binding')
            else:
                if current is not None:
                    raise ValueError('fixture continuation was bound concurrently; retry recovery')
                ledger._append(db, state, event)
        return ledger.circle_continuation_binding(draft['experiment_id'])
