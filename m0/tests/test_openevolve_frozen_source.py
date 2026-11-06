"""Bind a clean snapshot and draft to the original campaign before cell work."""
import threading
import time
import shutil

import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_framework import campaign_fixture
from test_openevolve_source_preflight import checkout, draft
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle


def fixture(tmp_path):
    root = tmp_path / 'checkout'
    commit = checkout(root)
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    return root, ledger, plan, ref, ledger.manifest_binding()['campaign_id']


def test_original_campaign_anchors_source_and_all_cells(tmp_path):
    from zoo.circle_packing.frozen_source import freeze_source_plan, verify_frozen_source
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    result = freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'source',
                                expected_plan_ref=ref, expected_campaign_id=campaign_id)
    assert ledger.circle_pilot_binding() == {'plan_ref': ref, 'tree_ref': result['tree_ref'],
                                             'wallclock_seconds': 2700}
    with pytest.raises(ValueError, match='pilot'):
        ledger.freeze_circle_pilot(ref, result['tree_ref'], 2700)
    with pytest.raises(ValueError, match='pilot'):
        ledger.freeze_circle_pilot(ref, 'sha256:' + 'f' * 64, 2700)
    assert verify_frozen_source(ledger, plan, snapshot=tmp_path / 'source', manifest=result['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id)['tree_ref'] == result['tree_ref']
    CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='vendor-0', plan_ref=ref, seconds=2700)
    with pytest.raises(ValueError, match='plan'):
        CellDeadline.start(ContinuationStore(tmp_path / 'other-clock.jsonl'), lifecycle=CellLifecycle(ledger),
                           cell_id='mori-0', plan_ref='sha256:' + 'c' * 64, seconds=2700)
    with pytest.raises(ValueError, match='cell'):
        CellDeadline.start(ContinuationStore(tmp_path / 'extra-clock.jsonl'), lifecycle=CellLifecycle(ledger),
                           cell_id='mori-9', plan_ref=ref, seconds=2700)
    with pytest.raises(ValueError, match='duration'):
        CellDeadline.start(ContinuationStore(tmp_path / 'wrong-duration.jsonl'), lifecycle=CellLifecycle(ledger),
                           cell_id='mori-1', plan_ref=ref, seconds=3600)


def test_snapshot_tampering_or_wrong_campaign_is_rejected(tmp_path):
    from zoo.circle_packing.frozen_source import freeze_source_plan, verify_frozen_source
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    with pytest.raises(ValueError, match='campaign'):
        freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'wrong',
                           expected_plan_ref=ref, expected_campaign_id='0' * 32)
    assert ledger.circle_pilot_binding() is None and not (tmp_path / 'wrong').exists()
    result = freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'source',
                                expected_plan_ref=ref, expected_campaign_id=campaign_id)
    (tmp_path / 'source' / 'm0' / 'source.py').write_text('changed')
    with pytest.raises(ValueError):
        verify_frozen_source(ledger, plan, snapshot=tmp_path / 'source', manifest=result['manifest'],
                             expected_plan_ref=ref, expected_campaign_id=campaign_id)


def test_lost_snapshot_rebuilds_from_original_commit_without_refreezing(tmp_path):
    from zoo.circle_packing.clean_source import export_clean_source
    from zoo.circle_packing.frozen_source import freeze_source_plan, verify_frozen_source
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    destination = tmp_path / 'source'
    original = freeze_source_plan(ledger, plan, checkout=root, destination=destination,
                                  expected_plan_ref=ref, expected_campaign_id=campaign_id)
    binding = ledger.circle_pilot_binding()
    shutil.rmtree(destination)
    rebuilt = export_clean_source(ledger, plan, 'vendor-0', checkout=root, destination=destination,
                                  expected_plan_ref=ref)
    assert rebuilt['tree_ref'] == original['tree_ref']
    assert verify_frozen_source(ledger, plan, snapshot=destination, manifest=rebuilt['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id)['tree_ref'] == binding['tree_ref']
    assert ledger.circle_pilot_binding() == binding


def test_freezing_preserves_prior_campaign_spend(tmp_path):
    from zoo.circle_packing.frozen_source import freeze_source_plan
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    ledger.reserve('prior-fixture', 'd' * 64, 10)
    ledger.settle('prior-fixture', {'prompt_tokens': 100, 'completion_tokens': 2, 'total_tokens': 102}, 'e' * 64)
    before = ledger.snapshot()
    freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'source',
                       expected_plan_ref=ref, expected_campaign_id=campaign_id)
    after = ledger.snapshot()
    assert before['settled_upper_bound_micro_cny'] == after['settled_upper_bound_micro_cny'] == 216
    assert before['remaining_micro_cny'] == after['remaining_micro_cny']
    assert before['operations'] == after['operations']


def test_unresolved_prior_call_blocks_freezing(tmp_path):
    from zoo.circle_packing.frozen_source import freeze_source_plan
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    ledger.reserve('pending-fixture', 'd' * 64, 10)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='unresolved'):
        freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'source',
                           expected_plan_ref=ref, expected_campaign_id=campaign_id)
    after = ledger.snapshot()
    assert after['pending_calls'] == before['pending_calls'] == ['pending-fixture']
    assert after['journal_head'] == before['journal_head'] and ledger.circle_pilot_binding() is None


