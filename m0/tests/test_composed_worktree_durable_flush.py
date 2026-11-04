"""A visible terminal result can precede the supervisor's final directory sync."""
from __future__ import annotations

import subprocess
import sys

import pytest

from test_composed_worktree_executor import components, execute, inputs, setup


@pytest.mark.skipif(sys.platform != 'linux', reason='fault injection uses Linux descriptor paths')
def test_completed_evaluation_waits_for_slow_supervisor_durable_flush(tmp_path, monkeypatch):
    """A delayed final fsync must not discard already measured evaluation cost."""
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    original_popen = subprocess.Popen
    supervisors = []
    bootstrap = '''import os, pathlib, runpy, stat, sys, time
original_fsync = os.fsync
def delayed_final_flush(fd):
    original_fsync(fd)
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        directory = pathlib.Path(os.readlink('/proc/self/fd/' + str(fd)))
        if (directory / 'process-result.json').exists():
            time.sleep(5.25)
            (directory / 'flush-finished').write_text('finished')
os.fsync = delayed_final_flush
path = sys.argv[1]
sys.argv = [path] + sys.argv[2:]
runpy.run_path(path, run_name='__main__')
'''

    def delayed_supervisor(args, *positional, **kwargs):
        if isinstance(args, list) and len(args) == 6 and str(args[4]) == str(executor.worker):
            args = [*args[:3], bootstrap, *args[4:]]
            child = original_popen(args, *positional, **kwargs)
            supervisors.append(child)
            return child
        return original_popen(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', delayed_supervisor)
    try:
        evidence = execute(executor, domain)
        directory = executor.operation_path(inputs()[2])
        assert (directory / 'flush-finished').read_text() == 'finished'
        assert evidence.eval_result.metrics == {'quality': 0.75}
        assert evidence.eval_result.cost.tokens_in == 7
        assert len(list(store.read('worktree_evidence'))) == 1
        assert len(supervisors) == 1 and supervisors[0].returncode == 0
        assert execute(executor, domain) == evidence
        assert len(list(store.read('worktree_process_started'))) == 1
        assert len(supervisors) == 1
    finally:
        for child in supervisors:
            child.wait(timeout=15)
