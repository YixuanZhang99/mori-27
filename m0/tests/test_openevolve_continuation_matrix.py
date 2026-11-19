"""Continuation claims remain separate from the historical pilot and scores."""
import copy
import pytest

from core.composition.recovery import ContinuationStore
from test_openevolve_continuation_binding import prepared, bind
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle

pytestmark = pytest.mark.linux


def test_continuation_inventory_is_pinned_separate_and_read_only(tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_matrix import snapshot_continuation_matrix
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, *_ = values
    artifacts = bind(values)
    ref = 'sha256:' + draft['draft_sha256']
    initial = ledger.snapshot()
    report = snapshot_continuation_matrix(ledger, draft, expected_plan_ref=ref, expected_head=initial['journal_head'])
    assert report['experiment_id'] == 'circle-v2'
    assert report['tree_ref'] == artifacts['tree_ref'] and report['runtime_ref'] == artifacts['runtime_ref']
    assert report['source_commit'] == draft['source_commit'] and report['method_changes'] == draft['method_changes']
    assert len(report['cells']) == 6
    assert {c['cell_id'] for c in report['cells']} == {c['cell_id'] for c in draft['cells']}
    assert all(c['state'] == 'not_claimed' and c['score'] is None for c in report['cells'])
    assert report['performance_claim'] is False and ledger.snapshot() == initial
    CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='circle-v2--mori-0', plan_ref=ref, seconds=2700)
    after = ledger.snapshot()
    with pytest.raises(ValueError):
        snapshot_continuation_matrix(ledger, draft, expected_plan_ref=ref, expected_head=initial['journal_head'])
    changed = copy.deepcopy(draft)
    changed['method_changes'] = ['changed']
    with pytest.raises(ValueError):
        snapshot_continuation_matrix(ledger, changed, expected_plan_ref=ref, expected_head=after['journal_head'])
    changed = copy.deepcopy(draft)
    changed['cells'][0]['seed'] = False
    with pytest.raises(ValueError):
        snapshot_continuation_matrix(ledger, changed, expected_plan_ref=ref, expected_head=after['journal_head'])
    with pytest.raises(ValueError):
        snapshot_continuation_matrix(ledger, draft, expected_plan_ref='sha256:' + '0' * 64, expected_head=after['journal_head'])
    report = snapshot_continuation_matrix(ledger, draft, expected_plan_ref=ref, expected_head=after['journal_head'])
    claimed = [c['cell_id'] for c in report['cells'] if c['state'] == 'claimed_outcome_unverified']
    assert claimed == ['circle-v2--mori-0'] and ledger.snapshot() == after
    report['cells'][0]['state'] = 'tampered'
    report['method_changes'].append('tampered')
    again = snapshot_continuation_matrix(ledger, draft, expected_plan_ref=ref, expected_head=after['journal_head'])
    assert all(c['state'] != 'tampered' for c in again['cells'])
    assert 'tampered' not in again['method_changes']