def test_plan_cannot_be_frozen_after_cell_start_or_replaced(tmp_path):
    from zoo.circle_packing.frozen_source import freeze_source_plan
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='vendor-0', plan_ref=ref, seconds=2700)
    with pytest.raises(ValueError, match='pilot'):
        freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'source',
                           expected_plan_ref=ref, expected_campaign_id=campaign_id)


def test_worker_requires_original_anchored_snapshot_before_launch(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    from zoo.circle_packing.frozen_source import freeze_source_plan
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    snapshot = tmp_path / 'snapshot'
    result = freeze_source_plan(ledger, plan, checkout=root, destination=snapshot,
                                expected_plan_ref=ref, expected_campaign_id=campaign_id)
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                  cell_id='vendor-0', plan_ref=ref, seconds=2700)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with pytest.raises(ValueError, match='frozen'):
        run_cell_worker(deadline, tmp_path / 'worker', workspace, ['/bin/true'], readonly_source=snapshot / 'm0')
    assert ledger.cell_worker_claim('vendor-0') is None
    other = tmp_path / 'other-source'
    other.mkdir()
    with pytest.raises(ValueError, match='source'):
        run_cell_worker(deadline, tmp_path / 'worker', workspace, ['/bin/true'], readonly_source=other,
            frozen_plan=plan, snapshot=snapshot, source_manifest=result['manifest'],
            expected_plan_ref=ref, expected_campaign_id=campaign_id)
    assert ledger.cell_worker_claim('vendor-0') is None
    (snapshot / 'm0' / 'source.py').write_text('changed')
    with pytest.raises(ValueError):
        run_cell_worker(deadline, tmp_path / 'worker', workspace, ['/bin/true'], readonly_source=snapshot / 'm0',
            frozen_plan=plan, snapshot=snapshot, source_manifest=result['manifest'],
            expected_plan_ref=ref, expected_campaign_id=campaign_id)
    assert ledger.cell_worker_claim('vendor-0') is None


def test_worker_rejects_source_changed_during_execution(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    from zoo.circle_packing.frozen_source import freeze_source_plan
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    snapshot = tmp_path / 'snapshot'
    result = freeze_source_plan(ledger, plan, checkout=root, destination=snapshot,
                                expected_plan_ref=ref, expected_campaign_id=campaign_id)
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                  cell_id='vendor-0', plan_ref=ref, seconds=2700)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    def mutate():
        end = time.monotonic() + 10
        while not (workspace / 'ready').exists() and time.monotonic() < end:
            time.sleep(.01)
        if (workspace / 'ready').exists():
            (snapshot / 'm0' / 'source.py').write_text('changed')
    thread = threading.Thread(target=mutate)
    thread.start()
    try:
        with pytest.raises(ValueError):
            run_cell_worker(deadline, tmp_path / 'worker', workspace,
                ['/usr/bin/python3', '-c', "import time; open('ready','w').write('ready'); time.sleep(1)"],
                readonly_source=snapshot / 'm0', frozen_plan=plan, snapshot=snapshot,
                source_manifest=result['manifest'], expected_plan_ref=ref, expected_campaign_id=campaign_id)
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive() and ledger.cell_worker_claim('vendor-0') is not None


def test_restore_rejects_clock_record_with_changed_frozen_duration(tmp_path):
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.cell_deadline import _boot_identity, _clock_ns
    from zoo.circle_packing.frozen_source import freeze_source_plan
    root, ledger, plan, ref, campaign_id = fixture(tmp_path)
    freeze_source_plan(ledger, plan, checkout=root, destination=tmp_path / 'snapshot',
                       expected_plan_ref=ref, expected_campaign_id=campaign_id)
    record = {'schema_version': 1, 'cell_id': 'vendor-0', 'plan_ref': ref, 'seconds': 3600,
              'boot_id': _boot_identity(), 'start_ns': _clock_ns()}
    record['record_sha256'] = payload_digest(record)
    # Simulate a low-level claim that misstates the record duration.
    ledger.claim_cell_deadline('vendor-0', ref, record['record_sha256'], seconds=2700)
    clock = ContinuationStore(tmp_path / 'clock.jsonl')
    clock.append('circle_cell_deadline_started', record)
    with pytest.raises(ValueError, match='duration'):
        CellDeadline.restore(ContinuationStore(clock.path), lifecycle=CellLifecycle(ledger),
                             cell_id='vendor-0', plan_ref=ref, seconds=3600)
