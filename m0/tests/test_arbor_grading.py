"""Post-selection grading is durable, isolated, and never selects a winner."""
import json
from pathlib import Path

import pytest

from test_mle_composed import fixture_public, TrustedFixtureRunner
from zoo.mle_bench_lite.arbor_runner import run


@pytest.mark.parametrize('failure', [False, True])
def test_grade_only_frozen_submission_once_and_reject_drift(tmp_path, failure):
    from zoo.mle_bench_lite.arbor_grading import grade_selected
    root = tmp_path / 'run'
    run(output=root, public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_cycles=1, runner=TrustedFixtureRunner())
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
    kwargs = dict(output=root, adapter=Adapter(), public_root=tmp_path / 'public', prepared_identity={'test': 'synthetic'}, fixture=True)
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
    from zoo.mle_bench_lite.arbor_grading import grade_selected
    from core.x1.store import AppendOnlyStore
    root = tmp_path / 'run'
    report = run(output=root, public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_cycles=1, runner=TrustedFixtureRunner())
    class Never:
        competition_id = 'spooky-author-identification'
        def grade_submission(self, *a, **kw):
            pytest.fail('grader must not run')
    journal = AppendOnlyStore(root / 'official/audit.jsonl')
    journal.append('arbor_grading_started', {'unknown': 'previous invocation'})
    with pytest.raises(ValueError, match='unfinished'):
        grade_selected(output=root, adapter=Never(), public_root=tmp_path / 'public', prepared_identity={}, fixture=True)
    report['run_state'] = 'execution_failed'
    (root / 'method-report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='completed'):
        grade_selected(output=root, adapter=Never(), public_root=tmp_path / 'public', prepared_identity={}, fixture=True)


def test_rehashed_summary_cannot_authorize_substituted_submission(tmp_path):
    import csv
    from zoo.mle_bench_lite.arbor_grading import grade_selected
    from zoo.mle_bench_lite.public_train import file_digest, write_csv
    root = tmp_path / 'run'
    run(output=root, public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_cycles=1, runner=TrustedFixtureRunner())
    with (root / 'submission.csv').open() as stream:
        reader=csv.DictReader(stream); columns=reader.fieldnames; rows=list(reader)
    for row in rows:
        row.update(A=.8, B=.1, C=.1)
    write_csv(root / 'submission.csv', columns, rows)
    report=json.loads((root / 'method-report.json').read_text())
    report['submission']['submission_sha256']=file_digest(root / 'submission.csv')
    (root / 'method-report.json').write_text(json.dumps(report))
    class Never:
        competition_id='spooky-author-identification'
        def grade_submission(self,*a,**kw):
            pytest.fail('substituted submission must not be graded')
    with pytest.raises(ValueError, match='prediction|submission'):
        grade_selected(output=root, adapter=Never(), public_root=tmp_path / 'public', prepared_identity={}, fixture=True)


def test_concurrent_grading_has_only_one_claim_and_grader_call(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from core.x1.store import AppendOnlyStore
    from zoo.mle_bench_lite.arbor_grading import grade_selected
    root=tmp_path/'run'
    run(output=root,public_root=fixture_public(tmp_path/'public'),
        task_id='spooky-author-identification',max_cycles=1,runner=TrustedFixtureRunner())
    barrier=threading.Barrier(2)
    original_read=AppendOnlyStore.read
    def race_read(self, kind=None):
        rows=list(original_read(self,kind))
        if kind=='arbor_grading_completed' and not rows:
            try: barrier.wait(timeout=.5)
            except threading.BrokenBarrierError: pass
        yield from rows
    monkeypatch.setattr(AppendOnlyStore,'read',race_read)
    calls=[]
    class Adapter:
        competition_id='spooky-author-identification'
        def grade_submission(self,*a,**kw):
            calls.append(1)
            return {'competition_id':self.competition_id,'valid_submission':True,'audit/score':1.2}
    def invoke():
        try:
            return grade_selected(output=root,adapter=Adapter(),public_root=tmp_path / 'public', prepared_identity={},fixture=True)
        except RuntimeError as error:
            assert 'coordinator' in str(error)
            return {'state':'busy'}
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:invoke(),range(2)))
    assert len(calls)==1
    assert sorted(r['state'] for r in results)==['busy','completed']
    assert invoke()['state']=='completed' and len(calls)==1
    assert len(list(AppendOnlyStore(root/'official/audit.jsonl').read('arbor_grading_started')))==1


