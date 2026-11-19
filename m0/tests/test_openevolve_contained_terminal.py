"""Recorded failure/timeout states require the original contained terminal."""
import json

import pytest

from core.composition.recovery import ContinuationStore
from core.x1.checkpoint import payload_digest
from test_governed_cny_bridge import setup
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle, RecordedCellClock
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def evidence(tmp_path, setup, *, returncode, timeout, ref='sha256:' + 'a' * 64, seconds=30):
    ledger, _bridge, run, context, _providers, _calls, _store, _physical = setup
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='mori-0', plan_ref=ref, seconds=seconds)
    root = tmp_path / 'supervisor'
    root.mkdir(mode=0o700)
    config = {'seed': 0, 'ref': ref}
    binding = {'schema_version': 1, 'cell_id': 'mori-0', 'deadline_ref': clock._record['record_sha256'],
               'config_sha256': payload_digest(config), 'directory': str(root),
               'entry': 'zoo.circle_packing.mori_live_worker', 'boot_id': clock._record['boot_id']}
    worker_ref = payload_digest(binding)
    ledger.claim_cell_worker('mori-0', clock._record['record_sha256'], worker_ref)
    ledger.bind_run_deadline(context.currency_run_id, 'mori-0', ref, clock._record['record_sha256'])
    head = ledger.snapshot()['journal_head']
    view = RecordedCurrencyView(ledger.export_governance_evidence(context.currency_run_id,
        run.physical_plan['plan_ref']), expected_run_id=context.currency_run_id, expected_head=head)
    recorded = RecordedCellClock(clock.export_evidence(), view.cell_deadline_claim('mori-0'))
    execution = 'b' * 32
    child = root / 'executor-processes' / execution
    child.mkdir(parents=True)
    paths = {f'{name}_path': str(child / f'{name}.txt') for name in ('stdout', 'stderr')}
    paths['result_path'] = str(child / 'result.json')
    (child / 'stdout.txt').write_text('')
    (child / 'stderr.txt').write_text('')
    (child / 'result.json').write_text(json.dumps({'returncode': returncode, 'timeout': timeout}))
    started = {'execution_id': execution, 'worker_ref': worker_ref, 'containment_required': True,
               'containment_binding': binding, **paths}
    finished = {'execution_id': execution, 'candidate_id': 'fixture-coordinator', 'attempt': 1,
                'returncode': returncode, 'timeout': timeout, 'recovered': False}
    journal = ContinuationStore(root / 'controller.jsonl')
    journal.append('executor_process_started', started)
    journal.append('executor_containment_verified', {'execution_id': execution})
    journal.append('executor_process_finished', finished)
    return config, root, view, recorded, head


@pytest.mark.parametrize(('returncode', 'timeout', 'expected'), [
    (1, False, 'contained_failed'), (-9, True, 'contained_timeout')])
def test_original_contained_failure_or_timeout_is_reported_without_score(tmp_path, setup, returncode, timeout, expected):
    from zoo.circle_packing.supervisor_audit import audit_contained_terminal
    config, root, view, clock, _head = evidence(tmp_path, setup, returncode=returncode, timeout=timeout)
    report = audit_contained_terminal(config, directory=root, view=view, clock=clock)
    assert report['state'] == expected
    assert report['score'] is None and report['performance_claim'] is False


def test_mismatched_terminal_and_wrapper_result_is_rejected(tmp_path, setup):
    from zoo.circle_packing.supervisor_audit import audit_contained_terminal
    config, root, view, clock, _head = evidence(tmp_path, setup, returncode=-9, timeout=True)
    result = root / 'executor-processes' / ('b' * 32) / 'result.json'
    result.write_text(json.dumps({'returncode': 1, 'timeout': False}))
    with pytest.raises(ValueError, match='terminal'):
        audit_contained_terminal(config, directory=root, view=view, clock=clock)


def test_success_terminal_has_no_score_until_separate_geometry_audit(tmp_path, setup):
    from zoo.circle_packing.supervisor_audit import audit_contained_terminal, audit_supervisor_result
    config, root, view, clock, _head = evidence(tmp_path, setup, returncode=0, timeout=False)
    output = root / 'executor-processes' / ('b' * 32) / 'stdout.txt'
    output.write_text(json.dumps({'performance_claim': False, 'candidate': 'original'}))
    terminal = audit_contained_terminal(config, directory=root, view=view, clock=clock)
    assert terminal['state'] == 'contained_completed' and terminal['score'] is None
    assert audit_supervisor_result(config, directory=root, view=view, clock=clock)['candidate'] == 'original'


@pytest.mark.parametrize('change', ['missing_containment', 'recovered', 'wrong_worker'])
def test_terminal_without_original_unique_containment_remains_unverified(tmp_path, setup, change):
    from zoo.circle_packing.supervisor_audit import audit_contained_terminal
    config, root, view, clock, _head = evidence(tmp_path, setup, returncode=-9, timeout=True)
    path = root / 'controller.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if change == 'missing_containment':
        rows = [row for row in rows if row['kind'] != 'executor_containment_verified']
    elif change == 'recovered':
        rows[-1]['payload']['recovered'] = True
    else:
        rows[0]['payload']['worker_ref'] = 'd' * 64
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError):
        audit_contained_terminal(config, directory=root, view=view, clock=clock)
