"""The cell clock is durable and cannot be reset by a restart."""
from unittest.mock import patch

import pytest

from core.composition.recovery import ContinuationStore


def _lifecycle(path):
    from zoo.circle_packing.cell_deadline import CellLifecycle
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger_path = path.parent / 'campaign.db'
    if not ledger_path.exists():
        ledger = CampaignBudget.create(ledger_path)
        ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                                 expected_head=ledger.snapshot()['journal_head'])
    return CellLifecycle(CampaignBudget(ledger_path))


def test_deadline_survives_restart_without_extending(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline, DeadlineExpired
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'a' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100_000_000_000, 101_000_000_000, 102_000_000_000,
                                                                            103_000_000_000, 105_000_000_000]):
        first = CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-0', plan_ref=plan, seconds=5)
        assert first.remaining() == pytest.approx(4)
        restored = CellDeadline.restore(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-0', plan_ref=plan, seconds=5)
        assert restored.remaining() == pytest.approx(2)
        with pytest.raises(DeadlineExpired):
            restored.check()


def test_deadline_rejects_restart_after_reboot_or_clock_regression(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'b' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-b'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=101):
        with pytest.raises(ValueError, match='boot'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=99):
        with pytest.raises(ValueError, match='clock'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)


def test_duplicate_start_or_changed_plan_is_rejected(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'c' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='exist'):
            CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='differ'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-0', plan_ref=plan, seconds=6)


def test_live_clock_regression_is_rejected(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'd' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 105, 104]):
        authority = CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-0', plan_ref=plan, seconds=5)
        authority.remaining()
        with pytest.raises(ValueError, match='clock'):
            authority.remaining()


def test_concurrent_starts_create_only_one_authority(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'e' * 64
    lifecycle = _lifecycle(path)
    def attempt():
        try:
            CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-1', plan_ref=plan, seconds=10)
            return 'started'
        except ValueError:
            return 'rejected'
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100), \
            ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ['rejected', 'started']
    assert len(list(ContinuationStore(path).read('circle_cell_deadline_started'))) == 1


def test_changed_or_duplicate_deadline_records_are_rejected(tmp_path):
    from core.x1.store import AppendOnlyStore
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'f' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        authority = CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-2', plan_ref=plan, seconds=10)
        original = list(AppendOnlyStore(path).read('circle_cell_deadline_started'))[0]['payload']
        AppendOnlyStore(path).append('circle_cell_deadline_started', original)
        with pytest.raises(ValueError, match='differ'):
            authority.check()
        with pytest.raises(ValueError, match='duplicated'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='vendor-2', plan_ref=plan, seconds=10)


def test_missing_deadline_cannot_be_created_after_prior_work(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    store = ContinuationStore(path)
    store.append('governed_control_started', {'slot_id': 'control-0000'})
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        with pytest.raises(ValueError, match='prior'):
            CellDeadline.start(store, lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref='sha256:' + 'a' * 64, seconds=5)


def test_restored_clock_cannot_move_before_last_durable_observation(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    plan = 'sha256:' + 'a' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 105, 102]):
        authority = CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)
        authority.remaining()
        with pytest.raises(ValueError, match='clock'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)


