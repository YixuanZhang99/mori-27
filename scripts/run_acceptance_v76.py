#!/usr/bin/env python3
"""V76 acceptance bound to the exact committed and executed source."""
import json
import os
import subprocess

import run_acceptance_v75 as previous

runner = previous.runner
VERIFIER_VERSION = "v76"
runner.VERIFIER_VERSION = VERIFIER_VERSION
runner.HISTORY = ('verifier/v76/LAST_RUN.json', 'verifier/runs/v76.jsonl')
runner.VERIFIER_COMMAND = 'python3 verifier/v76/verify.py'
runner.CONTROL_FILES = (*runner.CONTROL_FILES, 'scripts/run_acceptance_v76.py',
                        'scripts/verify_acceptance_v76.py', 'scripts/tests/test_verifier_v76_contract.py',
                        'scripts/tests/test_run_acceptance_v76.py', 'scripts/tests/test_verify_acceptance_v76.py')
previous.GENERATED = {'m0/' + name for name in runner.HISTORY}


def _passing_v76_checks(checks):
    try:
        expected = json.loads((runner.ROOT / 'm0/verifier/v76/expected-checks.json').read_text())
        return (isinstance(expected, list) and len(expected) == 57 and len(set(expected)) == 57
                and previous._base_passing_checks(checks) and {row['check'] for row in checks} == set(expected))
    except (OSError, ValueError, TypeError, KeyError):
        return False


runner._passing_checks = _passing_v76_checks


def prepare_git_copy(source, destination):
    """Clone committed objects only; do not copy untracked local files."""
    env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0',
           'GIT_LFS_SKIP_SMUDGE': '1'}
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', '--verify', 'HEAD'],
                                     env=env, stderr=subprocess.DEVNULL, text=True).strip()
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--quiet', '--no-local',
                    '--no-checkout', '--depth=1', str(source), str(destination)],
                   check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['git', '-C', str(destination), '-c', 'core.hooksPath=/dev/null',
                    'checkout', '--quiet', '--detach', commit], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv=None):
    before = previous.snapshot(runner.ROOT)
    commit, matches = previous.commit_binding(runner.ROOT, before)
    def finalize(summary, output):
        after = previous.snapshot(runner.ROOT)
        final_commit, final_matches = previous.commit_binding(runner.ROOT, after)
        unchanged = before == after and commit == final_commit
        errors = list(summary['errors'])
        if not matches or not final_matches:
            errors.append('Acceptance source does not match its exact Git commit')
        if not unchanged:
            errors.append('Original source or commit changed during acceptance')
        if summary['execution_source_manifest_sha256'] != previous.digest(before):
            errors.append('Executed copy differs from the committed input source')
        (output / 'source-files.json').write_text(json.dumps(before, sort_keys=True, indent=2) + '\n')
        return {**summary, 'passed': summary['passed'] and not errors, 'errors': errors,
            'error': errors[0] if errors else None,
            'source_binding': {'commit': commit, 'matches_commit': matches and final_matches,
                'unchanged': unchanged, 'source_manifest_sha256': previous.digest(before),
                'file_count': len(before),
                'scope': 'm0 payload and active acceptance control files; current version output history excluded'}}
    return runner.main(argv, source_snapshot=previous.snapshot, finalize_summary=finalize,
                       prepare_copy=prepare_git_copy)


if __name__ == '__main__':
    raise SystemExit(main())
