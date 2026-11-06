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


def audit_recorded_reference_stage(view, clock, run_id, start, terminal, proof):
    """Recompute one anchored stage; this is not a full physical-run audit."""
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
    if result['status'] != 'ok':
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
    if not proof['observation']['eligible'] or anchor != {
            'cell_id': record['cell_id'], 'sequence': observation['sequence'],
            'observation_sha256': observation['sha256'], 'proof_sha256': payload_digest(proof)}:
        raise ValueError('recorded reference stage eligibility differs from its campaign anchor')
    return {'program_ref': start['program_ref'], 'stage': start['stage'],
            'evidence_ref': terminal['evidence_ref'], 'geometry_ref': result['geometry_ref'],
            'metrics': dict(result['metrics'])}


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