def test_deadline_rejects_symlink_or_hardlinked_journal(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    target = tmp_path / 'real.jsonl'
    target.touch()
    link = tmp_path / 'alias.jsonl'
    link.symlink_to(target)
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        with pytest.raises(ValueError, match='link'):
            CellDeadline.start(ContinuationStore(link), lifecycle=_lifecycle(link), cell_id='vendor-0', plan_ref='sha256:' + 'a' * 64, seconds=5)
        link.unlink()
        link.hardlink_to(target)
        with pytest.raises(ValueError, match='link'):
            CellDeadline.start(ContinuationStore(target), lifecycle=_lifecycle(target), cell_id='vendor-0', plan_ref='sha256:' + 'a' * 64, seconds=5)


def test_direct_construction_rejects_forged_record(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    store = ContinuationStore(tmp_path / 'cell.jsonl')
    forged = {'schema_version': 1, 'cell_id': 'invalid', 'plan_ref': 'bad', 'seconds': 999999,
              'boot_id': 'boot-a', 'start_ns': 1, 'record_sha256': 'invalid'}
    with pytest.raises(ValueError):
        CellDeadline(store, forged, lifecycle=_lifecycle(store.path))


def test_deadline_rejects_shared_framework_replay_cursor(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'events.jsonl'
    plan = 'sha256:' + 'b' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        CellDeadline.start(ContinuationStore(path), lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)
        framework = ContinuationStore(path)
        framework.append('composed_checkpoint', {'sha256': 'fixture'})
        framework.restoring = True
        with pytest.raises(ValueError, match='dedicated'):
            CellDeadline.restore(framework, lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)
        fresh = ContinuationStore(path)
        with pytest.raises(ValueError, match='dedicated'):
            CellDeadline.restore(fresh, lifecycle=_lifecycle(path), cell_id='mori-0', plan_ref=plan, seconds=5)


def test_lifecycle_claim_prevents_reset_after_clock_journal_loss(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    path = tmp_path / 'cell.jsonl'
    lifecycle = _lifecycle(path)
    plan = 'sha256:' + 'c' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)
        path.unlink()
        with pytest.raises(ValueError, match='claim'):
            CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='missing'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)


def test_claim_survives_crash_before_first_deadline_write(tmp_path, monkeypatch):
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    path = tmp_path / 'cell.jsonl'
    lifecycle = _lifecycle(path)
    store = ContinuationStore(path)
    original = ContinuationStore.append
    def crash(self, kind, payload):
        if kind == 'circle_cell_deadline_started':
            raise SystemExit('crash after claim')
        return original(self, kind, payload)
    monkeypatch.setattr(ContinuationStore, 'append', crash)
    plan = 'sha256:' + 'd' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        with pytest.raises(SystemExit):
            CellDeadline.start(store, lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='claim'):
            CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='missing'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)


def test_changed_campaign_cannot_restore_or_continue(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    path = tmp_path / 'cell.jsonl'
    lifecycle = _lifecycle(path)
    other_path = tmp_path / 'other.db'
    other = CampaignBudget.create(other_path)
    other.enable_governance(expected_policy_sha256=other.manifest_binding()['policy_sha256'],
                            expected_head=other.snapshot()['journal_head'])
    foreign = CellLifecycle(other)
    plan = 'sha256:' + 'e' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='vendor-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='claim'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=foreign, cell_id='vendor-0', plan_ref=plan, seconds=5)


def test_two_live_deadline_instances_share_durable_observations(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    lifecycle = _lifecycle(path)
    plan = 'sha256:' + 'f' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 101, 102, 103]):
        first = CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='vendor-0', plan_ref=plan, seconds=5)
        second = CellDeadline.restore(ContinuationStore(path), lifecycle=lifecycle, cell_id='vendor-0', plan_ref=plan, seconds=5)
        assert first.remaining() > 0
        assert second.remaining() > 0


def test_original_campaign_rejects_same_cell_from_another_journal(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path, other = tmp_path / 'cell.jsonl', tmp_path / 'other-cell.jsonl'
    lifecycle = _lifecycle(path)
    plan = 'sha256:' + 'f' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', return_value=100):
        CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle, cell_id='vendor-0', plan_ref=plan, seconds=5)
        with pytest.raises(ValueError, match='claim'):
            CellDeadline.start(ContinuationStore(other), lifecycle=lifecycle, cell_id='vendor-0', plan_ref=plan, seconds=5)


def test_deadline_rejects_truncated_observation_tail(tmp_path):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    lifecycle = _lifecycle(path)
    plan = 'sha256:' + 'e' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 105, 106]):
        deadline = CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle,
                                      cell_id='mori-0', plan_ref=plan, seconds=5)
        deadline.remaining()
        lines = path.read_text().splitlines(keepends=True)
        path.write_text(lines[0])
        with pytest.raises(ValueError, match='head'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)


def test_crash_after_observation_before_campaign_anchor_fails_closed(tmp_path, monkeypatch):
    from zoo.circle_packing.cell_deadline import CellDeadline
    path = tmp_path / 'cell.jsonl'
    lifecycle = _lifecycle(path)
    plan = 'sha256:' + 'e' * 64
    with patch('zoo.circle_packing.cell_deadline._boot_identity', return_value='boot-a'), \
            patch('zoo.circle_packing.cell_deadline._clock_ns', side_effect=[100, 101, 102]):
        deadline = CellDeadline.start(ContinuationStore(path), lifecycle=lifecycle,
                                      cell_id='mori-0', plan_ref=plan, seconds=5)
        def crash(*args):
            raise SystemExit('crash after journal observation')
        monkeypatch.setattr(lifecycle.ledger, 'anchor_cell_deadline_observation', crash)
        with pytest.raises(SystemExit):
            deadline.remaining()
        with pytest.raises(ValueError, match='head'):
            CellDeadline.restore(ContinuationStore(path), lifecycle=lifecycle, cell_id='mori-0', plan_ref=plan, seconds=5)
