"""Independently compare v76 artifacts to the named Git tree, without live calls."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

if not __debug__:
    raise RuntimeError('independent acceptance verification requires assertions enabled')

parser = argparse.ArgumentParser()
parser.add_argument('artifact_directory', type=Path)
parser.add_argument('commit')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
root = args.artifact_directory
def read(name):
    return json.loads((root / name).read_text())
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

summary, certificate = read('summary.json'), read('LAST_RUN.json')
journal = [json.loads(line) for line in (root / 'new-runs.jsonl').read_text().splitlines() if line.strip()]
assert summary['verifier_version'] == 'v76' and summary['passed'] is True
assert summary['verifier_exit_code'] == 0 and not summary['errors'] and not summary['timed_out']
assert summary['certificate_passed'] and summary['new_journal_passed'] and summary['source_history_unchanged']
assert certificate['version'] == 'v76' and certificate['passed'] is True
checks = certificate['checks']
assert len(checks) == len({row['check'] for row in checks}) == 57
assert all(row['passed'] is True for row in checks)
expected_checks = json.loads(subprocess.check_output(
    ['git', 'show', args.commit + ':m0/verifier/v76/expected-checks.json'], cwd=repo))
assert isinstance(expected_checks, list) and len(expected_checks) == len(set(expected_checks)) == 57
assert {row['check'] for row in checks} == set(expected_checks)
assert len(journal) == 1 and journal[0]['exit_code'] == 0 and journal[0]['checks'] == checks
assert journal[0]['command'] == 'python3 verifier/v76/verify.py'
assert certificate['m7_configured_execution_evidence']['certified'] is True
binding = summary['source_binding']
assert binding['commit'] == args.commit and binding['matches_commit'] and binding['unchanged']
assert summary['execution_source_unchanged']
original, executed = read('source-files.json'), read('execution-source-files.json')
assert original == executed and len(original) == binding['file_count']
assert digest(original) == binding['source_manifest_sha256'] == summary['execution_source_manifest_sha256']

# Read committed bytes in one batch; do not trust the artifact's claimed hashes.
controls = ['.github/workflows/ci.yml', 'Makefile', 'scripts/run_acceptance.py',
            'scripts/run_acceptance_v74.py', 'scripts/run_acceptance_v76.py', 'scripts/setup_ci_tmpdir.sh',
            'scripts/tests/test_verifier_v74_contract.py', 'scripts/tests/test_run_acceptance_v74.py',
            'scripts/tests/test_verifier_v76_contract.py', 'scripts/tests/test_run_acceptance_v76.py',
            'scripts/setup_linux_ci.sh', 'scripts/verify_acceptance_v76.py',
            'scripts/tests/test_verify_acceptance_v76.py']
controls += ['scripts/run_acceptance_v75.py', 'scripts/verify_acceptance_v75.py',
            'scripts/tests/test_verifier_v75_contract.py', 'scripts/tests/test_run_acceptance_v75.py',
            'scripts/tests/test_verify_acceptance_v75.py']
tree = subprocess.check_output(['git', 'ls-tree', '-rz', args.commit, '--', 'm0', *controls], cwd=repo)
entries = []
for row in tree.split(b'\0'):
    if not row:
        continue
    metadata, name = row.split(b'\t', 1)
    mode, kind, oid = metadata.decode().split()
    name = name.decode()
    parts = Path(name).parts
    if name in {'m0/verifier/v76/LAST_RUN.json', 'm0/verifier/runs/v76.jsonl'} or name.endswith('.pyc'):
        continue
    if any(p in {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist'} or p.endswith('.egg-info') for p in parts):
        continue
    assert kind == 'blob' and mode in {'100644', '100755'}
    entries.append((name, mode, oid))
batch = subprocess.run(['git', 'cat-file', '--batch'], cwd=repo,
    input=''.join(oid + '\n' for _, _, oid in entries).encode(), capture_output=True, check=True).stdout
expected, offset = {}, 0
for name, mode, oid in entries:
    end = batch.index(b'\n', offset)
    got_oid, kind, size = batch[offset:end].decode().split()
    assert got_oid == oid and kind == 'blob'
    size = int(size)
    content = batch[end + 1:end + 1 + size]
    expected[name] = {'sha256': hashlib.sha256(content).hexdigest(), 'executable': mode == '100755'}
    offset = end + size + 2
assert offset == len(batch) and expected == original
report = {'passed': True, 'commit': args.commit, 'checks': 57,
    'elapsed_seconds': summary['elapsed_seconds'], 'verified_source_files': len(original),
    'source_manifest_sha256': digest(original), 'artifact_directory': str(root.resolve()),
    'artifact_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}}
args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k != 'artifact_sha256'}, indent=2))
