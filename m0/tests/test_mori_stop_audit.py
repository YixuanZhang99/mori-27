"""Early-stop reports preserve the recorded cause without certifying a run."""
from copy import deepcopy

import pytest

from zoo.circle_packing.mori_cycle_audit import summarize_recorded_mori_stop


@pytest.mark.parametrize('started', [False, True])
def test_early_stop_reports_the_matching_cycle_and_disposition(started):
    checkpoint = {'next_cycle': 1, 'halted_reason': 'budget exhausted'}
    rows = [{'kind': 'composed_cycle_started', 'payload': {'cycle': 0}}]
    if started:
        rows.append({'kind': 'composed_cycle_started', 'payload': {'cycle': 1}})
    rows.extend([{'kind': 'composed_cycle_aborted' if started else 'composed_stopped',
                  'payload': {'cycle': 1, 'reason': 'budget exhausted'}},
                 {'kind': 'governed_main_stopped', 'payload': {'main_cycles': 1, 'disposition': 'ordinary'}}])
    result = summarize_recorded_mori_stop(checkpoint, rows, planned_iterations=6)
    assert result['stop_cycle'] == 1 and result['reason'] == 'budget exhausted'
    assert result['started'] is started and result['complete_run_certified'] is False
    wrong = deepcopy(rows)
    wrong[-2]['payload']['reason'] = 'other'
    with pytest.raises(ValueError):
        summarize_recorded_mori_stop(checkpoint, wrong, planned_iterations=6)
    with pytest.raises(ValueError):
        summarize_recorded_mori_stop(checkpoint, rows[:-1], planned_iterations=6)
    wrong = deepcopy(rows)
    wrong.append({'kind': 'composed_cycle_started', 'payload': {'cycle': 2}})
    with pytest.raises(ValueError):
        summarize_recorded_mori_stop(checkpoint, wrong, planned_iterations=6)
    wrong = deepcopy(rows)
    wrong[0]['payload']['cycle'] = False
    with pytest.raises(ValueError):
        summarize_recorded_mori_stop(checkpoint, wrong, planned_iterations=6)
