"""A versioned cell's charge summary must come from its own pinned proof."""
import copy
import json
import pytest

from core.composition.recovery import ContinuationStore
from test_openevolve_continuation_binding import prepared, bind
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle, RecordedCellClock
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView

pytestmark = pytest.mark.linux


def setup(tmp_path, monkeypatch):
    values = prepared(tmp_path, monkeypatch)
    ledger, _, _, draft, *_ = values
    bind(values)
    ref = 'sha256:' + draft['draft_sha256']
    lifecycle = CellLifecycle(ledger)
    names = ('circle-v2--mori-0', 'circle-v2--vendor-0')
    clocks = [CellDeadline.start(ContinuationStore(tmp_path / f'clock-{arm}.jsonl'), lifecycle=lifecycle,
        cell_id=name, plan_ref=ref, seconds=2700) for arm, name in zip(('mori', 'vendor'), names)]
    ledger.claim_cell_worker(names[0], clocks[0]._record['record_sha256'], 'a' * 64)
    runs = ('3' * 64, '4' * 64)
    physical = ('sha256:' + 'b' * 64, 'sha256:' + 'c' * 64)
    for run, plan_ref, name, clock in zip(runs, physical, names, clocks):
        obligations = [{'slot_id': 'control-new', 'phase': 'operator', 'ordinal': 0, 'bound': ledger.quote_call(64)}]
        ledger.protect_run(run, plan_ref, obligations)
        ledger.bind_run_deadline(run, name, ref, clock._record['record_sha256'])
        ledger.cancel_control(run, 'control-new', reason='fixture did not call provider')
    head = ledger.snapshot()['journal_head']
    evidence = {}
    for run, plan_ref, name, clock in zip(runs, physical, names, clocks):
        view = RecordedCurrencyView(ledger.export_governance_evidence(run, plan_ref), expected_run_id=run,
                                    expected_plan_ref=plan_ref, expected_head=head)
        evidence[name] = {'view': view, 'clock': RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim(name))}
    return ledger, draft, ref, head, evidence


def test_currency_report_uses_separate_recorded_run_and_clock(tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_matrix import report_continuation_currency
    ledger, draft, ref, head, evidence = setup(tmp_path, monkeypatch)
    before = ledger.snapshot()
    report = report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head, cell_evidence=evidence)
    by_name = {cell['cell_id']: cell for cell in report['cells']}
    assert len(by_name) == 6 and report['performance_claim'] is False
    for name in evidence:
        assert by_name[name]['state'] == 'claimed_outcome_unverified'
        assert by_name[name]['currency']['settled_upper_bound_micro_cny'] == 0
        assert by_name[name]['currency']['invoice_verified'] is False
    assert all(cell['currency'] is None for name, cell in by_name.items() if name not in evidence)
    assert all(cell['score'] is None for cell in report['cells']) and ledger.snapshot() == before


def test_currency_report_rejects_cross_cell_stale_and_unpinned_proofs(tmp_path, monkeypatch):
    from zoo.circle_packing.pilot_matrix import report_continuation_currency
    ledger, draft, ref, head, evidence = setup(tmp_path, monkeypatch)
    before = ledger.snapshot()
    names = list(evidence)
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head,
                                    cell_evidence={names[0]: evidence[names[1]]})
    raw = ledger.export_governance_evidence('3' * 64, 'sha256:' + 'b' * 64)
    unpinned = RecordedCurrencyView(raw)
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head,
            cell_evidence={names[0]: {'view': unpinned, 'clock': evidence[names[0]]['clock']}})
    forged_view = copy.deepcopy(evidence[names[0]]['view'])
    forged_audit = json.loads(forged_view._audit)
    forged_audit['settled_upper_bound_micro_cny'] = 123
    forged_view._audit = json.dumps(forged_audit)
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head,
            cell_evidence={names[0]: {'view': forged_view, 'clock': evidence[names[0]]['clock']}})
    damaged_clock = copy.deepcopy(evidence[names[0]]['clock'])
    damaged_clock._evidence['record']['start_ns'] += 1
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head,
            cell_evidence={names[0]: {'view': evidence[names[0]]['view'], 'clock': damaged_clock}})
    other_dir = tmp_path / 'foreign'
    other_dir.mkdir(mode=0o700)
    monkeypatch.undo()  # The fixture installer patches subprocess.run globally.
    _, _, _, _, foreign_evidence = setup(other_dir, monkeypatch)
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head,
                                    cell_evidence={names[0]: foreign_evidence[names[0]]})
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref,
                                    expected_head=dict(head, sha256='0' * 64), cell_evidence=evidence)
    with pytest.raises(ValueError):
        report_continuation_currency(ledger, draft, expected_plan_ref=ref, expected_head=head,
                                    cell_evidence={'circle-v2--mori-1': evidence[names[0]]})
    assert ledger.snapshot() == before
