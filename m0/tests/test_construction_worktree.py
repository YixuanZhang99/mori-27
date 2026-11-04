"""Real Git publication retains one exact artifact across process interruption."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from core.composition.git_artifacts import GitArtifactBackend
from core.x1.store import AppendOnlyStore
from test_materialization_recovery import OP


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


def base(path):
    path.mkdir()
    git(path, 'init', '--quiet')
    git(path, 'config', 'user.name', 'Fixture')
    git(path, 'config', 'user.email', 'fixture@example.invalid')
    (path / 'evaluator.txt').write_text('trusted evaluator\n')
    (path / 'candidate.txt').write_text('old candidate\n')
    git(path, 'add', '.')
    git(path, 'commit', '--quiet', '-m', 'base')
    return path


def backend(tmp_path, **options):
    return GitArtifactBackend(tmp_path / 'artifacts', AppendOnlyStore(tmp_path / 'events.jsonl'), **options)


def test_git_publication_freezes_one_commit_and_preserves_base(tmp_path):
    repo = base(tmp_path / 'repo')
    original = git(repo, 'rev-parse', 'HEAD')
    owner = backend(tmp_path, base_repo=repo, protected_paths=['evaluator.txt'])
    result = owner.publish('new candidate\n', operation=OP)
    assert owner.load(result) == 'new candidate\n'
    assert git(repo, 'show', result['commit'] + ':candidate.txt') == 'new candidate'
    assert git(repo, 'show', result['commit'] + ':evaluator.txt') == 'trusted evaluator'
    assert git(repo, 'rev-parse', 'HEAD') == original
    assert (repo / 'candidate.txt').read_text() == 'old candidate\n'
    before = (tmp_path / 'events.jsonl').read_bytes()
    assert owner.publish('new candidate\n', operation=OP) == result
    assert (tmp_path / 'events.jsonl').read_bytes() == before
    assert result['reference'] == 'sha256:' + hashlib.sha256(b'new candidate\n').hexdigest()
    assert len(git(repo, 'rev-list', result['commit']).splitlines()) == 2


def test_managed_repository_does_not_snapshot_caller_files(tmp_path):
    (tmp_path / 'private.txt').write_text('PRIVATE')
    owner = backend(tmp_path)
    result = owner.publish('candidate', operation=OP)
    assert git(owner.repo, 'ls-tree', '-r', '--name-only', result['commit']) == 'candidate.txt'
    restored = backend(tmp_path)
    assert restored.manifest_binding == owner.manifest_binding
    assert restored.load(result) == 'candidate'


@pytest.mark.parametrize('path', ['../outside.txt', '.git/config', 'evaluator.txt', 'evaluator.txt/child', './evaluator.txt'])
def test_unsafe_or_protected_artifact_path_is_rejected(tmp_path, path):
    repo = base(tmp_path / 'repo')
    with pytest.raises(ValueError):
        backend(tmp_path, base_repo=repo, artifact_path=path, protected_paths=['evaluator.txt'])


def test_symlink_in_frozen_base_is_rejected(tmp_path):
    repo = base(tmp_path / 'repo')
    (repo / 'escape').symlink_to(tmp_path)
    git(repo, 'add', 'escape')
    git(repo, 'commit', '--quiet', '-m', 'symlink')
    with pytest.raises(ValueError, match='symlink|unsupported'):
        backend(tmp_path, base_repo=repo)


def test_changed_publication_identity_or_descriptor_is_rejected(tmp_path):
    owner = backend(tmp_path)
    result = owner.publish('first', operation=OP)
    with pytest.raises(ValueError):
        owner.publish('second', operation=OP)
    for change in ({'commit': owner.base_commit}, {'reference': 'sha256:' + 'a' * 64},
                   {'size_bytes': 1}, {'artifact_path': 'other.txt'}):
        with pytest.raises(ValueError):
            owner.load({**result, **change})
    plan = next((tmp_path / 'artifacts' / 'operations').glob('*/plan.json'))
    value = json.loads(plan.read_text())
    value['operation']['lane'] = 'control'
    plan.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        owner.load(result)


def test_publication_bypasses_git_hooks_and_filters(tmp_path):
    repo = base(tmp_path / 'repo')
    marker = tmp_path / 'executed.txt'
    hook = repo / '.git' / 'hooks' / 'post-checkout'
    hook.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n')
    hook.chmod(0o755)
    (repo / '.gitattributes').write_text('candidate.txt filter=hostile\n')
    git(repo, 'add', '.gitattributes')
    git(repo, 'commit', '--quiet', '-m', 'attributes')
    git(repo, 'config', 'filter.hostile.clean', 'touch ' + str(marker))
    git(repo, 'config', 'filter.hostile.smudge', 'touch ' + str(marker))
    owner = backend(tmp_path, base_repo=repo)
    result = owner.publish('exact bytes\n', operation=OP)
    assert owner.load(result) == 'exact bytes\n'
    assert not marker.exists()


@pytest.mark.parametrize('cut', ['worktree_artifact_plan', 'worktree_artifact_commit'])
def test_sigkill_adopts_original_commit_plan_without_duplicate_commit(tmp_path, cut):
    script = '''import json,os,signal,sys
from pathlib import Path
from core.composition.git_artifacts import GitArtifactBackend
from core.x1.store import AppendOnlyStore
class CutStore(AppendOnlyStore):
 def append(self,kind,value):
  super().append(kind,value)
  with self.path.open('rb') as f: os.fsync(f.fileno())
  if kind==sys.argv[2]: os.kill(os.getpid(),signal.SIGKILL)
root=Path(sys.argv[1])
owner=GitArtifactBackend(root/'artifacts',CutStore(root/'events.jsonl'))
owner.publish('one artifact',operation=json.loads(sys.argv[3]))
'''
    completed = subprocess.run([sys.executable, '-c', script, str(tmp_path), cut, json.dumps(OP)],
                               env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
    assert completed.returncode == -signal.SIGKILL
    plan = json.loads(next((tmp_path / 'artifacts' / 'operations').glob('*/plan.json')).read_text())
    owner = backend(tmp_path)
    result = owner.publish('one artifact', operation=OP)
    assert result['commit'] == plan['descriptor']['commit']
    assert owner.load(result) == 'one artifact'
    assert len(git(owner.repo, 'rev-list', result['commit']).splitlines()) == 2
    rows = list(owner.store.read())
    assert sum(r['kind'] == 'worktree_artifact_plan' for r in rows) == 1
    assert sum(r['kind'] == 'worktree_artifact_commit' for r in rows) == 1


def test_artifact_load_requires_original_publication_journal(tmp_path):
    owner = backend(tmp_path)
    result = owner.publish('original', operation=OP)
    foreign = GitArtifactBackend(tmp_path / 'artifacts', AppendOnlyStore(tmp_path / 'foreign.jsonl'))
    with pytest.raises(ValueError, match='journal'):
        foreign.load(result)


def test_publication_workspace_must_be_outside_supplied_base_repo(tmp_path):
    repo = base(tmp_path / 'repo')
    with pytest.raises(ValueError, match='outside'):
        GitArtifactBackend(repo / 'generated', AppendOnlyStore(tmp_path / 'events.jsonl'), base_repo=repo)


def test_artifact_cannot_replace_base_directory(tmp_path):
    repo = base(tmp_path / 'repo')
    (repo / 'package').mkdir()
    (repo / 'package' / 'base.py').write_text('trusted')
    git(repo, 'add', '.')
    git(repo, 'commit', '--quiet', '-m', 'base directory')
    with pytest.raises(ValueError, match='directory'):
        backend(tmp_path, base_repo=repo, artifact_path='package')
