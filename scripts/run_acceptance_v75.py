#!/usr/bin/env python3
"""V75 acceptance with original and execution-copy source bound to a Git commit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import run_acceptance as runner

VERIFIER_VERSION = "v75"
runner.VERIFIER_VERSION = VERIFIER_VERSION
runner.HISTORY = ("verifier/v75/LAST_RUN.json", "verifier/runs/v75.jsonl")
runner.VERIFIER_COMMAND = "python3 verifier/v75/verify.py"
runner.CONTROL_FILES = (*runner.CONTROL_FILES, "scripts/run_acceptance_v74.py", "scripts/run_acceptance_v75.py",
                        "scripts/setup_ci_tmpdir.sh", "scripts/tests/test_verifier_v74_contract.py",
                        "scripts/tests/test_run_acceptance_v74.py", "scripts/tests/test_verifier_v75_contract.py",
                        "scripts/tests/test_run_acceptance_v75.py", "scripts/setup_linux_ci.sh",
                        "scripts/verify_acceptance_v75.py", "scripts/tests/test_verify_acceptance_v75.py")
_base_passing_checks = runner._passing_checks


def _passing_v75_checks(checks):
    try:
        expected = json.loads((runner.ROOT / 'm0/verifier/v75/expected-checks.json').read_text())
        return (isinstance(expected, list) and len(expected) == 56 and len(set(expected)) == 56
                and _base_passing_checks(checks) and {row['check'] for row in checks} == set(expected))
    except (OSError, ValueError, TypeError, KeyError):
        return False


runner._passing_checks = _passing_v75_checks
IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist'}
GENERATED = {'m0/' + name for name in runner.HISTORY}


def included(name):
    path = Path(name)
    return name not in GENERATED and not any(p in IGNORED or p.endswith('.egg-info') for p in path.parts) \
        and path.suffix != '.pyc'


def snapshot(root):
    paths = [p for p in (root / 'm0').rglob('*') if p.is_file() or p.is_symlink()]
    paths += [root / name for name in runner.CONTROL_FILES if (root / name).exists()]
    result = {}
    for path in paths:
        name = str(path.relative_to(root))
        if not included(name):
            continue
        if path.is_symlink():
            raise ValueError('acceptance source contains a symlink: ' + name)
        result[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'executable': bool(path.stat().st_mode & 0o111)}
    return dict(sorted(result.items()))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def commit_binding(root, files):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)
    try:
        sha = git('rev-parse', 'HEAD').decode().strip()
        algorithm = git('rev-parse', '--show-object-format').decode().strip()
        tree = git('ls-tree', '-rz', '--full-tree', sha, '--', 'm0', *runner.CONTROL_FILES)
    except subprocess.CalledProcessError:
        return None, False
    expected = {}
    for row in tree.split(b'\0'):
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        name = raw_name.decode()
        if included(name):
            expected[name] = (mode, kind, oid)
    if set(expected) != set(files):
        return sha, False
    for name, (mode, kind, oid) in expected.items():
        content = (root / name).read_bytes()
        actual = hashlib.new(algorithm, b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if kind != 'blob' or mode not in {'100644', '100755'} or actual != oid or \
                files[name]['executable'] != (mode == '100755'):
            return sha, False
    return sha, True


def main(argv=None):
    before = snapshot(runner.ROOT)
    commit, matches = commit_binding(runner.ROOT, before)
    def finalize(summary, output):
        after = snapshot(runner.ROOT)
        final_commit, final_matches = commit_binding(runner.ROOT, after)
        unchanged = before == after and commit == final_commit
        errors = list(summary['errors'])
        if not matches or not final_matches:
            errors.append('Acceptance source does not match its exact Git commit')
        if not unchanged:
            errors.append('Original source or commit changed during acceptance')
        if summary['execution_source_manifest_sha256'] != digest(before):
            errors.append('Executed copy differs from the committed input source')
        (output / 'source-files.json').write_text(json.dumps(before, sort_keys=True, indent=2) + '\n')
        return {**summary, 'passed': summary['passed'] and not errors, 'errors': errors,
            'error': errors[0] if errors else None,
            'source_binding': {'commit': commit, 'matches_commit': matches and final_matches,
                'unchanged': unchanged, 'source_manifest_sha256': digest(before), 'file_count': len(before),
                'scope': 'm0 payload and active acceptance control files; current version output history excluded'}}
    return runner.main(argv, source_snapshot=snapshot, finalize_summary=finalize)


if __name__ == '__main__':
    raise SystemExit(main())
