"""Recover an anchored reference snapshot without restarting any work.

The recovered result remains host-attested evidence for a fixed journal head;
it is not a complete-run, final-winner, or performance certification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from zoo.circle_packing.reference_final import recalculate_reference_snapshot
from zoo.circle_packing.reference_selection import _unique

_MAX_JOURNAL_BYTES = 1024 * 1024


def read_worker_journal(directory):
    """Read one bounded, no-follow worker journal without creating a file."""
    directory_fd = file_fd = None
    try:
        directory_fd = os.open(Path(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        file_fd = os.open('worker.jsonl', os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0),
                          dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid() or \
                before.st_size > _MAX_JOURNAL_BYTES:
            raise ValueError('worker journal is not a bounded private regular file')
        parts, remaining = [], _MAX_JOURNAL_BYTES + 1
        while remaining:
            part = os.read(file_fd, remaining)
            if not part:
                break
            parts.append(part)
            remaining -= len(part)
        data, after = b''.join(parts), os.fstat(file_fd)
        now = os.stat('worker.jsonl', dir_fd=directory_fd, follow_symlinks=False)
        def identity(value):
            return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        if len(data) > _MAX_JOURNAL_BYTES or identity(before) != identity(after) or identity(after) != identity(now):
            raise ValueError('worker journal changed while reading')
        records = [json.loads(line, object_pairs_hook=_unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
                   for line in data.decode('utf-8').splitlines() if line.strip()]
        if any(type(row) is not dict or set(row) != {'kind', 'payload'} or type(row['kind']) is not str or
               type(row['payload']) is not dict for row in records):
            raise ValueError('invalid worker journal row')
        starts = [(i, row['payload']) for i, row in enumerate(records) if row['kind'] == 'executor_process_started']
        ends = [(i, row['payload']) for i, row in enumerate(records) if row['kind'] == 'executor_process_finished']
        if len(starts) != 1 or len(ends) != 1 or starts[0][0] >= ends[0][0]:
            raise ValueError('worker journal lacks a unique ordered terminal')
        return starts[0][1], ends[0][1]
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, RecursionError) as error:
        raise ValueError('worker journal cannot be safely read') from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def recover_reference_snapshot(view, clock, run_id, *, plan, expected_plan_ref, worker_directory,
                               options, stamp, governance, rows):
    """Reconstruct original worker proof and recalculate an anchored snapshot."""
    from zoo.circle_packing.host_runtime import _read_verified_worker_result
    try:
        directory = Path(worker_directory)
        if not directory.is_absolute():
            raise ValueError('reference worker directory must be absolute')
        started, terminal = read_worker_journal(directory)
        process = _read_verified_worker_result(directory, started)
        report = json.loads(process['stdout'], object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        proof = {'schema_version': 1, 'started': started, 'terminal': terminal,
            'result': {'returncode': process['returncode'], 'timeout': process['timeout'],
                'stdout_sha256': hashlib.sha256(process['stdout'].encode('utf-8')).hexdigest(),
                'stderr_sha256': hashlib.sha256(process['stderr'].encode('utf-8')).hexdigest(),
                'wrapper_error': process['wrapper_error']}}
        anchor = view.reference_physical_snapshot(run_id)
        if type(anchor) is not dict:
            raise ValueError('reference recovery requires the original physical snapshot')
        result = recalculate_reference_snapshot(view, clock, run_id, plan=plan, expected_plan_ref=expected_plan_ref,
            worker_proof=proof, stdout=process['stdout'], stderr=process['stderr'], selected=report['selected_program'],
            options=options, stamp=stamp, governance=governance, rows=rows, request_ids=anchor['request_ids'])
        trace = report.get('iteration_trace')
        if trace is not None:
            from zoo.circle_packing.reference_iteration_trace import reference_iteration_attempt_limit
            required = {'schema_version', 'scope', 'performance_claim', 'iterations'}
            if type(trace) is not dict or not required <= set(trace) or \
                    set(trace) - required - {'prompt_bindings', 'request_bindings', 'stage_bindings', 'controller_run'} or \
                    type(trace['schema_version']) is not int or trace['schema_version'] != 1 or \
                    trace['scope'] != 'reference_submitted_future_outcomes' or trace['performance_claim'] is not False or \
                    type(trace['iterations']) is not list or \
                    len(trace['iterations']) > reference_iteration_attempt_limit(plan['iterations']):
                raise ValueError('reference worker iteration trace is invalid')
            if 'prompt_bindings' in trace and (type(trace['prompt_bindings']) is not list or
                    len(trace['prompt_bindings']) > reference_iteration_attempt_limit(plan['iterations'])):
                raise ValueError('reference worker prompt bindings are invalid')
            if 'request_bindings' in trace and (type(trace['request_bindings']) is not list or
                    len(trace['request_bindings']) > reference_iteration_attempt_limit(plan['iterations'])):
                raise ValueError('reference worker request bindings are invalid')
            if 'stage_bindings' in trace and (type(trace['stage_bindings']) is not list or
                    len(trace['stage_bindings']) > 2 * reference_iteration_attempt_limit(plan['iterations'])):
                raise ValueError('reference worker stage bindings are invalid')
            result['iteration_trace'] = trace
        database_capture = report.get('database_capture')
        if database_capture is not None:
            if type(database_capture) is not dict or set(database_capture) != {'schema_version', 'scope', 'sha256', 'count'} or \
                    type(database_capture['schema_version']) is not int or database_capture['schema_version'] != 1 or \
                    database_capture['scope'] != 'reference_database_additions' or \
                    type(database_capture['sha256']) is not str or \
                    not re.fullmatch(r'[0-9a-f]{64}', database_capture['sha256']) or \
                    type(database_capture['count']) is not int or not 1 <= database_capture['count'] <= 1000:
                raise ValueError('reference database capture metadata is invalid')
            result['database_capture'] = database_capture
        return result
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError('invalid original reference recovery evidence') from error
