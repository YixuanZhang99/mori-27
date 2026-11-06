"""Bind verified fixture artifacts without granting live work."""
import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytestmark = pytest.mark.linux

from test_openevolve_continuation_event import fixture_pair_ledger
from test_openevolve_continuation_runtime import fake_install
from test_openevolve_source_preflight import checkout
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def prepared(tmp_path, monkeypatch, *, source_name='source-bundle', runtime_name='runtime-bundle'):
    ledger, proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    inv = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    source_checkout = tmp_path / 'checkout'
    commit = checkout(source_checkout)
    draft = build_continuation_draft(inv, experiment_id='circle-v2', source_commit=commit,
        dependency_lock_sha256=hashlib.sha256((source_checkout / 'm0/uv.lock').read_bytes()).hexdigest(),
        method_changes=['fixture continuation'])
    cache = tmp_path / 'cache'
    cache.mkdir(mode=0o700)
    fake_install(monkeypatch)
    source, runtime = tmp_path / source_name, tmp_path / runtime_name
    artifacts = prepare_continuation_runtime(ledger, draft, checkout=source_checkout, source_directory=source,
        directory=runtime, uv_cache=cache, base_python='/usr/bin/python3.12')
    return ledger, proof, before, draft, source_checkout, source, runtime, artifacts


def bind(values):
    from zoo.circle_packing.continuation_binding import bind_fixture_continuation
    ledger, _proof, _before, draft, checkout_root, source, runtime, _artifacts = values
    return bind_fixture_continuation(ledger, draft, checkout=checkout_root, source_directory=source,
                                     runtime_directory=runtime, base_python='/usr/bin/python3.12')


