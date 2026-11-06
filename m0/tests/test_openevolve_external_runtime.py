"""Sandboxed Python can use an isolated virtual environment outside /usr."""
from pathlib import Path
import subprocess
import sys

import pytest

from zoo.mle_bench_lite.composed_domain import SandboxRunner


pytestmark = pytest.mark.linux


def test_sandbox_runner_reads_external_virtualenv(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(runtime)], check=True)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'data').mkdir()
    (workspace / 'program.py').write_text("print('external-runtime-ok')\n")
    monkeypatch.setattr('zoo.mle_bench_lite.composed_domain._PROCESS_RUNTIME_ROOT', runtime)
    monkeypatch.setattr(sys, 'executable', str(runtime / 'bin' / 'python'))
    runner = SandboxRunner()
    result = runner.execute(workspace, timeout=15)
    assert result['returncode'] == 0
    assert (workspace / 'stdout.log').read_text().strip() == 'external-runtime-ok'


def test_private_artifacts_must_not_be_inside_visible_runtime(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    monkeypatch.setattr('zoo.mle_bench_lite.composed_domain._PROCESS_RUNTIME_ROOT', runtime)
    runner = SandboxRunner()
    with pytest.raises(ValueError, match='visible'):
        runner.validate_paths(runtime / 'private-data')
    with pytest.raises(ValueError, match='visible'):
        runner.validate_paths(tmp_path)


def test_cell_worker_reads_external_virtualenv(tmp_path):
    from test_openevolve_cell_worker import setup
    from zoo.circle_packing.cell_worker import run_cell_worker
    runtime = tmp_path / 'runtime'
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(runtime)], check=True)
    deadline, workspace = setup(tmp_path, 30)
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
                             [str(runtime / 'bin' / 'python'), '-c', "print('runtime-ok')"],
                             readonly_runtime=runtime)
    assert result['state'] == 'completed'
