"""A continuation's fixture clocks never replace original campaign identities."""
import pytest

pytestmark = pytest.mark.linux

from core.composition.recovery import ContinuationStore
from test_openevolve_continuation_binding import prepared, bind
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle, RecordedCellClock


def test_versioned_fixture_pair_preserves_original_clocks_and_one_worker(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, proof, _before, draft, *_ = values
    bind(values)
    start = ledger.snapshot()
    ref = 'sha256:' + draft['draft_sha256']
    lifecycle = CellLifecycle(ledger)
    names = ['circle-v2--mori-0', 'circle-v2--vendor-0']
    clocks = [CellDeadline.start(ContinuationStore(tmp_path / f'clock-{arm}.jsonl'), lifecycle=lifecycle,
              cell_id=name, plan_ref=ref, seconds=2700) for arm, name in zip(('mori', 'vendor'), names)]
    assert set(ledger.circle_claim_inventory(expected_head=ledger.snapshot()['journal_head'])['claims']) == {
        'mori-0', 'vendor-0', *names}
    from zoo.circle_packing.pilot_matrix import snapshot_matrix
    from zoo.circle_packing.pilot_plan import build_draft_plan
    original_plan = build_draft_plan(ledger.manifest_binding(), source_commit='6' * 40, dependency_lock_sha256='7' * 64)
    original_ref = 'sha256:' + original_plan['draft_sha256']
    original = snapshot_matrix(ledger, original_plan, expected_plan_ref=original_ref, expected_head=ledger.snapshot()['journal_head'])
    assert len(original['cells']) == 6 and {item['cell_id'] for item in original['cells'] if item['state'] != 'not_claimed'} == {'mori-0', 'vendor-0'}
    for arm, name, clock in zip(('mori', 'vendor'), names, clocks):
        restored = CellDeadline.restore(ContinuationStore(tmp_path / f'clock-{arm}.jsonl'), lifecycle=lifecycle,
                                        cell_id=name, plan_ref=ref, seconds=2700)
        assert restored._record == clock._record
        recorded = RecordedCellClock(clock.export_evidence(), ledger.cell_deadline_claim(name))
        assert recorded._record == clock._record
        with pytest.raises(ValueError):
            CellDeadline.start(ContinuationStore(tmp_path / f'other-{arm}.jsonl'), lifecycle=lifecycle,
                               cell_id=name, plan_ref=ref, seconds=2700)
    import copy
    updated_proof = copy.deepcopy(proof)
    head = ledger.snapshot()['journal_head']
    updated_proof['result']['journal_head'] = head
    ledger._record_first_pair_audit(updated_proof, expected_head=head)
    assert ledger.first_pair_audit() == updated_proof
    proof = updated_proof
    mori, vendor = clocks
    mc, vc = mori._record['record_sha256'], vendor._record['record_sha256']
    obligation = [{'slot_id': 'control-new', 'phase': 'operator', 'ordinal': 0, 'bound': ledger.quote_call(64)}]
    ledger.protect_run('0' * 64, ref, obligation)
    with pytest.raises(ValueError): ledger.bind_run_deadline('0' * 64, names[0], ref, mc)
    ledger.claim_cell_worker(names[0], mc, 'a' * 64)
    with pytest.raises(ValueError): ledger.claim_cell_worker(names[0], mc, 'a' * 64)
    ledger.claim_reference_host(names[1], vc, 'b' * 64)
    with pytest.raises(ValueError, match='unstarted'):
        CellDeadline.restore(ContinuationStore(tmp_path / 'clock-vendor.jsonl'), lifecycle=lifecycle,
                             cell_id=names[1], plan_ref=ref, seconds=2700, reconcile_unstarted=True)
    ledger.claim_reference_authority(names[1], vc, 'c' * 64, 'd' * 64, 'sha256:' + 'e' * 64)
    ledger.claim_cell_worker(names[1], vc, 'f' * 64)
    ledger.bind_run_deadline('0' * 64, names[0], ref, mc)
    with pytest.raises(ValueError): ledger.bind_run_deadline('0' * 64, names[0], ref, mc + 'x')
    ledger.cancel_control('0' * 64, 'control-new', reason='fixture only')
    assert ledger.first_pair_audit() == proof
    assert ledger.snapshot()['remaining_micro_cny'] == start['remaining_micro_cny']


@pytest.mark.parametrize('name,ref_kind,seconds', [
    ('circle-v2--mori-1', 'correct', 2700), ('circle-v2--vendor-2', 'correct', 2700),
    ('other--mori-0', 'correct', 2700), ('circle-v2--mori-0', 'wrong', 2700),
    ('circle-v2--vendor-0', 'correct', 1), ('circle-v2--mori-3', 'correct', 2700),
])
def test_versioned_fixture_clock_rejects_unadmitted_cell_or_changed_limits(tmp_path, monkeypatch, name, ref_kind, seconds):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, _before, draft, *_ = values
    bind(values)
    before = ledger.snapshot()
    ref = 'sha256:' + (draft['draft_sha256'] if ref_kind == 'correct' else '0' * 64)
    with pytest.raises(ValueError):
        ledger.claim_cell_deadline(name, ref, 'a' * 64, seconds=seconds)
    assert ledger.snapshot() == before


def test_denied_later_seed_does_not_create_a_clock_journal(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, _before, draft, *_ = values
    bind(values)
    before = ledger.snapshot()
    path = tmp_path / 'later-seed-clock.jsonl'
    with pytest.raises(ValueError):
        CellDeadline.start(ContinuationStore(path), lifecycle=CellLifecycle(ledger),
            cell_id='circle-v2--mori-1', plan_ref='sha256:' + draft['draft_sha256'], seconds=2700)
    assert not path.exists() and ledger.snapshot() == before


def test_unresolved_currency_blocks_new_clock_before_creating_file(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, _proof, _before, draft, *_ = values
    bind(values)
    ledger.reserve('unknown-provider', 'a' * 64, 64)
    before = ledger.snapshot()
    path = tmp_path / 'blocked-clock.jsonl'
    with pytest.raises(ValueError):
        CellDeadline.start(ContinuationStore(path), lifecycle=CellLifecycle(ledger),
            cell_id='circle-v2--mori-0', plan_ref='sha256:' + draft['draft_sha256'], seconds=2700)
    assert not path.exists() and ledger.snapshot() == before
