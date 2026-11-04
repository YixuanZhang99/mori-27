from pathlib import Path
import json
import os
import py_compile
import shlex
import subprocess
import sys
import pytest

from zoo.mle_bench_lite import pilot


def test_dependency_identity_changes_when_installed_bytes_change(tmp_path):
    snapshot = getattr(pilot, '_comparison_dependency_identity', None)
    assert callable(snapshot), 'comparison must freeze dependency bytes before launching'
    packages = tmp_path / 'packages'
    packages.mkdir()
    (packages / 'module.py').write_text('version = 1\n')
    original = snapshot([packages])
    assert original == snapshot([packages])
    (packages / 'module.py').write_text('version = 2\n')
    assert original != snapshot([packages])


def test_bootstrap_ignores_startup_hooks_and_refuses_changed_dependency(tmp_path):
    bootstrap = Path(pilot.__file__).with_name('comparison_bootstrap.py')
    assert bootstrap.is_file(), 'comparison needs an isolated pre-import bootstrap'
    packages = tmp_path / 'packages'
    packages.mkdir()
    marker = tmp_path / 'startup-hook-ran'
    (packages / 'sitecustomize.py').write_text(f'open({str(marker)!r}, "w").write("bad")\n')
    (packages / 'fixture_entry.py').write_text('print("fixture ran")\n')
    identity = pilot._comparison_dependency_identity([packages])
    command = [sys.executable, '-I', '-S', '-B', str(bootstrap), json.dumps(identity),
               str(tmp_path), str(tmp_path), 'fixture_entry']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'fixture ran'
    assert not marker.exists()
    (packages / 'fixture_entry.py').write_text('print("changed")\n')
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode != 0 and 'dependency identity changed' in refused.stderr
    assert not marker.exists()


def test_formal_comparison_command_uses_isolated_bootstrap(tmp_path):
    identity = {str(tmp_path): 'a' * 64}
    command = pilot._comparison_command('fixture', 5_000_000, 120, 3, arm='one_control',
        spending_ledger_path=tmp_path / 'campaign.db', runtime_identity=identity,
        official_root=tmp_path / 'official', pycache_root=tmp_path / 'empty-cache')
    args = shlex.split(command)
    assert args[1:5] == ['-I', '-S', '-B', '-X']
    assert args[5].startswith('pycache_prefix=')
    assert args[6].endswith('comparison_bootstrap.py')
    assert json.loads(args[7].replace('{{', '{').replace('}}', '}')) == identity
    assert args[10] == 'zoo.mle_bench_lite.composed_agent'


def test_bootstrap_keeps_standard_library_ahead_of_dependency_roots(tmp_path):
    packages = tmp_path / 'packages'
    packages.mkdir()
    (packages / 'fractions.py').write_text('raise RuntimeError("shadowed stdlib")\n')
    (packages / 'fixture_entry.py').write_text('import fractions; print(fractions.Fraction(1, 2))\n')
    identity = pilot._comparison_dependency_identity([packages])
    bootstrap = Path(pilot.__file__).with_name('comparison_bootstrap.py')
    command = [sys.executable, '-I', '-S', '-B', str(bootstrap), json.dumps(identity),
               str(tmp_path), str(tmp_path), 'fixture_entry']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '1/2'


def test_bootstrap_does_not_import_modules_from_official_data_checkout(tmp_path):
    packages = tmp_path / 'packages'
    official = tmp_path / 'official'
    packages.mkdir(); official.mkdir()
    (official / 'fixture_dependency.py').write_text('raise RuntimeError("unverified official module")\n')
    (packages / 'fixture_dependency.py').write_text('value = "verified"\n')
    (packages / 'fixture_entry.py').write_text('import fixture_dependency; print(fixture_dependency.value)\n')
    identity = pilot._comparison_dependency_identity([packages])
    bootstrap = Path(pilot.__file__).with_name('comparison_bootstrap.py')
    command = [sys.executable, '-I', '-S', '-B', str(bootstrap), json.dumps(identity),
               str(tmp_path / 'source'), str(official), 'fixture_entry']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'verified'


