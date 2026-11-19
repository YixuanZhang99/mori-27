"""The six-cell inventory is anchored to the original campaign head."""
import copy

import pytest

pytestmark = pytest.mark.linux

from core.composition.recovery import ContinuationStore
from test_governed_cny_framework import campaign_fixture
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.pilot_plan import build_draft_plan


def frozen(tmp_path):
    ledger = campaign_fixture(tmp_path)
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    ledger.freeze_circle_pilot(ref, 'sha256:' + 'c' * 64, plan['limits']['wallclock_seconds'])
    return ledger, plan, ref


def test_matrix_preserves_all_six_cells_and_distinguishes_claimed(tmp_path):
    from zoo.circle_packing.pilot_matrix import snapshot_matrix
    ledger, plan, ref = frozen(tmp_path)
    CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    head = ledger.snapshot()['journal_head']
    report = snapshot_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head)
    assert report['journal_head'] == head and report['plan_ref'] == ref
    assert [cell['cell_id'] for cell in report['cells']] == [
        'vendor-0', 'mori-0', 'vendor-1', 'mori-1', 'vendor-2', 'mori-2']
    assert [cell['state'] for cell in report['cells']] == [
        'not_claimed', 'claimed_outcome_unverified', 'not_claimed', 'not_claimed', 'not_claimed', 'not_claimed']
    assert all(cell['score'] is None for cell in report['cells'])
    assert report['performance_claim'] is False
    assert ledger.snapshot()['journal_head'] == head


def test_matrix_rejects_stale_head_wrong_plan_and_unfrozen_campaign(tmp_path):
    from zoo.circle_packing.pilot_matrix import snapshot_matrix
    ledger, plan, ref = frozen(tmp_path)
    old_head = ledger.snapshot()['journal_head']
    CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    with pytest.raises(ValueError, match='head'):
        snapshot_matrix(ledger, plan, expected_plan_ref=ref, expected_head=old_head)
    altered = copy.deepcopy(plan)
    altered['iterations'] += 1
    with pytest.raises(ValueError, match='plan'):
        snapshot_matrix(ledger, altered, expected_plan_ref=ref, expected_head=ledger.snapshot()['journal_head'])
    (tmp_path / 'other').mkdir()
    other = campaign_fixture(tmp_path / 'other')
    other_plan = build_draft_plan(other.manifest_binding(), source_commit='a' * 40,
                                  dependency_lock_sha256='b' * 64)
    with pytest.raises(ValueError, match='frozen'):
        snapshot_matrix(other, other_plan, expected_plan_ref='sha256:' + other_plan['draft_sha256'],
                        expected_head=other.snapshot()['journal_head'])


def test_claim_inventory_is_detached_from_ledger(tmp_path):
    ledger, plan, ref = frozen(tmp_path)
    CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    head = ledger.snapshot()['journal_head']
    inventory = ledger.circle_claim_inventory(expected_head=head)
    inventory['claims']['vendor-0']['plan_ref'] = 'changed'
    inventory['campaign']['campaign_id'] = 'changed'
    again = ledger.circle_claim_inventory(expected_head=head)
    assert again['claims']['vendor-0']['plan_ref'] == ref
    assert again['campaign']['campaign_id'] == ledger.manifest_binding()['campaign_id']
    assert ledger.snapshot()['journal_head'] == head
