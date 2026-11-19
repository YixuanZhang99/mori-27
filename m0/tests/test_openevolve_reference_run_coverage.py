"""Reference coverage reports preserve early and incomplete run outcomes."""
from zoo.circle_packing.reference_iteration_trace import summarize_reference_run_coverage


def test_early_stop_does_not_invent_missing_iterations():
    trace = {'controller_run': {'start_iteration': 1, 'max_iterations': 3,
                                'reported_completed_iterations': 1, 'stop_reason': 'early_stopping'}}
    receipts = {'iterations': [{'iteration': 1, 'state': 'candidate', 'receipt_state': 'matched'}],
                'missing_iterations': [2, 3]}
    provider = {'iterations': [{'iteration': 1, 'state': 'matched'}],
                'missing_prompt_iterations': [2, 3], 'unattributed_provider_bindings': []}
    stages = {'stages': [{'iteration': 1, 'state': 'matched', 'stage_status': 'ok'}],
              'unattributed_stage_ids': []}
    report = summarize_reference_run_coverage(trace, receipts, provider, stages, planned_iterations=3)
    assert report['controller_stop_reason'] == 'early_stopping'
    assert [row['iteration'] for row in report['iterations']] == [1, 2, 3]
    assert report['iterations'][1]['submission_state'] == 'not_submitted'
    assert report['complete_run_certified'] is False and report['performance_claim'] is False
