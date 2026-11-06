#!/usr/bin/env python3
"""V76 acceptance bound to the exact committed and executed source."""
import json

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


if __name__ == '__main__':
    raise SystemExit(previous.main())
