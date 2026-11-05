"""Post-selection grading is durable, isolated, and never selects a winner."""
import json
from pathlib import Path

import pytest

from test_mle_composed import fixture_public, TrustedFixtureRunner
from zoo.mle_bench_lite.aide_runner import run


@pytest.mark.parametrize('failure', [False, True])
def test_grade_only_frozen_submission_once_and_reject_drift(tmp_path, failure):
    from zoo.mle_bench_lite.aide_grading import grade_selected
    root = tmp_path / 'run'
    run(output=root, public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_nodes=1, runner=TrustedFixtureRunner())
    original = (root / 'method-report.json').read_bytes()
    calls = []
    class Adapter:
        competition_id = 'spooky-author-identification'
        def grade_submission(self, workspace, visibility, audit_store, grader=None):
            assert visibility == 'audit'
            calls.append(Path(workspace.root) / 'submission.csv')
            if failure:
                raise RuntimeError('fixture failure')
            return {'competition_id': self.competition_id, 'valid_submission': True, 'audit/score': 1.25}
    kwargs = dict(output=root, adapter=Adapter(), prepared_identity={'test': 'synthetic'}, fixture=True)
    report = grade_selected(**kwargs)
    assert report['state'] == ('grading_failed' if failure else 'completed')
    assert report['official_score'] == (None if failure else 1.25)
    assert not report['external_benchmark_score_produced']
    assert grade_selected(**kwargs) == report and len(calls) == 1
    assert (root / 'method-report.json').read_bytes() == original
    (root / 'submission.csv').write_text('tampered\n')
    with pytest.raises(ValueError, match='submission'):
        grade_selected(**kwargs)
    assert len(calls) == 1


def test_unfinished_grading_and_unfrozen_selection_cannot_trigger_grader(tmp_path):
    from zoo.mle_bench_lite.aide_grading import grade_selected
    from core.x1.store import AppendOnlyStore
    root = tmp_path / 'run'
    report = run(output=root, public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_nodes=1, runner=TrustedFixtureRunner())
    class Never:
        competition_id = 'spooky-author-identification'
        def grade_submission(self, *a, **kw):
            pytest.fail('grader must not run')
    journal = AppendOnlyStore(root / 'official/audit.jsonl')
    journal.append('aide_grading_started', {'unknown': 'previous invocation'})
    with pytest.raises(ValueError, match='unfinished'):
        grade_selected(output=root, adapter=Never(), prepared_identity={}, fixture=True)
    report['run_state'] = 'execution_failed'
    (root / 'method-report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='completed'):
        grade_selected(output=root, adapter=Never(), prepared_identity={}, fixture=True)
