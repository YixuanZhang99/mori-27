"""Continuation runtime preparation uses no provider and never writes the campaign."""
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_openevolve_continuation_source import prepared


def inputs(tmp_path, monkeypatch):
    ledger, before, draft, checkout, source = prepared(tmp_path, monkeypatch)
    cache = tmp_path / 'uv-cache'
    cache.mkdir(mode=0o700)
    return ledger, before, draft, checkout, source, tmp_path / 'runtime-bundle', cache


def fake_install(monkeypatch):
    import zoo.circle_packing.continuation_runtime as module
    calls = []
    real_run = subprocess.run
    monkeypatch.setattr(module, '_validate_install_inputs', lambda _: None)
    def run(args, *, env, **kwargs):
        if len(args) > 1 and args[1] == 'sync':
            assert env['UV_OFFLINE'] == '1' and env['UV_LINK_MODE'] == 'copy'
            assert not any('KEY' in key or 'SECRET' in key or 'TOKEN' in key for key in env)
            root = Path(env['UV_PROJECT_ENVIRONMENT'])
            root.mkdir(mode=0o700)
            (root / 'bin').mkdir()
            (root / 'bin/python').symlink_to('/usr/bin/python3.12')
            (root / 'package.py').write_text('fixture runtime\n')
            calls.append(root)
            time.sleep(.03)
            return subprocess.CompletedProcess(args, 0)
        return real_run(args, env=env, **kwargs)
    monkeypatch.setattr(module.subprocess, 'run', run)
    return calls


def invoke(values):
    from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
    ledger, _before, draft, checkout, source, target, cache = values
    return prepare_continuation_runtime(ledger, draft, checkout=checkout, source_directory=source,
        directory=target, uv_cache=cache, base_python='/usr/bin/python3.12')


def test_prepares_and_recovers_exact_runtime_without_campaign_writes(tmp_path, monkeypatch):
    values = inputs(tmp_path, monkeypatch)
    calls = fake_install(monkeypatch)
    first = invoke(values)
    assert first['scope'] == 'continuation_runtime_prepared_not_bound'
    assert len(first['runtime_ref']) == 71 and len(calls) == 1
    assert Path(first['runtime']).is_dir()
    assert invoke(values) == first and len(calls) == 1
    assert values[0].snapshot() == values[1]


def test_interrupted_manifest_publication_retains_old_attempt_and_recovers(tmp_path, monkeypatch):
    import zoo.circle_packing.continuation_runtime as module
    values = inputs(tmp_path, monkeypatch)
    calls = fake_install(monkeypatch)
    publish = module._persist_manifest
    with monkeypatch.context() as patch:
        def fail(path, value):
            if Path(path).name == 'runtime-manifest.json':
                raise OSError('fixture manifest interruption')
            return publish(path, value)
        patch.setattr(module, '_persist_manifest', fail)
        with pytest.raises(OSError, match='fixture manifest interruption'):
            invoke(values)
    abandoned = calls[0]
    result = invoke(values)
    assert len(calls) == 2 and calls[1] != abandoned and abandoned.is_dir()
    assert Path(result['runtime']) == calls[1]
    assert values[0].snapshot() == values[1]


@pytest.mark.parametrize('damage', ['runtime', 'manifest', 'source', 'stale'])
def test_runtime_recovery_rejects_damaged_or_stale_evidence(tmp_path, monkeypatch, damage):
    values = inputs(tmp_path, monkeypatch)
    fake_install(monkeypatch)
    result = invoke(values)
    if damage == 'runtime': (Path(result['runtime']) / 'package.py').write_text('tampered')
    elif damage == 'manifest': (values[5] / 'runtime-manifest.json').write_text('{}')
    elif damage == 'source': (values[4] / 'source/m0/source.py').write_text('tampered')
    else: values[0].reserve('new-pending', 'a' * 64, 64)
    before = values[0].snapshot()
    with pytest.raises(ValueError): invoke(values)
    assert values[0].snapshot() == before


def test_concurrent_preparation_shares_one_runtime_identity(tmp_path, monkeypatch):
    values = inputs(tmp_path, monkeypatch)
    calls = fake_install(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: invoke(values), range(2)))
    assert result[0] == result[1] and len(calls) == 1
    assert values[0].snapshot() == values[1]


def test_published_runtime_cannot_be_reused_by_a_different_draft(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_draft import build_continuation_draft
    from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
    values = inputs(tmp_path, monkeypatch)
    fake_install(monkeypatch)
    invoke(values)
    ledger, before, draft, checkout, source, target, cache = values
    inv = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    different = build_continuation_draft(inv, experiment_id=draft['experiment_id'],
        source_commit=draft['source_commit'], dependency_lock_sha256=draft['dependency_lock_sha256'],
        method_changes=['a different method'])
    with pytest.raises(ValueError):
        prepare_continuation_runtime(ledger, different, checkout=checkout, source_directory=tmp_path / 'other-source',
            directory=target, uv_cache=cache, base_python='/usr/bin/python3.12')
    assert ledger.snapshot() == before


def test_manifest_hardlink_publication_interruption_recovers_same_runtime(tmp_path, monkeypatch):
    import json
    import zoo.circle_packing.continuation_runtime as module
    values = inputs(tmp_path, monkeypatch)
    calls = fake_install(monkeypatch)
    publish = module._persist_manifest
    with monkeypatch.context() as patch:
        def interrupt(path, value):
            if Path(path).name != 'runtime-manifest.json':
                return publish(path, value)
            data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
            leftover = path.parent / '.mori-runtime-manifest-fixture'
            fd = os.open(leftover, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(leftover, path)
            raise OSError('fixture interrupted hardlink publication')
        patch.setattr(module, '_persist_manifest', interrupt)
        with pytest.raises(OSError, match='fixture interrupted hardlink'):
            invoke(values)
    assert (values[5] / 'runtime-manifest.json').stat().st_nlink == 2
    result = invoke(values)
    assert len(calls) == 1 and Path(result['runtime']) == calls[0]
    assert (values[5] / 'runtime-manifest.json').stat().st_nlink == 1
    assert not (values[5] / '.mori-runtime-manifest-fixture').exists()
    assert values[0].snapshot() == values[1]


def test_rejects_runtime_inside_source_bundle_before_creating_it(tmp_path, monkeypatch):
    from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
    ledger, before, draft, checkout, source, target, cache = inputs(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='separate'):
        prepare_continuation_runtime(ledger, draft, checkout=checkout, source_directory=source,
            directory=source, uv_cache=cache, base_python='/usr/bin/python3.12')
    assert not source.exists() and ledger.snapshot() == before


def test_failed_install_preserves_attempt_and_next_attempt_uses_new_path(tmp_path, monkeypatch):
    import zoo.circle_packing.continuation_runtime as module
    values = inputs(tmp_path, monkeypatch)
    calls = fake_install(monkeypatch)
    install = module.subprocess.run
    with monkeypatch.context() as patch:
        def fail_after_install(args, *, env, **kwargs):
            result = install(args, env=env, **kwargs)
            if len(args) > 1 and args[1] == 'sync':
                raise subprocess.CalledProcessError(1, args)
            return result
        patch.setattr(module.subprocess, 'run', fail_after_install)
        with pytest.raises(ValueError, match='installation failed'):
            invoke(values)
    abandoned = calls[0]
    assert abandoned.is_dir() and not (values[5] / 'runtime-manifest.json').exists()
    result = invoke(values)
    assert len(calls) == 2 and calls[1] != abandoned and abandoned.is_dir()
    assert Path(result['runtime']) == calls[1] and values[0].snapshot() == values[1]