def test_isolated_python_ignores_existing_source_bytecode(tmp_path):
    module = tmp_path / 'fixture_entry.py'
    module.write_text('print("malicious")\n')
    original = module.stat()
    py_compile.compile(str(module), doraise=True)
    module.write_text('print("safe-code")\n')
    os.utime(module, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert module.stat().st_size == original.st_size
    command = [sys.executable, '-I', '-S', '-B', '-X', f'pycache_prefix={tmp_path / "empty-cache"}',
               '-c', 'import sys; sys.path.append(sys.argv[1]); import fixture_entry', str(tmp_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'safe-code'


def test_comparison_source_rejects_ignored_standalone_bytecode(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'user.email', 'fixture@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'user.name', 'Fixture'], check=True)
    (tmp_path / '.gitignore').write_text('*.pyc\n')
    (tmp_path / 'm0').mkdir()
    (tmp_path / 'm0/source.py').write_text('value = 1\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'commit', '-qm', 'fixture'], check=True)
    (tmp_path / 'm0/shadow.pyc').write_bytes(b'ignored bytecode')
    with pytest.raises(ValueError, match='untracked importable'):
        pilot._comparison_source_state(tmp_path)


def test_comparison_source_rejects_tracked_python_symlink(tmp_path):
    repo, target = tmp_path / 'repo', tmp_path / 'target.py'
    repo.mkdir(); target.write_text('value = 1\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'fixture@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Fixture'], check=True)
    (repo / 'm0').mkdir()
    (repo / 'm0/linked.py').symlink_to(target)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'fixture'], check=True)
    with pytest.raises(ValueError, match='source symlink'):
        pilot._comparison_source_state(repo)


def test_formal_comparison_child_drops_loader_environment(tmp_path, monkeypatch):
    from zoo.mle_bench_lite.runner import _execute_agent
    monkeypatch.setenv('LD_LIBRARY_PATH', '/fixture/unsafe-library-path')
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-key')
    workspace, run_dir = tmp_path / 'workspace', tmp_path / 'run'
    workspace.mkdir(); run_dir.mkdir()
    code = "import os;print(os.getenv('LD_LIBRARY_PATH', 'absent'));print(os.getenv('OPENAI_API_KEY'))"
    result = _execute_agent(shlex.join([sys.executable, '-c', code]), workspace, 'fixture', 1,
                            'one_control', 10, run_dir, {'MLE_COMPARISON_ENV_ONLY': '1'})
    assert result['agent_returncode'] == 0
    assert (run_dir / 'stdout.log').read_text().splitlines() == ['absent', 'fixture-key']


def test_comparison_preflight_freezes_dependency_identity(tmp_path, monkeypatch):
    packages = tmp_path / 'packages'
    packages.mkdir()
    (packages / 'module.py').write_text('version = 1\n')
    monkeypatch.setattr(pilot, '_comparison_runtime_source', lambda: {'commit': 'a' * 40})
    monkeypatch.setattr(pilot, '_comparison_dependency_roots', lambda: [packages], raising=False)
    result = pilot.preflight_pilot(tmp_path / 'official', tmp_path / 'data', model='deepseek-flash',
        token_budget=5_000_000, iterations=3, runtime='m7', comparison='governance-intensity',
        spending_ledger_path=tmp_path / 'missing.db')
    assert result['plan']['comparison_dependencies'] == pilot._comparison_dependency_identity([packages])
    assert not any(item['requirement'] == 'comparison_runtime_attestation' for item in result['missing'])


def test_comparison_frozen_runtime_detects_changed_dependency(tmp_path, monkeypatch):
    packages = tmp_path / 'packages'
    packages.mkdir()
    (packages / 'module.py').write_text('original')
    monkeypatch.setattr(pilot, '_comparison_runtime_source', lambda: {'commit': 'a' * 40})
    monkeypatch.setattr(pilot, '_comparison_dependency_roots', lambda: [packages], raising=False)
    checker = getattr(pilot, '_comparison_frozen_runtime', None)
    assert callable(checker), 'comparison must recheck frozen source and dependencies'
    spec = {'source': {'commit': 'a' * 40},
            'comparison_dependencies': pilot._comparison_dependency_identity([packages])}
    assert checker(spec)
    (packages / 'module.py').write_text('changed')
    assert not checker(spec)


def test_isolated_bootstrap_loads_real_agent_help_without_network(tmp_path):
    root = Path(pilot.__file__).resolve().parents[3]
    identity = pilot._comparison_dependency_identity(pilot._comparison_dependency_roots())
    command = [sys.executable, '-I', '-S', '-B', str(Path(pilot.__file__).with_name('comparison_bootstrap.py')),
               json.dumps(identity), str(root / 'm0'), str(tmp_path),
               'zoo.mle_bench_lite.composed_agent', '--help']
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '--control-cycles' in result.stdout


def test_isolated_bootstrap_runs_governed_loopback_fixture(tmp_path):
    root = Path(pilot.__file__).resolve().parents[3]
    identity = pilot._comparison_dependency_identity(pilot._comparison_dependency_roots())
    test = root / 'm0/tests/test_mle_m7_agent.py'
    node = str(test) + '::test_m7_agent_materializes_frozen_predictions_and_accounts_controls[False-3-control_cycles5-full]'
    command = [sys.executable, '-I', '-S', '-B', '-X', f'pycache_prefix={tmp_path / "empty-cache"}',
               str(Path(pilot.__file__).with_name('comparison_bootstrap.py')), json.dumps(identity),
               str(root / 'm0'), str(tmp_path), 'pytest', '-q', '-p', 'no:cacheprovider',
               '--basetemp', str(tmp_path / 'fixture-data'), node]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120,
                            env={'PATH': os.defpath, 'HOME': str(tmp_path), 'OPENAI_API_KEY': 'fixture-only'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout
