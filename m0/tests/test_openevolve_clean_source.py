"""Construct a fixture source tree only from committed Git objects."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_governed_cny_framework import campaign_fixture
from test_openevolve_source_preflight import checkout, draft


def test_export_excludes_ignored_files_and_preserves_committed_bytes(tmp_path):
    from zoo.circle_packing.clean_source import export_clean_source
    root = tmp_path / 'checkout'
    checkout(root)
    (root / '.gitignore').write_text('m0/local-secret\n')
    subprocess.run(['git', '-C', str(root), 'add', '.gitignore'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'ignore local file'], check=True)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    (root / 'm0' / 'local-secret').write_text('fixture-secret-never-exported')
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    result = export_clean_source(ledger, plan, 'vendor-0', checkout=root,
                                 destination=tmp_path / 'export', expected_plan_ref=ref)
    assert result['source_commit'] == commit
    assert (tmp_path / 'export' / 'm0' / 'source.py').read_text() == 'value = 1\n'
    assert not (tmp_path / 'export' / 'm0' / 'local-secret').exists()
    assert not (tmp_path / 'export' / '.git').exists()
    assert result['dependency_lock_sha256'] == plan['dependency_lock_sha256']
    assert all(len(entry['sha256']) == 64 for entry in result['manifest'])


def test_export_rejects_tracked_symlinks_and_does_not_return_partial_tree(tmp_path):
    from zoo.circle_packing.clean_source import export_clean_source
    root = tmp_path / 'checkout'
    checkout(root)
    (root / 'm0' / 'link').symlink_to('/etc/passwd')
    subprocess.run(['git', '-C', str(root), 'add', 'm0/link'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'symlink'], check=True)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    with pytest.raises(ValueError, match='symlink'):
        export_clean_source(ledger, plan, 'vendor-0', checkout=root,
                            destination=tmp_path / 'export', expected_plan_ref=ref)
    assert not (tmp_path / 'export').exists()


def test_export_refuses_existing_destination(tmp_path):
    from zoo.circle_packing.clean_source import export_clean_source
    root = tmp_path / 'checkout'
    commit = checkout(root)
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    destination = tmp_path / 'export'
    destination.mkdir()
    (destination / 'keep').write_text('original')
    with pytest.raises(ValueError, match='destination'):
        export_clean_source(ledger, plan, 'vendor-0', checkout=root,
                            destination=destination, expected_plan_ref=ref)
    assert (destination / 'keep').read_text() == 'original'


@pytest.mark.parametrize('change', ['tracked', 'extra', 'symlink', 'mode', 'missing', 'hardlink'])
def test_snapshot_verification_rejects_later_mutation(tmp_path, change):
    from zoo.circle_packing.clean_source import export_clean_source, verify_clean_source
    root = tmp_path / 'checkout'
    commit = checkout(root)
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    destination = tmp_path / 'export'
    result = export_clean_source(ledger, plan, 'vendor-0', checkout=root,
                                 destination=destination, expected_plan_ref=ref)
    verify_clean_source(destination, result['manifest'], expected_tree_ref=result['tree_ref'])
    if change == 'tracked':
        (destination / 'm0' / 'source.py').write_text('changed')
    elif change == 'extra':
        (destination / 'm0' / 'extra.py').write_text('unexpected')
    elif change == 'symlink':
        (destination / 'm0' / 'link').symlink_to('/etc/passwd')
    elif change == 'mode':
        (destination / 'm0' / 'source.py').chmod(0o700)
    elif change == 'missing':
        (destination / 'm0' / 'source.py').unlink()
    else:
        outside = tmp_path / 'outside.py'
        outside.write_text('value = 1\n')
        (destination / 'm0' / 'source.py').unlink()
        os.link(outside, destination / 'm0' / 'source.py')
    with pytest.raises(ValueError):
        verify_clean_source(destination, result['manifest'], expected_tree_ref=result['tree_ref'])


def test_snapshot_verification_rejects_fifo_without_blocking(tmp_path):
    from zoo.circle_packing.clean_source import export_clean_source
    root = tmp_path / 'checkout'
    commit = checkout(root)
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    destination = tmp_path / 'export'
    result = export_clean_source(ledger, plan, 'vendor-0', checkout=root,
                                 destination=destination, expected_plan_ref=ref)
    path = destination / 'm0' / 'source.py'
    path.unlink()
    os.mkfifo(path)
    script = """import json,sys
from zoo.circle_packing.clean_source import verify_clean_source
try:
    verify_clean_source(sys.argv[1], json.loads(sys.argv[2]), expected_tree_ref=sys.argv[3])
except ValueError:
    sys.exit(0)
sys.exit(1)
"""
    result = subprocess.run([sys.executable, '-c', script, str(destination), json.dumps(result['manifest']),
                             result['tree_ref']], env={'PATH': os.defpath,
                             'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    assert result.returncode == 0
