"""The six-cell report retains unknown outcomes and pinned costs."""
import copy

import pytest

from test_governed_cny_bridge import setup
from test_openevolve_contained_terminal import evidence
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.pilot_plan import build_draft_plan


def prepared(tmp_path, setup, *, returncode=-9, timeout=True, single_run=True):
    ledger = setup[0]
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    ledger.freeze_circle_pilot(ref, 'sha256:' + 'c' * 64, plan['limits']['wallclock_seconds'],
                               require_single_run=single_run)
    config, root, view, clock, head = evidence(tmp_path, setup, returncode=returncode,
        timeout=timeout, ref=ref, seconds=plan['limits']['wallclock_seconds'])
    item = {'config': config, 'directory': root, 'view': view, 'clock': clock}
    return ledger, plan, ref, head, item


def test_six_cells_keep_unrun_unknown_cost_and_verified_timeout(tmp_path, setup):
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, head, item = prepared(tmp_path, setup)
    before = ledger.snapshot()
    report = report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head,
                           cell_evidence={'mori-0': item})
    assert len(report['cells']) == 6 and len(report['pairs']) == 3
    cells = {cell['cell_id']: cell for cell in report['cells']}
    assert cells['mori-0']['state'] == 'contained_timeout'
    assert cells['mori-0']['score'] is None
    assert cells['mori-0']['currency']['settled_upper_bound_micro_cny'] == 0
    assert cells['mori-0']['currency']['outstanding_micro_cny'] > 0
    assert cells['mori-0']['currency']['breaches_scope'] == 'campaign'
    assert cells['vendor-0']['state'] == 'not_claimed_at_head'
    assert cells['vendor-0']['score'] is None and cells['vendor-0']['currency'] is None
    assert all(pair['difference'] is None for pair in report['pairs'])
    assert [pair['state'] for pair in report['pairs']] == ['incomplete', 'not_claimed_at_head', 'not_claimed_at_head']
    assert report['performance_claim'] is False and ledger.snapshot() == before


def test_omitted_evidence_does_not_invent_failure_or_zero_cost(tmp_path, setup):
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, head, _item = prepared(tmp_path, setup)
    report = report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head)
    cell = next(value for value in report['cells'] if value['cell_id'] == 'mori-0')
    assert cell['state'] == 'claimed_unresolved' and cell['score'] is None and cell['currency'] is None


def test_report_rejects_caller_supplied_score_and_uses_exact_head(tmp_path, setup):
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, head, item = prepared(tmp_path, setup)
    with pytest.raises(ValueError):
        report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head,
                      cell_evidence={'mori-0': {**item, 'score': 9.9}})
    altered = copy.deepcopy(head)
    altered['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=altered,
                      cell_evidence={'mori-0': item})


def test_recorded_currency_can_be_known_while_terminal_remains_unresolved(tmp_path, setup):
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, head, item = prepared(tmp_path, setup)
    report = report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head,
                           cell_evidence={'mori-0': {**item, 'directory': None}})
    cell = next(value for value in report['cells'] if value['cell_id'] == 'mori-0')
    assert cell['state'] == 'claimed_unresolved' and cell['score'] is None
    assert cell['currency']['outstanding_micro_cny'] > 0


def test_report_rejects_valid_currency_prefix_at_a_newer_head(tmp_path, setup):
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, _head, item = prepared(tmp_path, setup)
    CellDeadline.start(ContinuationStore(tmp_path / 'vendor-clock.jsonl'), lifecycle=CellLifecycle(ledger),
                       cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    newer = ledger.snapshot()['journal_head']
    with pytest.raises(ValueError, match='head'):
        report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=newer,
                      cell_evidence={'mori-0': item})


def test_report_does_not_accept_conflicting_terminal_files(tmp_path, setup):
    import json
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, head, item = prepared(tmp_path, setup)
    result = item['directory'] / 'executor-processes' / ('b' * 32) / 'result.json'
    result.write_text(json.dumps({'returncode': 1, 'timeout': False}))
    with pytest.raises(ValueError, match='terminal'):
        report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head,
                      cell_evidence={'mori-0': item})


def test_pair_score_cannot_be_injected_as_caller_data(tmp_path, setup):
    from zoo.circle_packing.pilot_matrix import report_matrix
    ledger, plan, ref, head, item = prepared(tmp_path, setup)
    with pytest.raises(ValueError):
        report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head,
                      cell_evidence={'mori-0': item}, pair_evidence={0: {'score': 9.9}})


def test_legacy_multi_run_cell_cannot_report_one_run_as_its_total(tmp_path, setup):
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.pilot_matrix import report_matrix
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    ledger, plan, ref, _head, item = prepared(tmp_path, setup, single_run=False)
    other = 'f' * 64
    physical_ref = setup[2].physical_plan['plan_ref']
    ledger.protect_run(other, physical_ref, setup[1]._preparation['obligations'])
    ledger.bind_run_deadline(other, 'mori-0', ref, item['clock']._record['record_sha256'])
    head = ledger.snapshot()['journal_head']
    view = RecordedCurrencyView(ledger.export_governance_evidence(other, physical_ref),
                                expected_run_id=other, expected_head=head)
    item = {**item, 'view': view,
            'clock': RecordedCellClock(item['clock']._evidence, view.cell_deadline_claim('mori-0'))}
    with pytest.raises(ValueError, match='single.run'):
        report_matrix(ledger, plan, expected_plan_ref=ref, expected_head=head,
                      cell_evidence={'mori-0': item})


@pytest.mark.parametrize('protected', ['frozen_source', 'frozen_bundle', 'vendor_workspace', 'mori_cell', 'vendor_supervisor'])
def test_pair_replay_cannot_write_into_original_evidence_or_frozen_source(tmp_path, protected):
    from zoo.circle_packing.pilot_matrix import _validate_replay_output
    source = tmp_path / 'bundle' / 'source'
    (source / 'm0').mkdir(parents=True)
    (source / 'assets').mkdir()
    (source.parent / 'metadata').mkdir()
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    private = tmp_path / 'private'
    private.mkdir()
    ledger = private / 'campaign.db'
    ledger.write_text('fixture')
    mori_cell, vendor_cell = tmp_path / 'mori', tmp_path / 'vendor'
    mori_cell.mkdir()
    vendor_cell.mkdir()
    mori_supervisor, vendor_supervisor = mori_cell / 'supervisor', vendor_cell / 'supervisor'
    mori_supervisor.mkdir()
    vendor_supervisor.mkdir()
    workspace = vendor_cell / 'workspace'
    workspace.mkdir()
    mori = {'source': str(source / 'm0'), 'runtime': str(runtime), 'clock': str(mori_cell / 'clock'),
            'output': str(mori_cell / 'output')}
    vendor = {'clock': str(vendor_cell / 'clock'), 'output': str(vendor_cell / 'output'),
              'workspace': str(workspace), 'worker_directory': str(vendor_cell / 'worker')}
    destinations = {'frozen_source': source / 'assets' / 'replay',
                    'frozen_bundle': source.parent / 'metadata' / 'replay',
                    'vendor_workspace': workspace / 'replay', 'mori_cell': mori_cell / 'replay',
                    'vendor_supervisor': vendor_supervisor / 'replay'}
    with pytest.raises(ValueError, match='overlap'):
        _validate_replay_output(destinations[protected], mori=mori, vendor=vendor,
                                mori_directory=mori_supervisor, vendor_directory=vendor_supervisor,
                                ledger_path=ledger)
    assert not destinations[protected].exists()
