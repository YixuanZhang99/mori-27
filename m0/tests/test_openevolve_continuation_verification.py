"""Reverify a bound continuation's actual source and runtime before use."""
import copy
from pathlib import Path
import pytest

from test_openevolve_continuation_binding import bind, prepared

pytestmark = pytest.mark.linux


def test_bound_fixture_artifacts_are_reverified_without_changing_ledger(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_binding import verify_bound_fixture_continuation
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, _, source, runtime, artifacts = values
    binding = bind(values)
    before = ledger.snapshot()
    result = verify_bound_fixture_continuation(ledger, draft, source_directory=source,
        runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=before['journal_head'])
    assert result['tree_ref'] == binding['tree_ref'] and result['runtime_ref'] == binding['runtime_ref']
    assert result['source'] == str(source / 'source') and result['runtime'] == artifacts['runtime']
    assert ledger.snapshot() == before
    altered = copy.deepcopy(draft)
    altered['cells'][0]['seed'] = False
    with pytest.raises(ValueError):
        verify_bound_fixture_continuation(ledger, altered, source_directory=source,
            runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=before['journal_head'])
    stale = dict(before['journal_head'], sha256='0' * 64)
    with pytest.raises(ValueError):
        verify_bound_fixture_continuation(ledger, draft, source_directory=source,
            runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=stale)
    assert ledger.snapshot() == before


@pytest.mark.parametrize('damage', ['source', 'runtime', 'source_manifest', 'runtime_manifest'])
def test_bound_fixture_rejects_mutated_artifacts(tmp_path, monkeypatch, damage):
    from zoo.circle_packing.continuation_binding import verify_bound_fixture_continuation
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, _, source, runtime, artifacts = values
    bind(values)
    before = ledger.snapshot()
    paths = {'source': source / 'source/m0/source.py', 'runtime': Path(artifacts['runtime']) / 'package.py',
             'source_manifest': source / 'source-manifest.json', 'runtime_manifest': runtime / 'runtime-manifest.json'}
    paths[damage].write_text('tampered')
    with pytest.raises((ValueError, OSError)):
        verify_bound_fixture_continuation(ledger, draft, source_directory=source,
            runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=before['journal_head'])
    assert ledger.snapshot() == before


def test_bound_verification_rejects_unverified_event_and_real_campaign(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_binding import verify_bound_fixture_continuation
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    values = prepared(tmp_path, monkeypatch)
    ledger, _, before, draft, _, source, runtime, _ = values
    event = {'kind': 'bind_circle_continuation', 'schema_version': 2,
             'previous_head': before['journal_head'], 'draft': draft,
             'tree_ref': 'sha256:' + '8' * 64, 'runtime_ref': 'sha256:' + '9' * 64,
             'python_sha256': 'a' * 64, 'runtime_manifest_sha256': 'b' * 64}
    with ledger._transaction() as (db, _policy, state):
        ledger._append(db, state, event)
    snapshot = ledger.snapshot()
    with pytest.raises(ValueError):
        verify_bound_fixture_continuation(ledger, draft, source_directory=source,
            runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=snapshot['journal_head'])
    assert ledger.snapshot() == snapshot
    real = CampaignBudget.create(tmp_path / 'real.db')
    before_real = real.snapshot()
    with pytest.raises(ValueError):
        verify_bound_fixture_continuation(real, draft, source_directory=source,
            runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=before_real['journal_head'])
    assert real.snapshot() == before_real


def test_bound_verification_rejects_overlapping_bundles_without_locking(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_binding import verify_bound_fixture_continuation
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, _, source, _, _ = values
    bind(values)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='separate'):
        verify_bound_fixture_continuation(ledger, draft, source_directory=source,
            runtime_directory=source, base_python='/usr/bin/python3.12', expected_head=before['journal_head'])
    assert ledger.snapshot() == before


def test_swapped_roles_are_rejected_before_lock_acquisition(tmp_path, monkeypatch):
    import zoo.circle_packing.continuation_binding as module
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, _, source, runtime, _ = values
    bind(values)
    before = ledger.snapshot()
    def forbidden(*_args):
        raise AssertionError('swapped artifacts must fail before taking a lock')
    monkeypatch.setattr(module, '_locked_existing_bundle', forbidden)
    with pytest.raises(ValueError, match='roles'):
        module.verify_bound_fixture_continuation(ledger, draft, source_directory=runtime,
            runtime_directory=source, base_python='/usr/bin/python3.12', expected_head=before['journal_head'])
    assert ledger.snapshot() == before


def test_normal_and_swapped_verification_do_not_deadlock(tmp_path, monkeypatch):
    import multiprocessing
    import threading
    from contextlib import contextmanager
    import zoo.circle_packing.continuation_binding as module
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, _, source, runtime, _ = values
    bind(values)
    head = ledger.snapshot()['journal_head']
    queue = multiprocessing.get_context('fork').Queue()
    def child():
        held, swapped_finished = threading.Event(), threading.Event()
        original = module._locked_existing_bundle
        @contextmanager
        def controlled(path):
            with original(path) as root:
                if path == runtime and threading.current_thread().name == 'normal':
                    held.set()
                    if not swapped_finished.wait(5):
                        raise RuntimeError('swapped call did not finish')
                yield root
        module._locked_existing_bundle = controlled
        errors = []
        def normal():
            try:
                module.verify_bound_fixture_continuation(ledger, draft, source_directory=source,
                    runtime_directory=runtime, base_python='/usr/bin/python3.12', expected_head=head)
            except Exception as error:
                errors.append(repr(error))
        def swapped():
            try:
                module.verify_bound_fixture_continuation(ledger, draft, source_directory=runtime,
                    runtime_directory=source, base_python='/usr/bin/python3.12', expected_head=head)
                errors.append('swapped call was accepted')
            except ValueError:
                pass
            except Exception as error:
                errors.append(repr(error))
            finally:
                swapped_finished.set()
        first = threading.Thread(target=normal, name='normal', daemon=True)
        first.start()
        if not held.wait(5):
            queue.put(['normal call did not lock runtime']); return
        second = threading.Thread(target=swapped, daemon=True)
        second.start()
        first.join(10); second.join(10)
        queue.put(['deadlock'] if first.is_alive() or second.is_alive() else errors)
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start(); process.join(20)
    if process.is_alive():
        process.terminate(); process.join(5)
        pytest.fail('concurrent verification did not complete')
    assert process.exitcode == 0 and queue.get(timeout=3) == []
