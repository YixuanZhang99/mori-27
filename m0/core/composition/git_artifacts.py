"""Immutable Git artifacts with deterministic, recoverable publication plans.

Only exact Git blobs are materialized. User hooks, filters and the caller's
working tree/index are never used to construct a publication commit.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from core.composition.contracts import json_copy
from core.executor.workspace import safe_relative


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _sha(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _read(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('publication record is not a regular file')
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('publication record is unavailable or invalid') from error


def _atomic(path, value):
    if path.exists() or path.is_symlink():
        if _read(path) != value:
            raise ValueError('immutable publication record changed')
        return
    fd, name = tempfile.mkstemp(prefix='.publication-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_canonical(value)); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(name, path, follow_symlinks=False)
        except FileExistsError:
            if _read(path) != value:
                raise ValueError('concurrent publication record differs')
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _lease(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('another coordinator owns artifact publication') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _git(repo, *args, data=None, index=None, allow_missing=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS='1')
    if index is not None:
        env['GIT_INDEX_FILE'] = str(index)
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               '-c', 'core.attributesFile=/dev/null', *args]
    result = subprocess.run(command, cwd=repo, env=env, input=data, capture_output=True)
    if result.returncode:
        if allow_missing and result.returncode == 1:
            return None
        raise ValueError('Git artifact operation failed: ' + result.stderr.decode(errors='replace')[-1000:])
    return result.stdout


def _text(repo, *args, **kwargs):
    value = _git(repo, *args, **kwargs)
    return None if value is None else value.decode('utf-8').strip()


class GitArtifactBackend:
    def __init__(self, root, store, *, base_repo=None, base_ref='HEAD',
                 artifact_path='candidate.txt', protected_paths=()):
        root = Path(root)
        if root.is_symlink():
            raise ValueError('artifact root cannot be a symlink')
        root.mkdir(parents=True, exist_ok=True)
        self.root, self.store = root.resolve(), store
        if type(base_ref) is not str or not base_ref or base_ref.startswith('-'):
            raise ValueError('base_ref must identify a Git commit')
        if type(artifact_path) is not str or type(protected_paths) not in (tuple, list) \
                or any(type(p) is not str for p in protected_paths):
            raise ValueError('artifact and protected paths must be relative names')
        safe_relative(self.root, artifact_path)
        if Path(artifact_path).as_posix() != artifact_path:
            raise ValueError('artifact path must be canonical')
        if artifact_path.split('/')[0] == '.autoresearch-command':
            raise ValueError('artifact overlaps executor control path')
        self.artifact_path = artifact_path
        self.protected_paths = tuple(protected_paths)
        for path in self.protected_paths:
            safe_relative(self.root, path)
            if Path(path).as_posix() != path:
                raise ValueError('protected paths must be canonical')
            if artifact_path == path or artifact_path.startswith(path + '/') or path.startswith(artifact_path + '/'):
                raise ValueError('artifact overlaps protected path')
        self.repo = Path(base_repo).resolve() if base_repo is not None else self.root / 'repository'
        if base_repo is not None and (self.root == self.repo or self.repo in self.root.parents):
            raise ValueError('publication workspace must be outside base_repo')
        if base_repo is None:
            self._managed_repository()
            base_ref = 'refs/mori/base'
        elif not (self.repo / '.git').exists():
            raise ValueError('base_repo must be an existing Git repository')
        self.base_commit = _text(self.repo, 'rev-parse', '--verify', base_ref + '^{commit}')
        self.entries = self._entries(self.base_commit)
        if any(name.startswith(artifact_path + '/') or artifact_path.startswith(name + '/') for name in self.entries):
            raise ValueError('artifact path conflicts with a base file or directory')
        self.protected = self._protected(self.entries)
        for name in ('operations', 'worktrees'):
            safe_relative(self.root, name).mkdir(exist_ok=True)

    def _managed_repository(self):
        safe_relative(self.root, 'repository').mkdir(exist_ok=True)
        with _lease(self.root / 'repository.lock'):
            if not (self.repo / '.git').exists():
                if any(self.repo.iterdir()):
                    raise ValueError('managed repository directory must be empty')
                _git(self.repo, 'init', '--quiet')
            tree = _text(self.repo, 'hash-object', '-t', 'tree', '--stdin', data=b'')
            body = self._commit_body(tree, None, 'managed empty artifact base')
            commit = _text(self.repo, 'hash-object', '-t', 'commit', '--stdin', data=body)
            current = _text(self.repo, 'rev-parse', '--verify', '--quiet', 'refs/mori/base', allow_missing=True)
            if current is None:
                _git(self.repo, 'hash-object', '-w', '-t', 'tree', '--stdin', data=b'')
                _git(self.repo, 'hash-object', '-w', '-t', 'commit', '--stdin', data=body)
                _git(self.repo, 'update-ref', 'refs/mori/base', commit, '0' * len(commit))
            elif current != commit:
                raise ValueError('managed artifact base changed')

    @staticmethod
    def _commit_body(tree, parent, message):
        lines = ['tree ' + tree]
        if parent is not None:
            lines.append('parent ' + parent)
        lines += ['author Mori Artifact <artifact@local.invalid> 0 +0000',
                  'committer Mori Artifact <artifact@local.invalid> 0 +0000', '', message, '']
        return '\n'.join(lines).encode('utf-8')

    def _entries(self, commit):
        entries = {}
        for item in _git(self.repo, 'ls-tree', '-r', '-z', commit).split(b'\0'):
            if not item:
                continue
            header, name = item.split(b'\t', 1)
            mode, kind, oid = header.decode('ascii').split()
            name = name.decode('utf-8')
            if kind != 'blob' or mode not in {'100644', '100755'}:
                raise ValueError('artifact base has unsupported symlink, submodule or special entry')
            safe_relative(self.repo, name)
            entries[name] = (mode, oid)
        return entries

    def _protected(self, entries):
        result = {}
        for path in self.protected_paths:
            selected = {name: item for name, item in entries.items()
                        if name == path or name.startswith(path + '/')}
            if not selected:
                raise ValueError('protected path is missing from frozen base')
            for name, (mode, oid) in selected.items():
                result[name] = {'mode': mode, 'sha256': _sha(_git(self.repo, 'cat-file', 'blob', oid))}
        return result

    @property
    def manifest_binding(self):
        return {'schema_version': 1, 'kind': 'git_text_v1', 'base_repo': str(self.repo),
                'base_commit': self.base_commit, 'artifact_path': self.artifact_path,
                'protected_paths': list(self.protected_paths), 'protected': json_copy(self.protected)}

    @staticmethod
    def _descriptor(value):
        value = json_copy(value, label='Git artifact descriptor')
        if type(value) is not dict or set(value) != {'schema_version', 'kind', 'reference', 'size_bytes',
                'commit', 'tree', 'artifact_path', 'publication_key'} or type(value['schema_version']) is not int \
                or value['schema_version'] != 1 or value['kind'] != 'git_text_v1' \
                or type(value['size_bytes']) is not int or value['size_bytes'] < 1:
            raise ValueError('invalid immutable Git artifact descriptor')
        for key, pattern in [('reference', r'sha256:[0-9a-f]{64}'), ('commit', r'[0-9a-f]{40}|[0-9a-f]{64}'),
                             ('tree', r'[0-9a-f]{40}|[0-9a-f]{64}'), ('publication_key', r'[0-9a-f]{64}')]:
            if type(value[key]) is not str or re.fullmatch(pattern, value[key]) is None:
                raise ValueError('invalid Git artifact identity')
        if type(value['artifact_path']) is not str:
            raise ValueError('invalid Git artifact path')
        return value

    def _event_once(self, kind, plan, *, required=False):
        payload = {'publication_key': plan['descriptor']['publication_key'],
                   'plan_sha256': _sha(_canonical(plan)), 'commit': plan['descriptor']['commit']}
        rows = [row['payload'] for row in self.store.read(kind)
                if row['payload'].get('publication_key') == payload['publication_key']]
        if rows:
            if rows != [payload]:
                raise ValueError('Git publication journal identity changed')
        elif required:
            raise ValueError('Git artifact has no original publication journal evidence')
        else:
            self.store.append(kind, payload)

    def _validate_plan(self, plan, descriptor):
        if type(plan) is not dict or set(plan) != {'schema_version', 'operation', 'backend', 'descriptor', 'commit_body'} \
                or type(plan['schema_version']) is not int or plan['schema_version'] != 1 \
                or plan['backend'] != self.manifest_binding or plan['descriptor'] != descriptor:
            raise ValueError('Git publication plan binding changed')
        operation = plan['operation']
        if type(operation) is not dict or type(operation.get('intent_id')) is not str \
                or hashlib.sha256(operation['intent_id'].encode()).hexdigest() != descriptor['publication_key']:
            raise ValueError('Git publication operation identity changed')
        expected_body = self._commit_body(descriptor['tree'], self.base_commit,
                                          'mori artifact ' + _sha(_canonical(operation))).decode()
        if plan['commit_body'] != expected_body or _text(self.repo, 'hash-object', '-t', 'commit', '--stdin',
                data=expected_body.encode()) != descriptor['commit']:
            raise ValueError('Git commit differs from original publication plan')

    def load(self, descriptor):
        descriptor = self._descriptor(descriptor)
        if descriptor['artifact_path'] != self.artifact_path:
            raise ValueError('Git artifact path changed')
        directory = safe_relative(self.root, 'operations/' + descriptor['publication_key'])
        plan = _read(directory / 'plan.json')
        self._validate_plan(plan, descriptor)
        for kind in ('worktree_artifact_plan', 'worktree_artifact_commit'):
            self._event_once(kind, plan, required=True)
        if _read(directory / 'published.json') != descriptor:
            raise ValueError('Git artifact publication is incomplete')
        if _git(self.repo, 'cat-file', 'commit', descriptor['commit']) != plan['commit_body'].encode():
            raise ValueError('Git commit content changed')
        if _text(self.repo, 'show-ref', '--verify', '--hash', 'refs/mori/artifacts/' + descriptor['publication_key']) != descriptor['commit']:
            raise ValueError('Git artifact publication ref changed')
        entries = self._entries(descriptor['commit'])
        expected = {name: entry for name, entry in self.entries.items() if name != self.artifact_path}
        if {name: entry for name, entry in entries.items() if name != self.artifact_path} != expected \
                or self._protected(entries) != self.protected or self.artifact_path not in entries:
            raise ValueError('Git artifact changed the protected base')
        mode, blob = entries[self.artifact_path]
        if mode != '100644':
            raise ValueError('Git artifact mode changed')
        raw = _git(self.repo, 'cat-file', 'blob', blob)
        if len(raw) != descriptor['size_bytes'] or _sha(raw) != descriptor['reference']:
            raise ValueError('Git artifact content changed')
        return raw.decode('utf-8')

    def publish(self, artifact, *, operation):
        operation = json_copy(operation, label='Git publication operation')
        if type(operation) is not dict or type(operation.get('intent_id')) is not str or not operation['intent_id'] \
                or operation.get('phase') != 'operator' or type(artifact) is not str or not artifact.strip():
            raise ValueError('Git publication requires nonempty construction and operation identity')
        key = hashlib.sha256(operation['intent_id'].encode()).hexdigest()
        directory = safe_relative(self.root, 'operations/' + key)
        directory.mkdir(exist_ok=True)
        raw = artifact.encode('utf-8')
        with _lease(directory / 'coordinator.lock'):
            if (directory / 'plan.json').exists():
                plan = _read(directory / 'plan.json')
                descriptor = self._descriptor(plan['descriptor'])
                self._validate_plan(plan, descriptor)
                if plan['operation'] != operation or descriptor['reference'] != _sha(raw) \
                        or descriptor['size_bytes'] != len(raw):
                    raise ValueError('Git publication input changed')
            else:
                plan = self._prepare(directory, key, artifact, operation)
                descriptor = plan['descriptor']
                _atomic(directory / 'plan.json', plan)
            self._event_once('worktree_artifact_plan', plan)
            commit = _text(self.repo, 'hash-object', '-w', '-t', 'commit', '--stdin', data=plan['commit_body'].encode())
            if commit != descriptor['commit']:
                raise ValueError('published commit differs from its frozen plan')
            ref = 'refs/mori/artifacts/' + key
            current = _text(self.repo, 'rev-parse', '--verify', '--quiet', ref, allow_missing=True)
            if current is None:
                _git(self.repo, 'update-ref', ref, commit, '0' * len(commit))
            elif current != commit:
                raise ValueError('Git publication ref changed')
            self._event_once('worktree_artifact_commit', plan)
            _atomic(directory / 'published.json', descriptor)
            if self.load(descriptor) != artifact:
                raise ValueError('Git publication differs from construction')
            return descriptor

    def _prepare(self, directory, key, artifact, operation):
        root = safe_relative(self.root, 'worktrees/' + key)
        if not root.exists():
            _git(self.repo, 'worktree', 'add', '--quiet', '--detach', '--no-checkout', str(root), self.base_commit)
        if _text(root, 'rev-parse', '--path-format=absolute', '--git-common-dir') != _text(
                self.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir') \
                or _text(root, 'rev-parse', 'HEAD') != self.base_commit:
            raise ValueError('artifact worktree identity changed')
        for name, (mode, blob) in self.entries.items():
            target = safe_relative(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git(self.repo, 'cat-file', 'blob', blob))
            target.chmod(0o755 if mode == '100755' else 0o644)
        target = safe_relative(root, self.artifact_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.encode('utf-8')); target.chmod(0o644)
        index = directory / 'index'
        if index.is_symlink():
            raise ValueError('artifact index cannot be a symlink')
        _git(self.repo, 'read-tree', self.base_commit, index=index)
        blob = _text(self.repo, 'hash-object', '-w', '--stdin', data=target.read_bytes())
        _git(self.repo, 'update-index', '--add', '--cacheinfo', '100644', blob, self.artifact_path, index=index)
        tree = _text(self.repo, 'write-tree', index=index)
        body = self._commit_body(tree, self.base_commit, 'mori artifact ' + _sha(_canonical(operation)))
        commit = _text(self.repo, 'hash-object', '-t', 'commit', '--stdin', data=body)
        descriptor = {'schema_version': 1, 'kind': 'git_text_v1', 'reference': _sha(artifact.encode()),
                      'size_bytes': len(artifact.encode()), 'commit': commit, 'tree': tree,
                      'artifact_path': self.artifact_path, 'publication_key': key}
        return {'schema_version': 1, 'operation': operation, 'backend': self.manifest_binding,
                'descriptor': descriptor, 'commit_body': body.decode()}
