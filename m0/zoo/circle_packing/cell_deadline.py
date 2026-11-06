"""Linux cell clock in its own journal; not a supervisor or live admission gate."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import threading
import time

from core.composition.recovery import ContinuationStore
from core.x1.checkpoint import payload_digest
from core.x1.store import AppendOnlyStore

_KIND = 'circle_cell_deadline_started'
_OBSERVED = 'circle_cell_deadline_observed'


class DeadlineExpired(TimeoutError):
    """A frozen cell deadline has passed."""


def _boot_identity():
    try:
        value = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    except OSError as error:
        raise ValueError('a stable operating-system boot identity is required') from error
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        raise ValueError('invalid operating-system boot identity')
    return value


def _clock_ns():
    if not hasattr(time, 'CLOCK_BOOTTIME'):
        raise ValueError('a suspend-aware monotonic clock is required')
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


@contextmanager
def _exclusive(store):
    _validate_path(store)
    lock_path = store.path.parent.resolve() / (store.path.name + '.cell-deadline.lock')
    if lock_path.is_symlink():
        raise ValueError('cell deadline lock cannot be a symlink')
    with lock_path.open('a') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_path(store):
    if store.path.is_symlink() or store.path.exists() and store.path.stat().st_nlink != 1:
        raise ValueError('cell deadline journal cannot be a link')


def _parameters(store, cell_id, plan_ref, seconds):
    if not isinstance(store, ContinuationStore) or type(cell_id) is not str or \
            not re.fullmatch(r'(?:vendor|mori)-[0-9]+', cell_id) or type(plan_ref) is not str or \
            not re.fullmatch(r'sha256:[0-9a-f]{64}', plan_ref) or \
            type(seconds) is not int or not 1 <= seconds <= 86400:
        raise ValueError('cell deadline requires a durable store and bounded frozen identity')


def _validate_record(store, record):
    if type(record) is not dict or set(record) != {'schema_version', 'cell_id', 'plan_ref', 'seconds',
                                                  'boot_id', 'start_ns', 'record_sha256'} or \
            type(record['schema_version']) is not int or record['schema_version'] != 1 or \
            type(record['boot_id']) is not str or not record['boot_id'] or \
            type(record['start_ns']) is not int or record['start_ns'] < 0 or \
            record['record_sha256'] != payload_digest({key: value for key, value in record.items()
                                                        if key != 'record_sha256'}):
        raise ValueError('cell deadline record differs from its frozen identity')
    _parameters(store, record['cell_id'], record['plan_ref'], record['seconds'])


def _rows(store):
    _validate_path(store)
    if store.restoring or store.cursor != len(store.rows):
        raise ValueError('cell deadline requires a dedicated non-replaying journal')
    # Refuse stale continuation views before appending to a shared journal.
    durable = list(AppendOnlyStore(store.path).read())
    if list(store.read()) != durable:
        raise ValueError('cell deadline continuation differs from durable journal')
    return durable


def _records(store):
    return [row['payload'] for row in _rows(store) if row['kind'] == _KIND]


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class CellDeadline:
    def __init__(self, store, record):
        _validate_record(store, record)
        self._store, self._record = store, record
        self._lock = threading.RLock()
        self._last_ns = record['start_ns']

    @classmethod
    def start(cls, store, *, cell_id, plan_ref, seconds):
        _parameters(store, cell_id, plan_ref, seconds)
        with _exclusive(store):
            rows = _rows(store)
            if any(row['kind'] == _KIND for row in rows):
                raise ValueError('cell deadline already exists')
            if rows:
                raise ValueError('cell deadline cannot start after prior journal work')
            boot, start_ns = _boot_identity(), _clock_ns()
            if type(boot) is not str or not boot or type(start_ns) is not int or start_ns < 0:
                raise ValueError('cell clock identity is invalid')
            record = {'schema_version': 1, 'cell_id': cell_id, 'plan_ref': plan_ref,
                      'seconds': seconds, 'boot_id': boot, 'start_ns': start_ns}
            record['record_sha256'] = payload_digest(record)
            store.append(_KIND, record)
            _sync_directory(store.path.parent)
            if _records(store) != [record]:
                raise ValueError('cell deadline was not durably recorded')
            return cls(store, record)

    @classmethod
    def restore(cls, store, *, cell_id, plan_ref, seconds):
        _parameters(store, cell_id, plan_ref, seconds)
        with _exclusive(store):
            records = _records(store)
            if len(records) != 1:
                raise ValueError('cell deadline is missing or duplicated')
            record = records[0]
            _validate_record(store, record)
            if (record['cell_id'], record['plan_ref'], record['seconds']) != (cell_id, plan_ref, seconds):
                raise ValueError('cell deadline differs from frozen identity')
            instance = cls(store, record)
            instance._remaining()
            return instance

    def _remaining(self):
        rows = _rows(self._store)
        if any(row['kind'] not in {_KIND, _OBSERVED} for row in rows):
            raise ValueError('cell deadline requires a dedicated journal')
        starts = [row['payload'] for row in rows if row['kind'] == _KIND]
        if starts != [self._record]:
            raise ValueError('durable cell deadline differs from its authority')
        if _boot_identity() != self._record['boot_id']:
            raise ValueError('cell deadline boot identity changed')
        previous, last = self._record['record_sha256'], self._record['start_ns']
        observations = [row['payload'] for row in rows if row['kind'] == _OBSERVED]
        for index, observation in enumerate(observations, 1):
            if type(observation) is not dict or set(observation) != {'sequence', 'previous', 'observed_ns', 'sha256'} or \
                    type(observation['sequence']) is not int or observation['sequence'] != index or \
                    observation['previous'] != previous or type(observation['observed_ns']) is not int or \
                    observation['observed_ns'] < last or observation['sha256'] != payload_digest(
                        {key: value for key, value in observation.items() if key != 'sha256'}):
                raise ValueError('cell deadline observation differs from its journal')
            previous, last = observation['sha256'], observation['observed_ns']
        now = _clock_ns()
        if type(now) is not int or now < max(self._last_ns, last):
            raise ValueError('cell monotonic clock regressed')
        observation = {'sequence': len(observations) + 1, 'previous': previous, 'observed_ns': now}
        observation['sha256'] = payload_digest(observation)
        self._store.append(_OBSERVED, observation)
        self._last_ns = now
        return max(0, self._record['seconds'] * 1_000_000_000 - (now - self._record['start_ns'])) / 1_000_000_000

    def remaining(self):
        with self._lock, _exclusive(self._store):
            return self._remaining()

    def check(self):
        if self.remaining() <= 0:
            raise DeadlineExpired('cell deadline expired')
