"""Stage attribution retains failures and unresolved work."""
import copy

import pytest

from zoo.circle_packing.reference_iteration_trace import audit_reference_iteration_stages


def test_recorded_iteration_stage_checks_original_identity_and_outcome():
    stage_id = 'b' * 32
    program = 'sha256:' + 'a' * 64
    trace = {'iterations': [{'iteration': 1, 'state': 'candidate', 'program_sha256': 'a' * 64}],
             'stage_bindings': [{'iteration': 1, 'request_id': stage_id, 'program_ref': program,
                                 'stage': 1, 'prior_id': None}]}
    rows = [{'kind': 'host_stage_started', 'payload': {'request_id': stage_id, 'program_ref': program,
                                                       'stage': 1, 'prior_id': None}},
            {'kind': 'host_stage_completed', 'payload': {'request_id': stage_id, 'result': {'status': 'timeout'}}}]
    result = audit_reference_iteration_stages(trace, rows, planned_iterations=2)
    assert result['stages'][0]['state'] == 'matched' and result['stages'][0]['stage_status'] == 'timeout'
    assert result['unattributed_stage_ids'] == []
    damaged = copy.deepcopy(rows)
    damaged[0]['payload']['program_ref'] = 'sha256:' + 'f' * 64
    with pytest.raises(ValueError, match='stage'):
        audit_reference_iteration_stages(trace, damaged, planned_iterations=2)
    missing = audit_reference_iteration_stages(trace, [], planned_iterations=2)
    assert missing['stages'][0]['state'] == 'not_observed'
