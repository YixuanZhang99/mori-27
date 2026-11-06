"""One isolated worker under an existing cell clock; not a live pilot entrypoint.

The supervisor retains currency and physical authority. This primitive does
not establish a frozen source/environment, connect a broker, or settle any
provider call. An interrupted worker remains unresolved and cannot be retried.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

from core.composition.recovery import ContinuationStore
from core.executor.process import ProcessJournal
from core.executor.sandbox import BubblewrapSandbox
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_deadline import CellDeadline, DeadlineExpired, _boot_identity, _clock_ns


def _stop_watch(deadline):
    """Monitor only for stopping; admission still uses the durable authority."""
    record = deadline._record
    boot = record['boot_id']
    end = record['start_ns'] + record['seconds'] * 1_000_000_000
    last = deadline._last_ns
    def remaining():
        nonlocal last
        now = _clock_ns()
        if _boot_identity() != boot or type(now) is not int or now < last:
            raise ValueError('cell watchdog clock identity changed or regressed')
        last = now
        return max(0, end - now) / 1_000_000_000
    return remaining


def run_cell_worker(deadline, directory, workspace, command):
    """Launch one credential-free worker; expiry never certifies its result."""
    if type(deadline) is not CellDeadline or type(command) is not list or not command or \
            any(type(part) is not str or not part for part in command):
        raise ValueError('cell worker requires a deadline and nonempty command')
    workspace = Path(workspace).resolve(strict=True)
    directory = Path(directory).resolve()
    if not workspace.is_dir() or directory == workspace or workspace in directory.parents or \
            directory in workspace.parents or workspace == deadline._store.path.parent.resolve() or \
            workspace in deadline._store.path.resolve().parents or \
            workspace in deadline._lifecycle.ledger.path.resolve().parents:
        raise ValueError('worker workspace must be isolated from its authorities')
    remaining = deadline.remaining()
    if remaining <= 0:
        raise DeadlineExpired('cell deadline expired before worker claim')
    sandbox = BubblewrapSandbox()
    args = sandbox.wrap(command, workspace)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    store = ContinuationStore(directory / 'worker.jsonl')
    journal = ProcessJournal(store)
    record = deadline._record
    reference = payload_digest({'schema_version': 1, 'cell_id': record['cell_id'],
        'deadline_ref': record['record_sha256'], 'workspace': str(workspace),
        'command': command, 'sandbox': 'bubblewrap-seccomp-v1'})
    # This irreversible claim is the authority if local process evidence is lost.
    deadline._lifecycle.ledger.claim_cell_worker(record['cell_id'], record['record_sha256'], reference)
    store.append('circle_cell_worker_claimed', {'cell_id': record['cell_id'],
        'deadline_ref': record['record_sha256'], 'worker_ref': reference})
    remaining = deadline.remaining()
    if remaining <= 0:
        raise DeadlineExpired('cell deadline expired before worker start')
    stop_remaining = _stop_watch(deadline)
    process, execution = journal.launch(args, workspace, {}, remaining,
        {'candidate_id': 'cell-worker', 'attempt': 1, 'cell_id': record['cell_id'],
         'worker_ref': reference}, seccomp_policy=sandbox.seccomp_spec(), die_with_parent=True,
        absolute_deadline={'boot_id': record['boot_id'],
            'deadline_ns': record['start_ns'] + record['seconds'] * 1_000_000_000})
    try:
        while process.poll() is None:
            remaining = stop_remaining()
            if remaining <= 0:
                journal.terminate_target(execution)
                process.kill()
                process.wait()
                journal.terminate_target(execution)
                return {'state': 'expired_unresolved'}
            try:
                process.wait(timeout=min(remaining, 0.2))
            except subprocess.TimeoutExpired:
                pass
        if deadline.remaining() <= 0:
            journal.terminate_target(execution)
            return {'state': 'expired_unresolved'}
        result = journal.wait(process, execution)
        if result['timeout'] or deadline.remaining() <= 0:
            return {'state': 'expired_unresolved'}
        return {'state': 'completed' if result['returncode'] == 0 and not result['wrapper_error'] else 'failed',
                'returncode': result['returncode']}
    except BaseException:
        if process.poll() is None:
            journal.terminate_target(execution)
            process.kill()
            process.wait()
        journal.terminate_target(execution)
        raise
