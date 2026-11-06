"""Read the pinned upstream controller's saved winner after it has exited.

These checks bind its report to its saved files; they do not authenticate the
worker's selection or prevent a same-user writer from changing the workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from core.x1.checkpoint import payload_digest


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate reference artifact field')
        value[key] = item
    return value


def _read_file(directory, name, limit):
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(name, flags, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError('reference artifact must be a bounded single-link regular file')
        parts, remaining = [], limit + 1
        while remaining:
            part = os.read(fd, remaining)
            if not part:
                break
            parts.append(part)
            remaining -= len(part)
        data = b''.join(parts)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('reference artifact changed during reading')
        return data
    finally:
        os.close(fd)


def read_reference_selection(workspace, selected):
    """Check the worker report against bounded, no-follow upstream files."""
    if type(selected) is not dict or set(selected) != {'id', 'program_ref', 'metrics'} or \
            type(selected['id']) is not str or not selected['id'] or type(selected['metrics']) is not dict:
        raise ValueError('invalid reference selection')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directories = []
    try:
        directory = os.open(Path(workspace), flags)
        directories.append(directory)
        for name in ('host-run', 'host', 'best'):
            directory = os.open(name, flags, dir_fd=directory)
            directories.append(directory)
        source = _read_file(directory, 'best_program.py', 1024 * 1024)
        info = json.loads(_read_file(directory, 'best_program_info.json', 65536).decode('utf-8'),
                          object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        program = source.decode('utf-8')
        if not program.strip() or type(info) is not dict or info.get('id') != selected['id'] or \
                json.dumps(info.get('metrics'), sort_keys=True, allow_nan=False) != \
                json.dumps(selected['metrics'], sort_keys=True, allow_nan=False) or \
                selected['program_ref'] != 'sha256:' + hashlib.sha256(source).hexdigest():
            raise ValueError('reference report differs from saved program or metadata')
        return {'saved_program_ref': selected['program_ref']}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, RecursionError) as error:
        raise ValueError('reference artifact cannot be safely read') from error
    finally:
        for fd in reversed(directories):
            os.close(fd)


def _audit_reference_stage(view, clock, run_id, start, terminal, proof, *, require_success, require_eligible):
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.host_physical import _validate_stage_result
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    if type(view) is not RecordedCurrencyView or type(clock) is not RecordedCellClock or \
            type(start) is not dict or set(start) != {'request_id', 'stage', 'prior_id', 'program_ref',
                                                     'intent_id', 'fingerprint'} or \
            type(terminal) is not dict or set(terminal) != {'request_id', 'fingerprint', 'result',
                                                            'result_ref', 'evidence_ref'} or \
            type(proof) is not dict or set(proof) != {'request_id', 'intent_id', 'fingerprint',
                                                     'evidence_ref', 'observation'}:
        raise ValueError('invalid recorded reference stage')
    if not view._pinned_head:
        raise ValueError('recorded reference stage requires an independently pinned campaign head')
    request_id = start['request_id']
    if type(request_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', request_id) or \
            type(start['stage']) is not int or start['stage'] not in (1, 2) or \
            type(start['program_ref']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', start['program_ref']) or \
            type(start['fingerprint']) is not str or not start['fingerprint'] or \
            (start['stage'] == 1 and start['prior_id'] is not None) or \
            (start['stage'] == 2 and (type(start['prior_id']) is not str or
                                      not re.fullmatch(r'[0-9a-f]{32}', start['prior_id']))) or \
            start['intent_id'] != 'host-stage:' + request_id or \
            terminal['request_id'] != request_id or proof['request_id'] != request_id or \
            terminal['fingerprint'] != start['fingerprint'] or proof['fingerprint'] != start['fingerprint'] or \
            proof['intent_id'] != start['intent_id'] or proof['evidence_ref'] != terminal['evidence_ref']:
        raise ValueError('recorded reference stage identity differs')
    result = terminal['result']
    if terminal['result_ref'] != 'sha256:' + payload_digest(result) or \
            terminal['evidence_ref'] != 'sha256:' + payload_digest({'start': start, 'result': result}):
        raise ValueError('recorded reference stage evidence differs')
    _validate_stage_result(result, stage=start['stage'], program_ref=start['program_ref'])
    if require_success and result['status'] != 'ok':
        raise ValueError('recorded reference stage did not succeed')
    binding = view.run_deadline_binding(run_id)
    record = clock._record
    RecordedCellClock(clock._evidence, view.cell_deadline_claim(record['cell_id']))
    if binding is None or binding['cell_id'] != record['cell_id'] or \
            binding['plan_ref'] != record['plan_ref'] or binding['deadline_ref'] != record['record_sha256']:
        raise ValueError('recorded stage belongs to another cell clock')
    clock.verify_observation(proof['observation'])
    observation = proof['observation']['observation']
    anchor = view.stage_eligibility(run_id, request_id)
    if (require_eligible and not proof['observation']['eligible']) or anchor != {
            'cell_id': record['cell_id'], 'sequence': observation['sequence'],
            'observation_sha256': observation['sha256'], 'proof_sha256': payload_digest(proof)}:
        raise ValueError('recorded reference stage eligibility differs from its campaign anchor')
    return {'program_ref': start['program_ref'], 'stage': start['stage'], 'status': result['status'],
            'eligible': proof['observation']['eligible'], 'evidence_ref': terminal['evidence_ref'],
            'geometry_ref': result.get('geometry_ref'),
            'metrics': dict(result['metrics']) if result['status'] == 'ok' else None}


def audit_recorded_reference_stage(view, clock, run_id, start, terminal, proof):
    """Recompute one successful eligible stage; not a complete run audit."""
    result = _audit_reference_stage(view, clock, run_id, start, terminal, proof,
                                    require_success=True, require_eligible=True)
    return {key: value for key, value in result.items() if key not in {'status', 'eligible'}}


def audit_recorded_reference_cascade(view, clock, run_id, stages):
    """Check stage linkage and qualification, without auditing physical settlement."""
    if type(stages) is not list or len(stages) not in (1, 2) or any(
            type(row) is not dict or set(row) != {'started', 'completed', 'eligibility'} for row in stages):
        raise ValueError('reference cascade requires one or two recorded stages')
    verified = [audit_recorded_reference_stage(view, clock, run_id, row['started'], row['completed'],
                                               row['eligibility']) for row in stages]
    first = stages[0]
    if verified[0]['stage'] != 1 or (verified[0]['metrics']['combined_score'] >= .5) != (len(stages) == 2):
        raise ValueError('reference cascade differs from the first-stage threshold')
    if len(stages) == 2:
        second = stages[1]
        if verified[1]['stage'] != 2 or verified[1]['program_ref'] != verified[0]['program_ref'] or \
                second['started']['prior_id'] != first['started']['request_id'] or \
                second['eligibility']['observation']['observation']['sequence'] <= \
                first['eligibility']['observation']['observation']['sequence']:
            raise ValueError('reference cascade predecessor or clock order differs')
    return {**verified[-1], 'stage_count': len(stages)}


def audit_recorded_reference_physical(view, clock, run_id, *, options, stamp, governance, rows,
                                      expected_rows_ref, request_ids):
    """Rebuild a pinned physical transcript and check selected stage settlement.

    The caller must obtain the transcript reference independently. This does not
    anchor the transcript or certify the worker's final selection.
    """
    from core.budget.types import AccountingStamp
    from core.composition.budget import HierarchicalBudget, JOURNAL_KIND
    from core.composition.provider_evidence import invocation_records
    if type(rows) is not list or type(expected_rows_ref) is not str or type(request_ids) is not list or \
            len(request_ids) not in (1, 2) or \
            any(type(item) is not str or not re.fullmatch(r'[0-9a-f]{32}', item) for item in request_ids) or \
            len(set(request_ids)) != len(request_ids):
        raise ValueError('physical transcript or stage identities differ from pinned evidence')
    try:
        frozen_rows = json.loads(json.dumps(rows, allow_nan=False))
        if expected_rows_ref != 'sha256:' + payload_digest(frozen_rows):
            raise ValueError('physical transcript differs from pinned evidence')
        class ReadOnlyRows:
            def read(self, kind=None):
                return (row for row in frozen_rows if kind is None or row.get('kind') == kind)
        store = ReadOnlyRows()
        budget = HierarchicalBudget(options, AccountingStamp(**stamp), store, governance=governance)
        data, _, _ = budget._rebuild()
        physical = budget.audit_governance()
        if not physical.get('protection_valid'):
            raise ValueError('physical transcript has invalid budget protection')
        view.audit_run(run_id, data['control_plan']['plan_ref'])
        provider_records = invocation_records(store)
        ids_by_kind = {}
        for kind in ('started', 'completed', 'eligibility'):
            ids = [row['payload']['request_id'] for row in frozen_rows if row.get('kind') == 'host_stage_' + kind]
            if any(type(item) is not str or not re.fullmatch(r'[0-9a-f]{32}', item) for item in ids) or \
                    len(set(ids)) != len(ids):
                raise ValueError('physical stage evidence coverage is invalid or duplicated')
            ids_by_kind[kind] = set(ids)
        stage_ids = ids_by_kind['started']
        physical_ids = {key for key in data['operations'] if key.startswith('host-stage:')}
        if any(ids_by_kind[kind] != stage_ids for kind in ids_by_kind) or \
                physical_ids != {'host-stage:' + key for key in stage_ids} or not set(request_ids) <= stage_ids:
            raise ValueError('physical stage evidence coverage differs from its reservations')
        if set(view.stage_eligibility_ids(run_id)) != stage_ids:
            raise ValueError('physical stage evidence coverage differs from the campaign anchors')
        recorded, positions, audited = {}, {}, {}
        for request_id in sorted(stage_ids):
            stage = {}
            indexes = {}
            for kind in ('started', 'completed', 'eligibility'):
                matches = [(i, row['payload']) for i, row in enumerate(frozen_rows)
                           if row.get('kind') == 'host_stage_' + kind and
                           row.get('payload', {}).get('request_id') == request_id]
                if len(matches) != 1:
                    raise ValueError('physical transcript lacks a unique stage record')
                indexes[kind], stage[kind] = matches[0]
            intent_id = stage['started']['intent_id']
            transitions = {}
            for event in ('start', 'settle'):
                matches = [i for i, row in enumerate(frozen_rows) if row.get('kind') == JOURNAL_KIND and
                           row.get('payload', {}).get('event') == event and
                           row['payload'].get('data', {}).get('intent_id') == intent_id]
                if len(matches) != 1:
                    raise ValueError('physical stage transition is missing or duplicated')
                transitions[event] = matches[0]
            operation = data['operations'].get(intent_id)
            if operation is None or operation['status'] != 'settled' or \
                    operation['fingerprint'] != stage['started']['fingerprint'] or \
                    operation['intent']['candidate']['id'] != 'host-stage-' + request_id or \
                    operation['intent']['operation'] != 'dev' or operation['intent']['lane'] != 'main' or \
                    operation['intent']['amounts'] != {'token': 0, 'node': 0, 'eval_count': 1} or \
                    operation['actual_costs'] != {'token': 0, 'node': 0, 'eval_count': 1} or \
                    operation['provider_evidence_ref'] != 'sha256:' + payload_digest([]) or \
                    operation.get('measurement_evidence_ref') != stage['completed']['evidence_ref'] or \
                    provider_records.get(intent_id):
                raise ValueError('physical stage settlement differs from its measured evidence')
            if not transitions['start'] < indexes['started'] < indexes['completed'] < \
                    transitions['settle'] < indexes['eligibility']:
                raise ValueError('physical stage transition order differs')
            recorded[request_id] = stage
            positions[request_id] = (transitions['start'], indexes['eligibility'])
            audited[request_id] = _audit_reference_stage(view, clock, run_id, stage['started'],
                stage['completed'], stage['eligibility'], require_success=False, require_eligible=False)
        used, cascade_issues = set(), []
        for request_id, stage in recorded.items():
            if stage['started']['stage'] != 2:
                continue
            prior = stage['started']['prior_id']
            first = audited.get(prior)
            if first is None or prior in used or first['stage'] != 1 or first['status'] != 'ok' or \
                    not first['eligible'] or first['metrics']['combined_score'] < .5 or \
                    first['program_ref'] != audited[request_id]['program_ref'] or \
                    positions[prior][1] >= positions[request_id][0]:
                raise ValueError('physical cascade stage order or predecessor differs')
            used.add(prior)
            second = audited[request_id]
            if second['status'] != 'ok' or not second['eligible']:
                reason = ('failed_and_late' if second['status'] != 'ok' and not second['eligible'] else
                          'failed' if second['status'] != 'ok' else 'late')
                cascade_issues.append({'first_request_id': prior, 'second_request_id': request_id, 'reason': reason})
        unattempted = sorted(key for key, value in audited.items() if value['stage'] == 1 and \
                             value['status'] == 'ok' and value['eligible'] and \
                             value['metrics']['combined_score'] >= .5 and key not in used)
        result = audit_recorded_reference_cascade(view, clock, run_id, [recorded[key] for key in request_ids])
        outcomes = [{'request_id': key, **audited[key]} for key in sorted(audited)]
        return {**result, 'stage_eval_count': len(request_ids), 'all_stage_count': len(outcomes),
                'failed_stage_count': sum(value['status'] != 'ok' for value in audited.values()),
                'late_stage_count': sum(not value['eligible'] for value in audited.values()),
                'unattempted_first_stages': unattempted, 'cascade_issues': cascade_issues,
                'stage_outcomes': outcomes, 'physical': physical}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid recorded physical transcript') from error


def _validated_reference_snapshot(view, clock, run_id):
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    if type(view) is not RecordedCurrencyView or not view._pinned_head or type(clock) is not RecordedCellClock:
        raise ValueError('anchored reference audit requires a pinned campaign and recorded clock')
    anchor = view.reference_physical_snapshot(run_id)
    binding = view.run_deadline_binding(run_id)
    if anchor is None or binding is None or anchor['cell_id'] != binding['cell_id'] or \
            anchor['cell_id'] != clock._record['cell_id'] or binding['plan_ref'] != clock._record['plan_ref'] or \
            binding['deadline_ref'] != clock._record['record_sha256']:
        raise ValueError('reference physical snapshot differs from its campaign binding')
    RecordedCellClock(clock._evidence, view.cell_deadline_claim(anchor['cell_id']))
    sequence = anchor['sequence']
    observations = clock._evidence['observations']
    if type(sequence) is not int or sequence < 1 or sequence > len(observations):
        raise ValueError('reference physical snapshot observation is missing')
    observation = observations[sequence - 1]
    remaining = max(0, clock._record['seconds'] * 1_000_000_000 -
                    (observation['observed_ns'] - clock._record['start_ns']))
    proof = {'deadline_ref': clock._record['record_sha256'], 'observation': observation,
             'eligible': remaining > 0, 'remaining_ns': remaining}
    clock.verify_observation(proof)
    if not proof['eligible'] or observation['sha256'] != anchor['observation_sha256']:
        raise ValueError('reference physical snapshot is late or differs from its clock anchor')
    return anchor


def audit_anchored_reference_physical(view, clock, run_id, *, options, stamp, governance, rows, request_ids):
    """Audit a host-attested prefix; a worker claim is not worker completion proof."""
    anchor = _validated_reference_snapshot(view, clock, run_id)
    if anchor['request_ids'] != request_ids:
        raise ValueError('reference physical snapshot stage identities differ')
    return audit_recorded_reference_physical(view, clock, run_id, options=options, stamp=stamp,
        governance=governance, rows=rows, expected_rows_ref='sha256:' + anchor['rows_sha256'],
        request_ids=request_ids)


def audit_anchored_reference_worker(view, clock, run_id, worker_proof, *, stdout, stderr, selected):
    """Check a host-attested worker terminal and report, without OS attestation."""
    anchor = _validated_reference_snapshot(view, clock, run_id)
    if type(worker_proof) is not dict or set(worker_proof) != {'schema_version', 'started', 'terminal', 'result'} or \
            type(worker_proof['schema_version']) is not int or worker_proof['schema_version'] != 1 or \
            anchor.get('worker_proof_sha256') != payload_digest(worker_proof):
        raise ValueError('worker evidence differs from its campaign anchor')
    started, terminal, result = worker_proof['started'], worker_proof['terminal'], worker_proof['result']
    if type(started) is not dict or type(terminal) is not dict or type(result) is not dict or \
            set(result) != {'returncode', 'timeout', 'stdout_sha256', 'stderr_sha256', 'wrapper_error'} or \
            type(started.get('execution_id')) is not str or \
            not re.fullmatch(r'[0-9a-f]{32}', started['execution_id']) or \
            started.get('cell_id') != anchor['cell_id'] or started.get('worker_ref') != anchor['worker_ref'] or \
            started.get('candidate_id') != 'cell-worker' or type(started.get('attempt')) is not int or \
            started['attempt'] != 1 or type(terminal.get('attempt')) is not int or \
            type(terminal.get('returncode')) is not int or type(terminal.get('timeout')) is not bool or \
            type(terminal.get('recovered')) is not bool or terminal != {
                'execution_id': started['execution_id'], 'candidate_id': 'cell-worker', 'attempt': 1,
                'returncode': 0, 'timeout': False, 'recovered': False} or \
            type(result['returncode']) is not int or result['returncode'] != 0 or \
            type(result['timeout']) is not bool or result['timeout'] is not False or result['wrapper_error'] is not None:
        raise ValueError('anchored worker process identity or terminal differs')
    if type(stdout) is not str or type(stderr) is not str or \
            len(stdout.encode('utf-8')) > 8 * 1024 * 1024 or len(stderr.encode('utf-8')) > 32 * 1024 * 1024 or \
            result['stdout_sha256'] != hashlib.sha256(stdout.encode('utf-8')).hexdigest() or \
            result['stderr_sha256'] != hashlib.sha256(stderr.encode('utf-8')).hexdigest():
        raise ValueError('anchored worker output differs')
    try:
        report = json.loads(stdout, object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if type(report) is not dict or type(report.get('schema_version')) is not int or report['schema_version'] != 1 or \
                report.get('mode') != 'fixture' or report.get('performance_claim') is not False or \
                report.get('controller') != 'pinned_openevolve' or type(selected) is not dict or \
                set(selected) != {'id', 'program_ref', 'metrics'} or type(selected['id']) is not str or \
                not selected['id'] or type(selected['program_ref']) is not str or \
                not re.fullmatch(r'sha256:[0-9a-f]{64}', selected['program_ref']) or type(selected['metrics']) is not dict or \
                json.dumps(report.get('selected_program'), sort_keys=True, allow_nan=False) != \
                json.dumps(selected, sort_keys=True, allow_nan=False):
            raise ValueError('anchored worker report differs from the selected program')
        if 'selection_stage_request_id' in report and (not anchor['request_ids'] or
                report['selection_stage_request_id'] != anchor['request_ids'][-1]):
            raise ValueError('anchored worker stage receipt differs from physical stage')
        frozen = view.reference_selection(run_id)
        if frozen is not None and (frozen['cell_id'] != anchor['cell_id'] or
                frozen['rows_sha256'] != anchor['rows_sha256'] or
                frozen['selection_sha256'] != payload_digest(selected)):
            raise ValueError('frozen reference selection differs from worker report')
        if frozen is not None:
            sequence = frozen['sequence']
            observations = clock._evidence['observations']
            if type(sequence) is not int or not anchor['sequence'] < sequence <= len(observations):
                raise ValueError('frozen reference selection observation is missing')
            observation = observations[sequence - 1]
            remaining = max(0, clock._record['seconds'] * 1_000_000_000 -
                            (observation['observed_ns'] - clock._record['start_ns']))
            clock.verify_observation({'deadline_ref': clock._record['record_sha256'],
                'observation': observation, 'eligible': remaining > 0, 'remaining_ns': remaining})
            if remaining <= 0 or observation['sha256'] != frozen['observation_sha256']:
                raise ValueError('frozen reference selection is late or has a different clock anchor')
    except (TypeError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('anchored worker report is invalid') from error
    return {'worker_ref': anchor['worker_ref'], 'execution_id': started['execution_id']}


def audit_anchored_reference_cell(view, clock, run_id, *, worker_proof, stdout, stderr, selected,
                                  options, stamp, governance, rows, request_ids):
    """Join host-attested worker and stage evidence, not a complete run audit."""
    try:
        selected = json.loads(json.dumps(selected, allow_nan=False))
        worker = audit_anchored_reference_worker(view, clock, run_id, worker_proof,
            stdout=stdout, stderr=stderr, selected=selected)
        stage = audit_anchored_reference_physical(view, clock, run_id, options=options, stamp=stamp,
            governance=governance, rows=rows, request_ids=request_ids)
        if selected['program_ref'] != stage['program_ref'] or \
                json.dumps(selected['metrics'], sort_keys=True, allow_nan=False) != \
                json.dumps(stage['metrics'], sort_keys=True, allow_nan=False):
            raise ValueError('reference worker and physical stage evidence differ')
        return {'scope': 'host_attested_reference_snapshot', 'performance_claim': False,
                'selected_program': selected, 'worker': worker, 'stage': stage}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid reference worker or stage evidence') from error
