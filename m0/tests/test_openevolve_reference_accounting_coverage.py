"""A complete accounting report must explain the seed and all iterations."""
import copy

from zoo.circle_packing.reference_iteration_trace import audit_reference_accounting_coverage


def test_seed_stage_and_each_iteration_must_be_accounted():
    seed_id, stage_id = 'a' * 32, 'b' * 32
    plan = {'iterations': 1, 'seed_sha256': 'c' * 64}
    rows = [
        {'kind': 'host_stage_started', 'payload': {'request_id': seed_id, 'stage': 1,
            'prior_id': None, 'program_ref': 'sha256:' + plan['seed_sha256']}},
        {'kind': 'composed_provider_started', 'payload': {'invocation': {'external_context': {'lane': 'main'}}}},
        {'kind': 'host_stage_started', 'payload': {'request_id': stage_id, 'stage': 1,
            'prior_id': None, 'program_ref': 'sha256:' + 'd' * 64}},
    ]
    coverage = {'controller_stop_reason': 'iteration_limit', 'controller_reported_completed_iterations': 1,
                'iterations': [{'iteration': 1, 'submission_state': 'candidate', 'provider_states': ['matched']}]}
    provider = {'missing_prompt_iterations': [], 'unattributed_provider_bindings': [],
                'iterations': [{'iteration': 1, 'state': 'matched'}]}
    stages = {'unattributed_stage_ids': [seed_id], 'stages': [{'iteration': 1, 'request_id': stage_id,
              'state': 'matched', 'stage_status': 'ok', 'candidate_program_digest_matches': True}]}
    result = audit_reference_accounting_coverage(coverage, provider, stages, rows=rows, plan=plan)
    assert result['iteration_accounting_complete'] is True
    assert result['complete_run_certified'] is False and result['seed_stage_ids'] == [seed_id]
    changed = copy.deepcopy(stages)
    changed['unattributed_stage_ids'].append(stage_id)
    assert not audit_reference_accounting_coverage(coverage, provider, changed, rows=rows, plan=plan)['iteration_accounting_complete']
