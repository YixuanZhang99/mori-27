"""Read supervised terminals against their recorded campaign claims.

This checks the trusted supervisor's records, not an independently observed OS
history. It does not certify a complete run, provider invoice, or benchmark.
"""
import json
from pathlib import Path

from core.composition.recovery import ContinuationStore
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.host_runtime import _read_verified_worker_result
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def _contained_process(config, *, directory, view, clock):
    """Bind an original contained terminal to its pinned run and cell."""
    if type(config) is not dict or type(view) is not RecordedCurrencyView or not view._pinned_head or \
            type(clock) is not RecordedCellClock:
        raise ValueError('supervisor audit requires a pinned campaign and recorded clock')
    try:
        cell = clock._record['cell_id']
        arm, seed = cell.split('-')
        if arm not in ('mori', 'vendor') or seed not in ('0', '1', '2') or \
                type(config['seed']) is not int or config['seed'] != int(seed) or \
                config['ref'] != clock._record['plan_ref']:
            raise ValueError('supervisor configuration differs from its cell')
        claim = view.cell_deadline_claim(cell)
        RecordedCellClock(clock._evidence, claim)
        run_id = json.loads(view._evidence)['run_id']
        binding = view.run_deadline_binding(run_id)
        if binding != {'cell_id': cell, 'plan_ref': config['ref'],
                       'deadline_ref': clock._record['record_sha256']}:
            raise ValueError('supervisor audit differs from its currency run')
        authority = view.cell_worker_claim(cell) if arm == 'mori' else view.reference_host_claim(cell)
        root = Path(directory)
        if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
            raise ValueError('supervisor audit requires its original directory')
        rows = list(ContinuationStore(root / 'controller.jsonl').read())
        starts = [row for row in rows if row['kind'] == 'executor_process_started']
        proofs = [row for row in rows if row['kind'] == 'executor_containment_verified']
        terminals = [row for row in rows if row['kind'] == 'executor_process_finished']
        if len(starts) != 1 or len(proofs) != 1 or len(terminals) != 1 or \
                not rows.index(starts[0]) < rows.index(proofs[0]) < rows.index(terminals[0]):
            raise ValueError('supervisor lacks a unique contained terminal')
        started, proof, terminal = starts[0]['payload'], proofs[0]['payload'], terminals[0]['payload']
        process_binding = started['containment_binding']
        entry = 'zoo.circle_packing.mori_live_worker' if arm == 'mori' else 'zoo.circle_packing.reference_live_worker'
        ref_name = 'worker_ref' if arm == 'mori' else 'host_ref'
        if authority is None or authority['deadline_ref'] != clock._record['record_sha256'] or \
                authority[ref_name] != payload_digest(process_binding) or \
                started.get('worker_ref') != authority[ref_name] or started.get('containment_required') is not True or \
                any(process_binding.get(key) != value for key, value in {
                    'schema_version': 1, 'cell_id': cell, 'deadline_ref': clock._record['record_sha256'],
                    'config_sha256': payload_digest(config), 'directory': str(root), 'entry': entry,
                    'boot_id': clock._record['boot_id']}.items()):
            raise ValueError('supervisor process differs from its campaign claim')
        execution = started['execution_id']
        if type(terminal) is not dict or set(terminal) != {'execution_id', 'candidate_id', 'attempt',
                'returncode', 'timeout', 'recovered'} or proof != {'execution_id': execution} or \
                terminal['execution_id'] != execution or terminal['candidate_id'] != 'fixture-coordinator' or \
                type(terminal['attempt']) is not int or terminal['attempt'] != 1 or \
                type(terminal['returncode']) is not int or type(terminal['timeout']) is not bool or \
                terminal['recovered'] is not False:
            raise ValueError('supervisor process lacks its matching contained terminal')
        result = _read_verified_worker_result(root, started)
        if result['returncode'] != terminal['returncode'] or result['timeout'] != terminal['timeout'] or \
                result['timeout'] and result['wrapper_error']:
            raise ValueError('supervisor wrapper result differs from its terminal')
        return result
    except (KeyError, TypeError, AttributeError, OSError, json.JSONDecodeError) as error:
        raise ValueError('invalid supervised process evidence') from error


def audit_contained_terminal(config, *, directory, view, clock):
    """Classify a verified terminal without claiming a score or full run."""
    result = _contained_process(config, directory=directory, view=view, clock=clock)
    if result['timeout']:
        state = 'contained_timeout'
    elif result['returncode'] != 0 or result['wrapper_error']:
        state = 'contained_failed'
    else:
        state = 'contained_completed'
    return {'schema_version': 1, 'scope': 'recorded_contained_terminal',
            'state': state, 'returncode': result['returncode'], 'score': None,
            'performance_claim': False}


def audit_supervisor_result(config, *, directory, view, clock):
    """Return only the original successful report tied to a pinned claim."""
    result = _contained_process(config, directory=directory, view=view, clock=clock)
    if result['returncode'] != 0 or result['timeout'] or result['wrapper_error']:
        raise ValueError('supervisor result is not successful')
    try:
        def unique(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError('duplicate supervisor report field')
                out[key] = value
            return out
        report = json.loads(result['stdout'], object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if type(report) is not dict or report.get('performance_claim') is not False:
            raise ValueError('supervisor report has an invalid scope')
        return report
    except (KeyError, TypeError, AttributeError, OSError, json.JSONDecodeError) as error:
        raise ValueError('invalid supervised process evidence') from error
