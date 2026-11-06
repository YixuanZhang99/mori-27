"""Sandboxed Python can use an isolated virtual environment outside /usr."""
from pathlib import Path
import os
import subprocess
import sys
import time

import pytest

from zoo.mle_bench_lite.composed_domain import SandboxRunner


pytestmark = pytest.mark.linux


def test_sanitized_child_path_preserves_selected_bubblewrap(tmp_path, monkeypatch):
    import shutil
    from core.executor.sandbox import sandbox_child_path
    approved = tmp_path / 'approved'
    approved.mkdir()
    executable = approved / 'bwrap'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(approved) + os.pathsep + os.defpath)
    assert shutil.which('bwrap') == str(executable)
    child = subprocess.run([sys.executable, '-c', 'import shutil; print(shutil.which("bwrap"))'],
                           env={'PATH': sandbox_child_path()}, capture_output=True, text=True, check=True)
    assert child.stdout.strip() == str(executable)


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


@pytest.mark.parametrize('parent_death_guard', [True, False])
def test_coordinator_deadline_stops_its_active_candidate_sandbox(tmp_path, parent_death_guard):
    """A killed coordinator must not leave its detached evaluator running."""
    from core.composition.recovery import ContinuationStore
    from core.executor.process import ProcessJournal
    from core.executor.sandbox import sandbox_child_path
    from test_openevolve_cell_worker import setup

    deadline, workspace = setup(tmp_path, 5)
    (workspace / 'data').mkdir()
    (workspace / 'program.py').write_text(
        "import time\nopen('ready', 'w').write('ready')\n"
        "time.sleep(8)\nopen('late', 'w').write('escaped')\n"
    )
    script = ("import sys\nfrom pathlib import Path\n"
              "from core.executor.sandbox import BubblewrapSandbox\n"
              "from zoo.mle_bench_lite.composed_domain import SandboxRunner\n"
              "if sys.argv[2] == 'no-parent-guard':\n"
              "    old = BubblewrapSandbox.wrap\n"
              "    def wrap(self, *args, **kwargs):\n"
              "        command = old(self, *args, **kwargs)\n"
              "        command.remove('--die-with-parent')\n"
              "        return command\n"
              "    BubblewrapSandbox.wrap = wrap\n"
              "SandboxRunner().execute(Path(sys.argv[1]), timeout=20)\n")
    source = Path(__file__).resolve().parents[1]
    journal = ProcessJournal(ContinuationStore(tmp_path / 'coordinator.jsonl'))
    record = deadline._record
    process, execution = journal.launch(
        [sys.executable, '-c', script, str(workspace),
         'parent-guard' if parent_death_guard else 'no-parent-guard'], tmp_path,
        {'PATH': sandbox_child_path(), 'PYTHONPATH': str(source)}, None,
        {'candidate_id': 'fixture-coordinator', 'attempt': 1},
        absolute_deadline={'boot_id': record['boot_id'],
                           'deadline_ns': record['start_ns'] + record['seconds'] * 1_000_000_000})
    result = journal.wait(process, execution)
    sandbox_stderr = workspace / 'stderr.log'
    assert (workspace / 'ready').exists(), {
        'coordinator': result,
        'sandbox_stderr': sandbox_stderr.read_text(errors='replace')[-4000:] if sandbox_stderr.exists() else None,
    }
    assert result['timeout'], result
    # Allow the full candidate delay after the ready marker was observed,
    # including when startup consumed most of the coordinator deadline.
    time.sleep(8.5)
    assert (workspace / 'late').exists() is not parent_death_guard
