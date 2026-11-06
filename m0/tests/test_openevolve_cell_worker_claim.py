"""A controller launch claim survives local worker journal loss."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.composition.recovery import ContinuationStore
from test_openevolve_cell_deadline import _lifecycle
from zoo.circle_packing.cell_deadline import CellDeadline


def authority(tmp_path):
    store = ContinuationStore(tmp_path / 'clock.jsonl')
    lifecycle = _lifecycle(store.path)
    deadline = CellDeadline.start(store, lifecycle=lifecycle, cell_id='vendor-0',
                                  plan_ref='sha256:' + 'a' * 64, seconds=60)
    return lifecycle, deadline


def test_worker_claim_binds_original_deadline_and_cannot_be_reused(tmp_path):
    lifecycle, deadline = authority(tmp_path)
    ledger = lifecycle.ledger
    clock_ref = deadline._record['record_sha256']
    worker_ref = 'b' * 64
    ledger.claim_cell_worker('vendor-0', clock_ref, worker_ref)
    assert ledger.cell_worker_claim('vendor-0') == {'deadline_ref': clock_ref, 'worker_ref': worker_ref}
    with pytest.raises(ValueError, match='worker'):
        ledger.claim_cell_worker('vendor-0', clock_ref, worker_ref)
    with pytest.raises(ValueError, match='worker'):
        ledger.claim_cell_worker('vendor-0', clock_ref, 'c' * 64)


def test_worker_claim_rejects_wrong_or_missing_clock(tmp_path):
    lifecycle, _ = authority(tmp_path)
    with pytest.raises(ValueError, match='deadline'):
        lifecycle.ledger.claim_cell_worker('vendor-0', 'f' * 64, 'b' * 64)
    with pytest.raises(ValueError, match='deadline'):
        lifecycle.ledger.claim_cell_worker('mori-0', 'f' * 64, 'b' * 64)


def test_concurrent_worker_claims_allow_one_launch(tmp_path):
    lifecycle, deadline = authority(tmp_path)
    def claim(worker_ref):
        try:
            lifecycle.ledger.claim_cell_worker('vendor-0', deadline._record['record_sha256'], worker_ref * 64)
            return 'claimed'
        except ValueError:
            return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, ['b', 'c'])) == ['claimed', 'rejected']
