"""Create and bind an offline disposable runtime; not a live launch gate."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tomllib
from urllib.parse import urlsplit

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.frozen_source import verify_frozen_source

_MAX_FILES = 100000
_MAX_BYTES = 1024 * 1024 * 1024


def _validate_install_inputs(project):
    """Reject local dependency sources before invoking the host installer."""
    with (project / 'uv.lock').open('rb') as stream:
        lock = tomllib.load(stream)
    with (project / 'pyproject.toml').open('rb') as stream:
        config = tomllib.load(stream)
    # uv may inspect project declarations while checking the lock. Permit only
    # ordinary index requirements and no workspace or custom source overrides.
    if 'uv' in config.get('tool', {}) or 'dynamic' in config.get('project', {}):
        raise ValueError('custom dependency sources are not allowed')
    requirements = list(config.get('project', {}).get('dependencies', []))
    for group in config.get('dependency-groups', {}).values():
        requirements.extend(group)
    for group in config.get('project', {}).get('optional-dependencies', {}).values():
        requirements.extend(group)
    if any(not isinstance(item, str) or '@' in item or '://' in item or 'file:' in item.lower()
           for item in requirements):
        raise ValueError('direct dependency sources are not allowed')
    packages = lock.get('package')
    if not isinstance(packages, list) or not packages:
        raise ValueError('dependency lock has no packages')
    for package in packages:
        source = package.get('source')
        if source not in ({'registry': 'https://pypi.org/simple'}, {'editable': '.'}, {'virtual': '.'}):
            raise ValueError('dependency lock has an unsupported source')
        artifacts = list(package.get('wheels', []))
        if 'sdist' in package:
            artifacts.append(package['sdist'])
        for artifact in artifacts:
            url = artifact.get('url', '')
            digest = artifact.get('hash', '')
            if (urlsplit(url).scheme != 'https' or urlsplit(url).hostname != 'files.pythonhosted.org'
                    or not isinstance(digest, str) or len(digest) != 71 or not digest.startswith('sha256:')
                    or any(ch not in '0123456789abcdef' for ch in digest[7:])):
                raise ValueError('dependency lock has an unsupported artifact')


def _file_sha256(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('runtime file must be a private regular file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or \
                (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('runtime file identity changed')
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('runtime file changed during verification')
    return digest.hexdigest(), before.st_size, stat.S_IMODE(before.st_mode)


def _runtime_manifest(runtime, base_python, lock_sha256):
    root = Path(runtime)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('runtime root must be a directory')
    root = root.resolve(strict=True)
    base = Path(base_python).resolve(strict=True)
    if not (base == Path('/usr') or Path('/usr') in base.parents) or not base.is_file():
        raise ValueError('runtime base Python must be a system executable')
    base_digest = hashlib.sha256(base.read_bytes()).hexdigest()
    entries, total = [], 0
    def onerror(error):
        raise error
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = path.resolve(strict=True)
                if target != base and target != root and root not in target.parents:
                    raise ValueError('runtime symlink escapes its isolated tree')
                entries.append({'path': relative, 'kind': 'symlink', 'target': os.readlink(path)})
                if name in dirs:
                    dirs.remove(name)
            elif stat.S_ISDIR(info.st_mode):
                entries.append({'path': relative, 'kind': 'dir', 'mode': stat.S_IMODE(info.st_mode)})
            elif stat.S_ISREG(info.st_mode):
                if info.st_size < 0 or total + info.st_size > _MAX_BYTES:
                    raise ValueError('runtime exceeds verification limits')
                digest, size, mode = _file_sha256(path)
                total += size
                entries.append({'path': relative, 'kind': 'file', 'sha256': digest, 'size': size, 'mode': mode})
            else:
                raise ValueError('runtime contains a non-regular file')
            if len(entries) > _MAX_FILES or total > _MAX_BYTES:
                raise ValueError('runtime exceeds verification limits')
    if not entries:
        raise ValueError('runtime is empty')
    return {'schema_version': 1, 'root': str(root), 'base_python': str(base),
            'base_python_sha256': base_digest, 'lock_sha256': lock_sha256,
            'entries': sorted(entries, key=lambda entry: entry['path'])}


def prepare_frozen_runtime(ledger, plan, *, snapshot, source_manifest, expected_plan_ref,
                           expected_campaign_id, destination, base_python, uv_cache):
    """Install locked wheels offline in a fresh private directory and anchor it."""
    source = verify_frozen_source(ledger, plan, snapshot=snapshot, manifest=source_manifest,
                                  expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id)
    if ledger.snapshot()['pending_calls']:
        raise ValueError('unresolved campaign call prevents runtime preparation')
    if ledger.circle_runtime_binding() is not None or any(
            ledger.cell_deadline_claim(f'{arm}-{seed}') is not None for arm in ('vendor', 'mori') for seed in range(3)):
        raise ValueError('runtime must be prepared once before any cell')
    requested = Path(destination)
    parent = requested.parent.resolve(strict=True)
    info = parent.stat()
    dest = parent / requested.name
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or \
            not requested.name or requested.name in ('.', '..') or dest.exists() or dest.is_symlink():
        raise ValueError('runtime destination must be fresh with a private parent')
    source_root = Path(snapshot).resolve(strict=True)
    ledger_path = ledger.path.resolve(strict=True)
    if dest == source_root or source_root in dest.parents or dest in source_root.parents or \
            dest == ledger_path or dest in ledger_path.parents:
        raise ValueError('runtime destination must be separate from source and campaign')
    base = Path(base_python).resolve(strict=True)
    if Path('/usr') not in base.parents or not base.is_file():
        raise ValueError('runtime requires a system Python')
    uv = shutil.which('uv')
    if uv is None:
        raise ValueError('offline runtime installation requires uv')
    cache = Path(uv_cache).resolve(strict=True)
    if not cache.is_dir() or cache == dest or dest in cache.parents or cache in dest.parents or \
            cache == source_root or source_root in cache.parents or cache in source_root.parents or \
            cache == ledger_path or cache in ledger_path.parents:
        raise ValueError('runtime cache must be separate from the destination')
    _validate_install_inputs(source_root / 'm0')
    env = {'PATH': os.defpath, 'HOME': str(parent), 'UV_CACHE_DIR': str(cache), 'UV_PYTHON': str(base),
           'UV_PROJECT_ENVIRONMENT': str(dest), 'UV_OFFLINE': '1', 'UV_NO_CONFIG': '1',
           'UV_LINK_MODE': 'copy', 'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        version = subprocess.check_output([str(base), '-I', '-S', '-c',
            "import sys; print('%d.%d' % sys.version_info[:2])"], env=env, timeout=30).decode('ascii').strip()
        if version != '3.12':
            raise ValueError('runtime requires Python 3.12')
        subprocess.run([uv, 'sync', '--project', str(Path(snapshot) / 'm0'), '--locked', '--offline',
            '--no-build', '--no-dev', '--no-install-project', '--link-mode', 'copy'], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=True)
        verify_frozen_source(ledger, plan, snapshot=snapshot, manifest=source_manifest,
                             expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id)
        manifest = _runtime_manifest(dest, base, plan['dependency_lock_sha256'])
        runtime_ref = 'sha256:' + payload_digest(manifest)
        ledger.freeze_circle_runtime(expected_plan_ref, source['tree_ref'], runtime_ref,
                                     manifest['base_python_sha256'])
        return {'runtime_ref': runtime_ref, 'manifest': manifest}
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError('offline locked runtime installation failed') from error


def verify_frozen_runtime(ledger, *, runtime, manifest, base_python):
    """Verify only the already-anchored disposable runtime, without installing."""
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    if type(ledger) is not CampaignBudget or type(manifest) is not dict:
        raise ValueError('runtime requires its original campaign and manifest')
    binding = ledger.circle_runtime_binding()
    reference = 'sha256:' + payload_digest(manifest)
    if binding is None or binding['runtime_ref'] != reference or \
            binding['python_sha256'] != manifest.get('base_python_sha256') or \
            str(Path(runtime).resolve()) != manifest.get('root') or \
            str(Path(base_python).resolve()) != manifest.get('base_python'):
        raise ValueError('runtime differs from the campaign binding')
    actual = _runtime_manifest(runtime, base_python, manifest.get('lock_sha256'))
    if actual != manifest:
        raise ValueError('runtime content differs from the frozen manifest')
    return {'runtime_ref': reference}
