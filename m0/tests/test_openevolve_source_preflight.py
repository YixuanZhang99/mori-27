"""Source preflight checks a real checkout without authorizing execution."""
import hashlib
import subprocess

import pytest

from test_governed_cny_framework import campaign_fixture
from zoo.circle_packing.pilot_plan import build_draft_plan


def checkout(path):
    path.mkdir()
    (path / 'm0').mkdir()
    (path / 'm0' / 'uv.lock').write_bytes(b'locked dependencies\n')
    (path / 'm0' / 'source.py').write_text('value = 1\n')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Fixture')
    git('add', '.')
    git('commit', '-qm', 'fixture')
    return git('rev-parse', 'HEAD')


def draft(campaign, root, commit):
    lock = hashlib.sha256((root / 'm0' / 'uv.lock').read_bytes()).hexdigest()
    plan = build_draft_plan(campaign.manifest_binding(), source_commit=commit,
                            dependency_lock_sha256=lock)
    return plan, 'sha256:' + plan['draft_sha256']


def test_source_preflight_binds_checkout_lock_and_campaign(tmp_path):
    from zoo.circle_packing.pilot_plan import validate_source_preflight
    root = tmp_path / 'checkout'
    commit = checkout(root)
    campaign = campaign_fixture(tmp_path)
    plan, ref = draft(campaign, root, commit)
    result = validate_source_preflight(campaign, plan, 'vendor-0', checkout=root,
                                       expected_plan_ref=ref)
    assert result['source_commit'] == commit
    assert result['dependency_lock_sha256'] == plan['dependency_lock_sha256']
    assert result['cell_id'] == 'vendor-0'


@pytest.mark.parametrize('change', ['tracked', 'untracked', 'lock', 'commit'])
def test_source_preflight_rejects_checkout_divergence(tmp_path, change):
    from zoo.circle_packing.pilot_plan import validate_source_preflight
    root = tmp_path / 'checkout'
    commit = checkout(root)
    campaign = campaign_fixture(tmp_path)
    plan, ref = draft(campaign, root, commit)
    if change == 'tracked':
        (root / 'm0' / 'source.py').write_text('value = 2\n')
    elif change == 'untracked':
        (root / 'm0' / 'extra.py').write_text('value = 2\n')
    elif change == 'lock':
        (root / 'm0' / 'uv.lock').write_bytes(b'different\n')
    else:
        (root / 'm0' / 'source.py').write_text('value = 2\n')
        subprocess.run(['git', '-C', str(root), 'commit', '-qam', 'different'], check=True)
    with pytest.raises(ValueError):
        validate_source_preflight(campaign, plan, 'vendor-0', checkout=root,
                                  expected_plan_ref=ref)


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_source_preflight_rejects_hidden_tracked_modifications(tmp_path, flag):
    from zoo.circle_packing.pilot_plan import validate_source_preflight
    root = tmp_path / 'checkout'
    commit = checkout(root)
    campaign = campaign_fixture(tmp_path)
    plan, ref = draft(campaign, root, commit)
    subprocess.run(['git', '-C', str(root), 'update-index', flag, 'm0/source.py'], check=True)
    (root / 'm0' / 'source.py').write_text('value = 2\n')
    with pytest.raises(ValueError):
        validate_source_preflight(campaign, plan, 'vendor-0', checkout=root,
                                  expected_plan_ref=ref)


def test_source_preflight_rejects_wrong_lock_even_for_clean_checkout(tmp_path):
    from zoo.circle_packing.pilot_plan import validate_source_preflight
    root = tmp_path / 'checkout'
    commit = checkout(root)
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit=commit,
                            dependency_lock_sha256='0' * 64)
    with pytest.raises(ValueError, match='lock'):
        validate_source_preflight(campaign, plan, 'vendor-0', checkout=root,
                                  expected_plan_ref='sha256:' + plan['draft_sha256'])


def test_source_preflight_detects_executable_bit_when_git_config_disables_it(tmp_path):
    from zoo.circle_packing.pilot_plan import validate_source_preflight
    root = tmp_path / 'checkout'
    commit = checkout(root)
    campaign = campaign_fixture(tmp_path)
    plan, ref = draft(campaign, root, commit)
    subprocess.run(['git', '-C', str(root), 'config', 'core.filemode', 'false'], check=True)
    (root / 'm0' / 'source.py').chmod(0o755)
    with pytest.raises(ValueError):
        validate_source_preflight(campaign, plan, 'vendor-0', checkout=root,
                                  expected_plan_ref=ref)


def test_source_preflight_rejects_clean_filter_that_hides_changed_bytes(tmp_path):
    from zoo.circle_packing.pilot_plan import validate_source_preflight
    root = tmp_path / 'checkout'
    checkout(root)
    (root / '.gitattributes').write_text('m0/source.py filter=fixture\n')
    subprocess.run(['git', '-C', str(root), 'add', '.gitattributes'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'attributes'], check=True)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    campaign = campaign_fixture(tmp_path)
    plan, ref = draft(campaign, root, commit)
    sentinel = tmp_path / 'filter-executed'
    subprocess.run(['git', '-C', str(root), 'config', 'filter.fixture.clean',
                    f"touch {sentinel}; sed 's/value = 2/value = 1/'"], check=True)
    (root / 'm0' / 'source.py').write_text('value = 2\n')
    with pytest.raises(ValueError):
        validate_source_preflight(campaign, plan, 'vendor-0', checkout=root,
                                  expected_plan_ref=ref)
    assert not sentinel.exists()
