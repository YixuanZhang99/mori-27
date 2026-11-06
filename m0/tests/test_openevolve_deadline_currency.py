"""Cell-clock evidence must coexist with the original governed currency bridge."""
from unittest.mock import patch

import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_bridge import setup
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle


def test_cell_clock_events_do_not_change_governed_call_or_recovery(setup, tmp_path):
    ledger, bridge, run, context, providers, calls, store, physical = setup
    lifecycle = CellLifecycle(ledger)
    clock_store = ContinuationStore(tmp_path / 'clock.jsonl')
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 101]):
        clock = CellDeadline.start(clock_store, lifecycle=lifecycle, cell_id='vendor-0',
                                   plan_ref='sha256:' + 'a' * 64, seconds=5)
        clock.check()
        assert bridge.invoke(context, ('prompt',), {}) == 'answer'
        outcome = bridge.recover(context, context.argument_sha256)
        assert outcome.outcome == 'returned'
        assert len(calls) == 1
        assert ledger.snapshot()['pending_calls'] == []
