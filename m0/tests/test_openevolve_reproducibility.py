"""A runtime environment edit cannot impersonate a seed fixed at process startup."""
import os
import subprocess
import sys


def run_child(seed, code):
    env = dict(os.environ)
    env.update(PYTHONHASHSEED=seed, PYTHONPATH=os.pathsep.join(sys.path))
    return subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=15)


def test_hash_seed_must_match_actual_process_not_mutated_environment():
    code = ("import os; os.environ['PYTHONHASHSEED']='0'; "
            "from zoo.circle_packing.reproducibility import require_hash_seed_zero; require_hash_seed_zero()")
    good = run_child('0', code)
    bad = run_child('random', code)
    assert good.returncode == 0
    assert bad.returncode != 0 and 'hash' in bad.stderr.lower()


def test_hash_seed_probe_does_not_write_into_venv(tmp_path):
    import venv
    runtime = tmp_path / 'runtime'
    venv.create(runtime)
    site = next((runtime / 'lib').glob('python*/site-packages'))
    (site / 'fixture_probe.py').write_text('pass\n')
    (site / 'fixture_probe.pth').write_text('import fixture_probe\n')
    child = subprocess.run([str(runtime / 'bin' / 'python'), '-B', '-c',
        'from zoo.circle_packing.reproducibility import require_hash_seed_zero; require_hash_seed_zero()'],
        env={'PATH': os.defpath, 'PYTHONHASHSEED': '0', 'PYTHONPATH': os.pathsep.join(sys.path)},
        capture_output=True, text=True, timeout=15)
    assert child.returncode == 0, child.stderr
    assert not list(site.rglob('*.pyc'))


def test_source_identity_distinguishes_different_dirty_runtime_changes(tmp_path):
    from zoo.circle_packing.reproducibility import fixture_source_identity
    source = tmp_path / 'm0' / 'core' / 'example.py'
    source.parent.mkdir(parents=True)
    source.write_text('value = 1\n')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'm0/core/example.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                    'commit', '-qm', 'fixture'], check=True)
    source.write_text('value = 2\n')
    first = fixture_source_identity(tmp_path)
    source.write_text('value = 3\n')
    second = fixture_source_identity(tmp_path)
    assert first['commit'] == second['commit'] and first['dirty'] and second['dirty']
    assert first['worktree_sha256'] != second['worktree_sha256']
    new_source = tmp_path / 'm0' / 'zoo' / 'new_module.py'
    new_source.parent.mkdir()
    new_source.write_text('value = 4\n')
    third = fixture_source_identity(tmp_path)
    new_source.write_text('value = 5\n')
    fourth = fixture_source_identity(tmp_path)
    assert third['worktree_sha256'] != fourth['worktree_sha256']
