"""Verify that hash randomization was fixed before this interpreter started."""
import json
import os
import subprocess
import sys

_PROBES = ('mori-openevolve-hash-seed-v1', 'circle-packing-checkpoint-order-v1')


def require_hash_seed_zero():
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('OpenEvolve requires PYTHONHASHSEED=0 before process start')
    code = 'import json; print(json.dumps([hash(x) for x in ' + repr(_PROBES) + ']))'
    try:
        reference = subprocess.run([sys.executable, '-B', '-c', code], check=True, capture_output=True,
            text=True, timeout=10, env={'PYTHONHASHSEED': '0', 'PATH': os.defpath})
        expected = json.loads(reference.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError('could not verify the process hash seed') from error
    if expected != [hash(item) for item in _PROBES]:
        raise ValueError('process hash seed differs from PYTHONHASHSEED=0 at startup')


_RUNTIME_PATHS = ('m0/core', 'm0/zoo', 'm0/config', 'm0/vendor/openevolve/openevolve',
                  'm0/vendor/openevolve/examples/circle_packing', 'm0/pyproject.toml', 'm0/uv.lock')


def fixture_source_identity(root=None):
    """Bind the commit and local runtime-source edits, never unrelated private files."""
    import hashlib
    from pathlib import Path
    root = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    try:
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)
        commit = git('rev-parse', 'HEAD').decode().strip()
        dirty = bool(git('status', '--porcelain', '-z'))
        diff = git('diff', '--binary', 'HEAD', '--', *_RUNTIME_PATHS)
        untracked = git('ls-files', '--others', '--exclude-standard', '-z', '--', *_RUNTIME_PATHS)
        digest = hashlib.sha256()
        digest.update(len(diff).to_bytes(8, 'big'))
        digest.update(diff)
        for raw in sorted(item for item in untracked.split(b'\0') if item):
            relative = os.fsdecode(raw)
            path = root / relative
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('untracked runtime source must be a bounded regular file')
            data = path.read_bytes()
            digest.update(len(raw).to_bytes(8, 'big'))
            digest.update(raw)
            digest.update(len(data).to_bytes(8, 'big'))
            digest.update(data)
        return {'commit': commit, 'dirty': dirty, 'worktree_sha256': digest.hexdigest()}
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError('fixture requires a readable source checkout') from error
