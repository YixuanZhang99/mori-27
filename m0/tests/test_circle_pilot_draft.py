"""Prepare a reproducible pilot draft without starting any paid work."""
import json
import os
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from zoo.circle_packing.pilot_draft import freeze_source_bundle, write_pilot_draft
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def test_draft_binds_clean_commit_and_original_campaign_without_changing_ledger(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', str(repository), str(checkout)], check=True)
    # The development checkout can be detached; clone its exact current commit.
    head = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', head], check=True)
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    output = tmp_path / 'plan.json'
    before = ledger.snapshot()['journal_head']
    result = write_pilot_draft(ledger, checkout=checkout, destination=output)
    plan = json.loads(output.read_text())
    assert output.stat().st_mode & 0o777 == 0o600
    assert plan['source_commit'] == head and plan['campaign_id'] == ledger.manifest_binding()['campaign_id']
    assert result['plan_ref'] == 'sha256:' + plan['draft_sha256']
    assert ledger.snapshot()['journal_head'] == before
    cli = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.pilot_draft',
                          '--ledger', str(ledger.path), '--checkout', str(checkout),
                          '--destination', str(tmp_path / 'cli-plan.json')],
                         env={'PATH': os.defpath, 'PYTHONPATH': str(repository / 'm0')},
                         capture_output=True, text=True, timeout=60)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)['plan_ref'] == result['plan_ref']
    assert json.loads((tmp_path / 'cli-plan.json').read_text()) == plan
    with pytest.raises(ValueError):
        write_pilot_draft(ledger, checkout=checkout, destination=output)
    (checkout / 'm0' / 'uv.lock').write_text('changed')
    with pytest.raises(ValueError):
        write_pilot_draft(ledger, checkout=checkout, destination=tmp_path / 'dirty.json')
    assert not (tmp_path / 'dirty.json').exists() and ledger.snapshot()['journal_head'] == before


def test_source_bundle_can_resume_if_anchor_fails_without_losing_original_manifest(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[2]
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', str(repository), str(checkout)], check=True)
    head = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', head], check=True)
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    # Exercise sync separately on a small real tree; the bundle test checks the
    # ordering and failure behavior without thousands of redundant disk syncs.
    monkeypatch.setattr('zoo.circle_packing.pilot_draft._sync_source_tree', lambda _: None)
    draft = write_pilot_draft(ledger, checkout=checkout, destination=tmp_path / 'plan.json')
    plan = json.loads((tmp_path / 'plan.json').read_text())
    bundle = tmp_path / 'bundle'
    before = ledger.snapshot()['journal_head']
    with monkeypatch.context() as patch:
        patch.setattr(ledger, 'freeze_circle_pilot', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('interrupted')))
        with pytest.raises(RuntimeError, match='interrupted'):
            freeze_source_bundle(ledger, plan=plan, expected_plan_ref=draft['plan_ref'],
                                 checkout=checkout, directory=bundle)
    assert ledger.snapshot()['journal_head'] == before
    assert (bundle / 'source-manifest.json').is_file() and (bundle / 'source').is_dir()
    manifest_path = bundle / 'source-manifest.json'
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    entry = next(item for item in manifest if item['path'] == 'README.md')
    source_file = bundle / 'source' / entry['path']
    original_source = source_file.read_bytes()
    forged = b'forged source\n'
    source_file.write_bytes(forged)
    entry.update(size=len(forged), sha256=hashlib.sha256(forged).hexdigest(),
                 oid=hashlib.sha1(b'blob ' + str(len(forged)).encode() + b'\0' + forged,
                                  usedforsecurity=False).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        freeze_source_bundle(ledger, plan=plan, expected_plan_ref=draft['plan_ref'],
                             checkout=checkout, directory=bundle)
    assert ledger.snapshot()['journal_head'] == before
    source_file.write_bytes(original_source)
    manifest_path.write_bytes(original_manifest)
    with monkeypatch.context() as patch:
        patch.setattr('zoo.circle_packing.pilot_draft._sync_source_tree',
                      lambda _: (_ for _ in ()).throw(OSError('sync failed')))
        with pytest.raises(OSError, match='sync failed'):
            freeze_source_bundle(ledger, plan=plan, expected_plan_ref=draft['plan_ref'],
                                 checkout=checkout, directory=bundle)
    assert ledger.snapshot()['journal_head'] == before
    original_freeze = ledger.freeze_circle_pilot
    def freeze_then_interrupt(*args, **kwargs):
        original_freeze(*args, **kwargs)
        raise RuntimeError('after anchor')
    with monkeypatch.context() as patch:
        patch.setattr(ledger, 'freeze_circle_pilot', freeze_then_interrupt)
        with pytest.raises(RuntimeError, match='after anchor'):
            freeze_source_bundle(ledger, plan=plan, expected_plan_ref=draft['plan_ref'],
                                 checkout=checkout, directory=bundle)
    anchored = ledger.snapshot()['journal_head']
    result = freeze_source_bundle(ledger, plan=plan, expected_plan_ref=draft['plan_ref'],
                                  checkout=checkout, directory=bundle)
    assert ledger.circle_pilot_binding()['plan_ref'] == draft['plan_ref']
    assert result['tree_ref'] == ledger.circle_pilot_binding()['tree_ref']
    assert ledger.snapshot()['journal_head'] == anchored
    assert freeze_source_bundle(ledger, plan=plan, expected_plan_ref=draft['plan_ref'],
                                checkout=checkout, directory=bundle) == result
    assert ledger.snapshot()['journal_head'] == anchored
    cli = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.pilot_freeze_source',
        '--ledger', str(ledger.path), '--plan', str(tmp_path / 'plan.json'),
        '--expected-plan-ref', draft['plan_ref'], '--checkout', str(checkout), '--directory', str(bundle)],
        env={'PATH': os.defpath, 'PYTHONPATH': str(repository / 'm0')},
        capture_output=True, text=True, timeout=60)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout) == result and ledger.snapshot()['journal_head'] == anchored


def test_source_sync_flushes_files_directories_and_bundle_parent(tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_draft import _sync_source_tree
    bundle = tmp_path / 'bundle'
    source = bundle / 'source'
    nested = source / 'subdir'
    nested.mkdir(parents=True)
    (source / 'one').write_text('one')
    (nested / 'two').write_text('two')
    original, seen = os.fsync, []
    def sync(fd):
        seen.append(os.fstat(fd).st_ino)
        original(fd)
    monkeypatch.setattr(os, 'fsync', sync)
    _sync_source_tree(source)
    assert set(seen) == {path.stat().st_ino for path in
                         (tmp_path, bundle, source, nested, source / 'one', nested / 'two')}


def test_runtime_sync_flushes_regular_files_and_directories_without_following_symlinks(tmp_path, monkeypatch):
    from zoo.circle_packing.frozen_runtime import _sync_runtime_tree
    runtime = tmp_path / 'runtime'
    nested = runtime / 'bin'
    nested.mkdir(parents=True)
    (nested / 'python').write_text('runtime')
    (nested / 'python-link').symlink_to('python')
    original, seen = os.fsync, []
    def sync(fd):
        seen.append(os.fstat(fd).st_ino)
        original(fd)
    monkeypatch.setattr(os, 'fsync', sync)
    _sync_runtime_tree(runtime)
    assert set(seen) == {path.stat().st_ino for path in (tmp_path, runtime, nested, nested / 'python')}