def test_binding_verifies_artifacts_and_preserves_original_campaign(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, proof, before, draft, _checkout, _source, _runtime, artifacts = values
    result = bind(values)
    assert result['draft'] == draft and result['tree_ref'] == artifacts['tree_ref']
    assert result['runtime_ref'] == artifacts['runtime_ref']
    assert ledger.circle_continuation_binding('circle-v2') == result
    assert ledger.first_pair_audit() == proof
    after = ledger.snapshot()
    assert after['journal_head']['seq'] == before['journal_head']['seq'] + 1
    assert after['remaining_micro_cny'] == before['remaining_micro_cny']
    with pytest.raises(ValueError):
        ledger.claim_cell_deadline('circle-v2--mori-0', 'sha256:' + draft['draft_sha256'], 'a' * 64, seconds=2700)
    assert ledger.snapshot() == after


@pytest.mark.parametrize('damage', ['source', 'source_manifest', 'runtime', 'runtime_manifest', 'draft', 'missing'])
def test_binding_rejects_tampered_or_missing_evidence_without_event(tmp_path, monkeypatch, damage):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, before, draft, _checkout, source, runtime, artifacts = values
    if damage == 'source': (source / 'source/m0/source.py').write_text('tampered')
    elif damage == 'source_manifest': (source / 'source-manifest.json').write_text('{}')
    elif damage == 'runtime': (Path(artifacts['runtime']) / 'package.py').write_text('tampered')
    elif damage == 'runtime_manifest': (runtime / 'runtime-manifest.json').write_text('{}')
    elif damage == 'draft': draft['method_changes'] = ['tampered']
    else: (runtime / 'runtime-manifest.json').unlink()
    with pytest.raises((ValueError, OSError)):
        bind(values)
    assert ledger.snapshot() == before


def test_real_campaign_rejected_without_artifact_creation(tmp_path):
    from zoo.circle_packing.continuation_binding import bind_fixture_continuation
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    before = ledger.snapshot()
    source, runtime = tmp_path / 'source', tmp_path / 'runtime'
    with pytest.raises(ValueError, match='fixture'):
        bind_fixture_continuation(ledger, {}, checkout=tmp_path, source_directory=source,
                                  runtime_directory=runtime, base_python='/usr/bin/python3.12')
    assert ledger.snapshot() == before and not source.exists() and not runtime.exists()


def test_concurrent_fixture_binding_appends_only_once(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, before, *_rest = values
    def attempt(_):
        try:
            bind(values)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert any(outcomes)  # A late caller may legitimately recover the same committed identity.
    assert ledger.snapshot()['journal_head']['seq'] == before['journal_head']['seq'] + 1


def test_binding_rejects_overlapping_bundles_before_locking(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_binding import bind_fixture_continuation
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, before, draft, checkout_root, source, _runtime, _artifacts = values
    with pytest.raises(ValueError, match='separate'):
        bind_fixture_continuation(ledger, draft, checkout=checkout_root, source_directory=source,
                                  runtime_directory=source, base_python='/usr/bin/python3.12')
    assert ledger.snapshot() == before


def test_binding_and_runtime_recovery_have_compatible_lock_order(tmp_path, monkeypatch):
    import multiprocessing
    import threading
    from contextlib import contextmanager
    import zoo.circle_packing.continuation_binding as binding_module
    import zoo.circle_packing.continuation_runtime as runtime_module
    values = prepared(tmp_path, monkeypatch, source_name='a-source', runtime_name='z-runtime')
    ledger, _proof, _before, draft, checkout_root, source, runtime, _artifacts = values
    cache = tmp_path / 'cache'
    queue = multiprocessing.get_context('fork').Queue()
    def child():
        runtime_locked, source_locked = threading.Event(), threading.Event()
        real_manifest, real_lock = runtime_module._runtime_manifest, binding_module._locked_existing_bundle
        first = [True]
        def intercept_manifest(*args, **kwargs):
            if first[0]:
                first[0] = False
                runtime_locked.set()
                source_locked.wait(1)
            return real_manifest(*args, **kwargs)
        @contextmanager
        def intercept_lock(path):
            with real_lock(path) as locked:
                if Path(path) == source:
                    source_locked.set()
                yield locked
        runtime_module._runtime_manifest = intercept_manifest
        binding_module._locked_existing_bundle = intercept_lock
        errors = []
        def recover():
            try:
                runtime_module.prepare_continuation_runtime(ledger, draft, checkout=checkout_root,
                    source_directory=source, directory=runtime, uv_cache=cache, base_python='/usr/bin/python3.12')
            except Exception as error: errors.append(type(error).__name__)
        def run_binding():
            try: bind(values)
            except Exception as error: errors.append(type(error).__name__)
        first_thread = threading.Thread(target=recover, daemon=True)
        second_thread = threading.Thread(target=run_binding, daemon=True)
        first_thread.start()
        if not runtime_locked.wait(10):
            queue.put('runtime lock was not reached'); return
        second_thread.start()
        first_thread.join(12); second_thread.join(12)
        queue.put('deadlock' if first_thread.is_alive() or second_thread.is_alive() else errors)
    proc = multiprocessing.get_context('fork').Process(target=child)
    proc.start(); proc.join(30)
    if proc.is_alive():
        proc.terminate(); proc.join(5)
        pytest.fail('binding and runtime preparation did not complete')
    assert proc.exitcode == 0 and queue.get(timeout=3) == []


def test_binding_rejects_swapped_bundle_roles_before_acquiring_locks(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_binding import bind_fixture_continuation
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, before, draft, checkout_root, source, runtime, _artifacts = values
    with pytest.raises(ValueError, match='roles'):
        bind_fixture_continuation(ledger, draft, checkout=checkout_root, source_directory=runtime,
                                  runtime_directory=source, base_python='/usr/bin/python3.12')
    assert ledger.snapshot() == before


def test_interrupted_after_binding_recovers_same_identity_without_new_event(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, _before, _draft, _checkout, _source, _runtime, artifacts = values
    original = bind(values)
    head = ledger.snapshot()
    assert bind(values) == original and ledger.snapshot() == head
    (Path(artifacts['runtime']) / 'package.py').write_text('changed after binding')
    with pytest.raises(ValueError): bind(values)
    assert ledger.snapshot() == head


def test_recovery_after_interruption_between_commit_and_return(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, before, *_rest = values
    read_binding = ledger.circle_continuation_binding
    calls = [0]
    with monkeypatch.context() as patch:
        def interrupt(experiment_id):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError('fixture interrupted after commit')
            return read_binding(experiment_id)
        patch.setattr(ledger, 'circle_continuation_binding', interrupt)
        with pytest.raises(RuntimeError, match='after commit'):
            bind(values)
    after = ledger.snapshot()
    assert after['journal_head']['seq'] == before['journal_head']['seq'] + 1
    result = bind(values)
    assert result == ledger.circle_continuation_binding('circle-v2') and ledger.snapshot() == after
