"""Reference iteration receipts must refer to the original physical program."""
import copy

import pytest

from zoo.circle_packing.reference_iteration_trace import audit_reference_iteration_receipts


def test_iteration_receipts_match_original_stage_and_preserve_unlinked_failures():
    trace = {'schema_version': 1, 'scope': 'reference_submitted_future_outcomes', 'performance_claim': False,
             'iterations': [{'iteration': 1, 'state': 'candidate', 'program_sha256': 'a' * 64,
                             'stage_request_id': 'b' * 32},
                            {'iteration': 2, 'state': 'worker_error'},
                            {'iteration': 3, 'state': 'candidate', 'program_sha256': 'c' * 64}]}
    rows = [{'kind': 'host_stage_started', 'payload': {'request_id': 'b' * 32, 'program_ref': 'sha256:' + 'a' * 64}}]
    report = audit_reference_iteration_receipts(trace, rows, planned_iterations=3)
    assert [item['receipt_state'] for item in report['iterations']] == ['matched', 'not_available', 'not_available']
    altered = copy.deepcopy(rows)
    altered[0]['payload']['program_ref'] = 'sha256:' + 'f' * 64
    with pytest.raises(ValueError, match='stage'):
        audit_reference_iteration_receipts(trace, altered, planned_iterations=3)
