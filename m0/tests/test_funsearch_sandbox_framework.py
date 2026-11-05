"""Offline FunSearch through the real M7 sandbox and recorded replay."""
import shutil

import pytest

from test_composed_worktree_framework import prepare, profile
from test_composed_worktree_executor import PROGRAM, git
from test_configured_construction import build
from test_funsearch_framework import CodeProvider, TASK, assembly


def test_funsearch_rejects_unsandboxed_command_before_provider_call(tmp_path):
    prepare(tmp_path)
    configured = assembly()
    command = profile(tmp_path, layered=False)
    configured['domain'] = command['domain']
    configured['executor'] = command['executor']
    configured['executor']['name'] = 'git_artifact'
    configured['executor']['options'].pop('run_root')
    provider = CodeProvider()
    with pytest.raises(ValueError, match='bounded M7'):
        build(tmp_path / 'run', assembly=configured, provider=provider, generations=0)
    assert provider.calls == 0


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_funsearch_uses_sandboxed_worktree_and_replays_without_workers(tmp_path, monkeypatch):
    import subprocess
    prepare(tmp_path)
    (tmp_path / 'host-secret.txt').write_text('unavailable to the candidate')
    program = PROGRAM.replace("value=runpy.run_path(str(root/request['artifact_path']))['VALUE']",
                              "value=runpy.run_path(str(root/request['artifact_path']))['priority'](0)")
    program = program.replace("'quality':value", "'dev/score':float(value)")
    program = program.replace("'items':None", "'items':[{'item_id':name,'verdict':None,"
        "'metrics':{'score':float(value)},'seed':None,'visibility':'public'} for name in ('a','b')]")
    (tmp_path / 'repo/evaluate.py').write_text(program)
    git(tmp_path / 'repo', 'add', 'evaluate.py')
    git(tmp_path / 'repo', 'commit', '--quiet', '-m', 'public numeric fixture')
    configuration = assembly()
    command = profile(tmp_path, mode='sandbox', layered=False)
    configuration['domain'] = command['domain']
    configuration['executor'] = command['executor']
    configuration['executor']['name'] = 'git_artifact'
    configuration['executor']['options'].pop('run_root')
    configuration['executor']['options']['sandbox'] = 'bubblewrap'
    provider = CodeProvider()
    fw = build(tmp_path / 'run', assembly=configuration, provider=provider, generations=1)
    fw.evolve(TASK)
    assert len(list(fw.store.read('funsearch_public_candidate'))) == 2
    assert len(list(fw.store.read('funsearch_selection'))) == 1
    calls = provider.calls
    original_popen = subprocess.Popen
    def no_worker(args, *rest, **kwargs):
        if isinstance(args, (list, tuple)) and any(str(part).endswith('/command_worker.py') for part in args):
            raise AssertionError('replay started a command worker')
        return original_popen(args, *rest, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', no_worker)
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert provider.calls == calls == 2
