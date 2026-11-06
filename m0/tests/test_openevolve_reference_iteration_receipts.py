"""Reference iteration receipts must refer to the original physical program."""
import copy

import pytest

from zoo.circle_packing.reference_iteration_trace import audit_reference_iteration_receipts, reference_iteration_attempt_limit


def test_iteration_receipts_match_original_stage_and_preserve_unlinked_failures():
    trace = {'schema_version': 1, 'scope': 'reference_submitted_future_outcomes', 'performance_claim': False,
             'iterations': [{'iteration': 1, 'state': 'candidate', 'program_sha256': 'a' * 64,
                             'stage_request_id': 'b' * 32},
                            {'iteration': 2, 'state': 'worker_error'},
                            {'iteration': 3, 'state': 'candidate', 'program_sha256': 'c' * 64}]}
    rows = [{'kind': 'host_stage_started', 'payload': {'request_id': 'b' * 32, 'program_ref': 'sha256:' + 'a' * 64}}]
    report = audit_reference_iteration_receipts(trace, rows, planned_iterations=3)
    assert [item['receipt_state'] for item in report['iterations']] == ['matched', 'not_available', 'not_available']
    assert report['missing_iterations'] == []
    assert audit_reference_iteration_receipts({**trace, 'iterations': trace['iterations'][:2]}, rows,
                                               planned_iterations=3)['missing_iterations'] == [3]
    altered = copy.deepcopy(rows)
    altered[0]['payload']['program_ref'] = 'sha256:' + 'f' * 64
    with pytest.raises(ValueError, match='stage'):
        audit_reference_iteration_receipts(trace, altered, planned_iterations=3)
    invalid = copy.deepcopy(trace)
    invalid['iterations'][2]['stage_receipt_invalid'] = True
    with pytest.raises(ValueError, match='stage'):
        audit_reference_iteration_receipts(invalid, rows, planned_iterations=3)


def test_not_submitted_iteration_can_be_retried_without_hiding_missing_work():
    trace = {'scope': 'reference_submitted_future_outcomes', 'performance_claim': False,
             'iterations': [{'iteration': 1, 'state': 'not_submitted'},
                            {'iteration': 1, 'state': 'worker_error'},
                            {'iteration': 2, 'state': 'not_submitted'}]}
    report = audit_reference_iteration_receipts(trace, [], planned_iterations=2)
    assert [item['attempt'] for item in report['iterations']] == [1, 2, 1]
    assert report['missing_iterations'] == [2]


def test_attempt_bound_accounts_for_each_island_per_completion():
    assert reference_iteration_attempt_limit(6) >= 14
