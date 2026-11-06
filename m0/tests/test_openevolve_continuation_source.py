"""The continuation source is durable evidence, not a campaign binding."""
import copy
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_openevolve_continuation_draft import inventory
from test_openevolve_source_preflight import checkout
from zoo.circle_packing.continuation_draft import build_continuation_draft


def prepared(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    commit = checkout(root)
    ledger, before, value = inventory(tmp_path)
    inventory_read = ledger.circle_continuation_inventory
    def fixture_inventory(*, expected_head):
        inventory_read(expected_head=expected_head)
        return copy.deepcopy(value)
    monkeypatch.setattr(ledger, 'circle_continuation_inventory', fixture_inventory)
    draft = build_continuation_draft(value, experiment_id='circle-v2', source_commit=commit,
        dependency_lock_sha256=hashlib.sha256((root / 'm0/uv.lock').read_bytes()).hexdigest(),
        method_changes=['disable thinking in both arms'])
    return ledger, before, draft, root, tmp_path / 'bundle'


def test_prepares_and_reuses_exact_source_without_changing_ledger(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_source import prepare_continuation_source
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    first = prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    assert first['scope'] == 'continuation_source_prepared_not_bound'
    assert (bundle / 'source/m0/source.py').read_text() == 'value = 1\n'
    assert len(first['tree_ref']) == 71 and first['draft_sha256'] == draft['draft_sha256']
    assert prepare_continuation_source(ledger, draft, checkout=root, directory=bundle) == first
    assert ledger.snapshot() == before


def test_interrupted_publish_resumes_without_replacing_evidence(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_source import prepare_continuation_source
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    from zoo.circle_packing import continuation_source as module
    real_publish = module._publish_source
    with monkeypatch.context() as patch:
        def interrupt(source, destination):
            if Path(destination) == bundle / 'source':
                raise OSError('fixture interrupted publication')
            return real_publish(source, destination)
        patch.setattr(module, '_publish_source', interrupt)
        with pytest.raises(OSError, match='fixture interrupted'):
            prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    manifest = (bundle / 'source-manifest.json').read_bytes()
    result = prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    assert (bundle / 'source-manifest.json').read_bytes() == manifest
    assert (bundle / 'source/m0/source.py').is_file() and result['scope'].endswith('not_bound')
    assert ledger.snapshot() == before


@pytest.mark.parametrize('damage', ['source', 'manifest', 'draft', 'stale'])
def test_source_recovery_rejects_tampering_and_stale_head(tmp_path, monkeypatch, damage):
    from zoo.circle_packing.continuation_source import prepare_continuation_source
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    if damage == 'source': (bundle / 'source/m0/source.py').write_text('changed')
    elif damage == 'manifest': (bundle / 'source-manifest.json').write_text('{}')
    elif damage == 'draft': draft['reasoning_effort'] = 'low'
    else: draft['predecessor_head']['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    assert ledger.snapshot() == before


def test_concurrent_preparation_keeps_one_consistent_tree(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_source import prepare_continuation_source
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: prepare_continuation_source(ledger, draft, checkout=root, directory=bundle), range(2)))
    assert results[0] == results[1]
    assert ledger.snapshot() == before


def test_publication_never_replaces_a_racing_empty_directory(tmp_path, monkeypatch):
    import zoo.circle_packing.continuation_source as module
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    original = module._publish_source
    original_inode = []
    def race(stage, destination):
        destination.mkdir(mode=0o700)
        original_inode.append(destination.stat().st_ino)
        original(stage, destination)
    monkeypatch.setattr(module, '_publish_source', race)
    with pytest.raises(OSError):
        module.prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    assert (bundle / 'source').stat().st_ino == original_inode[0]
    assert not list((bundle / 'source').iterdir())
    assert ledger.snapshot() == before


def test_recovery_resyncs_published_source_before_returning_success(tmp_path, monkeypatch):
    import zoo.circle_packing.continuation_source as module
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    sync = module._sync_source_tree
    attempts = []
    def fail_published(path):
        attempts.append(Path(path))
        if Path(path) == bundle / 'source':
            raise OSError('fixture sync failure')
        sync(path)
    with monkeypatch.context() as patch:
        patch.setattr(module, '_sync_source_tree', fail_published)
        with pytest.raises(OSError, match='fixture sync failure'):
            module.prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
        assert (bundle / 'source').is_dir()
        with pytest.raises(OSError, match='fixture sync failure'):
            module.prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    def observe(path):
        attempts.append(Path(path))
        sync(path)
    monkeypatch.setattr(module, '_sync_source_tree', observe)
    module.prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    assert attempts.count(bundle / 'source') >= 3
    assert ledger.snapshot() == before


def test_actual_new_ledger_event_invalidates_prior_source_draft(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_source import prepare_continuation_source
    ledger, before, draft, root, bundle = prepared(tmp_path, monkeypatch)
    prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    ledger.reserve('new-pending', 'a' * 64, 64)
    changed = ledger.snapshot()
    with pytest.raises(ValueError, match='head'):
        prepare_continuation_source(ledger, draft, checkout=root, directory=bundle)
    assert ledger.snapshot() == changed
    assert (bundle / 'source/m0/source.py').read_text() == 'value = 1\n'
