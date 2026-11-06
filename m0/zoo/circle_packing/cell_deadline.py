"""Linux cell clock in its own journal; not a supervisor or live admission gate."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import threading
import time

from core.composition.recovery import ContinuationStore
from core.llm import ProviderDeadlineSignal
from core.x1.checkpoint import payload_digest
from core.x1.store import AppendOnlyStore

_KIND = 'circle_cell_deadline_started'
_OBSERVED = 'circle_cell_deadline_observed'


class DeadlineExpired(ProviderDeadlineSignal):
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
            not re.fullmatch(r'(?:vendor|mori)-(?:0|[1-9][0-9]*)', cell_id) or type(plan_ref) is not str or \
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
    return list(AppendOnlyStore(store.path).read())


def _records(store):
    return [row['payload'] for row in _rows(store) if row['kind'] == _KIND]


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_unstarted(ledger, cell_id):
    if ledger.cell_worker_claim(cell_id) is not None or (cell_id.startswith('vendor-') and (
            ledger.reference_host_claim(cell_id) is not None or ledger.reference_authority_claim(cell_id) is not None)):
        raise ValueError('clock reconciliation requires an unstarted cell')


class CellLifecycle:
    """First-start claims in the original campaign's transactional journal."""
    def __init__(self, ledger):
        from zoo.mle_bench_lite.cny_budget import CampaignBudget
        if type(ledger) is not CampaignBudget:
            raise ValueError('cell lifecycle requires the original campaign ledger')
        self.ledger = ledger
        self.campaign_id = ledger.manifest_binding()['campaign_id']

    def create(self, record):
        self.ledger.claim_cell_deadline(record['cell_id'], record['plan_ref'], record['record_sha256'],
                                        seconds=record['seconds'])

    def verify(self, record):
        claim = self.ledger.cell_deadline_claim(record['cell_id'])
        pilot = self.ledger.circle_pilot_binding()
        if pilot is not None and (pilot['plan_ref'] != record['plan_ref'] or
                pilot['wallclock_seconds'] != record['seconds'] or
                re.fullmatch(r'(?:vendor|mori)-[012]', record['cell_id']) is None):
            raise ValueError('cell duration or identity differs from the frozen pilot')
        if self.ledger.manifest_binding()['campaign_id'] != self.campaign_id or claim is None or \
                claim['plan_ref'] != record['plan_ref'] or claim['record_sha256'] != record['record_sha256']:
            raise ValueError('cell lifecycle claim is missing or differs from the frozen deadline')
        return claim


class CellDeadline:
    def __init__(self, store, record, *, lifecycle):
        _validate_record(store, record)
        if type(lifecycle) is not CellLifecycle:
            raise ValueError('cell deadline requires an independent lifecycle authority')
        lifecycle.verify(record)
        self._store, self._record, self._lifecycle = store, record, lifecycle
        self._lock = threading.RLock()
        self._last_ns = record['start_ns']

    @classmethod
    def start(cls, store, *, lifecycle, cell_id, plan_ref, seconds):
        _parameters(store, cell_id, plan_ref, seconds)
        if type(lifecycle) is not CellLifecycle or lifecycle.ledger.path.resolve() == store.path.resolve():
            raise ValueError('cell lifecycle must be independent from the cell journal directory')
        with _exclusive(store):
            rows = _rows(store)
            if any(row['kind'] == _KIND for row in rows):
                raise ValueError('cell deadline already exists')
            if rows:
                raise ValueError('cell deadline cannot start after prior journal work')
            if lifecycle.ledger.cell_deadline_claim(cell_id) is not None:
                raise ValueError('cell deadline claim already exists')
            boot, start_ns = _boot_identity(), _clock_ns()
            if type(boot) is not str or not boot or type(start_ns) is not int or start_ns < 0:
                raise ValueError('cell clock identity is invalid')
            record = {'schema_version': 1, 'cell_id': cell_id, 'plan_ref': plan_ref,
                      'seconds': seconds, 'boot_id': boot, 'start_ns': start_ns}
            record['record_sha256'] = payload_digest(record)
            ContinuationStore(store.path).append(_KIND, record)
            _sync_directory(store.path.parent)
            lifecycle.create(record)
            if _records(store) != [record]:
                raise ValueError('cell deadline was not durably recorded')
            return cls(store, record, lifecycle=lifecycle)

    @classmethod
    def restore(cls, store, *, lifecycle, cell_id, plan_ref, seconds, reconcile_unstarted=False):
        _parameters(store, cell_id, plan_ref, seconds)
        if type(lifecycle) is not CellLifecycle or lifecycle.ledger.path.resolve() == store.path.resolve():
            raise ValueError('cell lifecycle must be independent from the cell journal directory')
        with _exclusive(store):
            records = _records(store)
            if len(records) != 1:
                raise ValueError('cell deadline is missing or duplicated')
            record = records[0]
            _validate_record(store, record)
            if (record['cell_id'], record['plan_ref'], record['seconds']) != (cell_id, plan_ref, seconds):
                raise ValueError('cell deadline differs from frozen identity')
            if type(reconcile_unstarted) is not bool:
                raise ValueError('clock reconciliation flag must be boolean')
            if reconcile_unstarted:
                _require_unstarted(lifecycle.ledger, cell_id)
                if _boot_identity() != record['boot_id'] or _clock_ns() < record['start_ns']:
                    raise ValueError('original cell clock identity or monotonic time changed')
                if lifecycle.ledger.cell_deadline_claim(cell_id) is None:
                    if _rows(store) != [{'kind': _KIND, 'payload': record}]:
                        raise ValueError('unclaimed clock must contain only its original start')
                    lifecycle.create(record)
            instance = cls(store, record, lifecycle=lifecycle)
            if reconcile_unstarted:
                instance._checked_history(reconcile_unstarted=True)
            instance._remaining()
            return instance

    def _checked_history(self, *, reconcile_unstarted=False):
        claim = self._lifecycle.verify(self._record)
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
        if (claim['observation_sequence'], claim['observation_sha256']) != (len(observations), previous):
            if not reconcile_unstarted or not observations or claim['observation_sequence'] != len(observations) - 1 or \
                    claim['observation_sha256'] != observations[-1]['previous'] or _clock_ns() < last:
                raise ValueError('cell deadline observation head differs from campaign authority')
            _require_unstarted(self._lifecycle.ledger, self._record['cell_id'])
            self._lifecycle.ledger.anchor_unstarted_cell_observation(self._record['cell_id'],
                observations[-1]['sequence'], observations[-1]['previous'], observations[-1]['sha256'])
        return observations, previous, last

    def _observe(self):
        observations, previous, last = self._checked_history()
        now = _clock_ns()
        if type(now) is not int or now < max(self._last_ns, last):
            raise ValueError('cell monotonic clock regressed')
        observation = {'sequence': len(observations) + 1, 'previous': previous, 'observed_ns': now}
        observation['sha256'] = payload_digest(observation)
        ContinuationStore(self._store.path).append(_OBSERVED, observation)
        self._lifecycle.ledger.anchor_cell_deadline_observation(
            self._record['cell_id'], observation['sequence'], observation['previous'], observation['sha256'])
        self._last_ns = now
        remaining_ns = max(0, self._record['seconds'] * 1_000_000_000 - (now - self._record['start_ns']))
        return {'deadline_ref': self._record['record_sha256'], 'observation': observation,
                'eligible': remaining_ns > 0, 'remaining_ns': remaining_ns}

    def _remaining(self):
        return self._observe()['remaining_ns'] / 1_000_000_000

    def observe(self):
        """Return the just-anchored clock observation and its current eligibility."""
        with self._lock, _exclusive(self._store):
            return self._observe()

    def observe_and_anchor(self, anchor):
        """Serialize the operation's authority anchor with its clock observation."""
        if not callable(anchor):
            raise ValueError('deadline observation requires an anchor callback')
        with self._lock, _exclusive(self._store):
            observation = self._observe()
            anchor(observation)
            return observation

    def export_evidence(self):
        """Export the original clock chain after checking its campaign anchor."""
        with self._lock, _exclusive(self._store):
            observations, _, _ = self._checked_history()
            return json.loads(json.dumps({'schema_version': 1, 'record': self._record,
                                          'observations': observations}, allow_nan=False))

    def verify_observation(self, proof):
        """Check an operation's observation against the original anchored clock chain."""
        with self._lock, _exclusive(self._store):
            observations, _, _ = self._checked_history()
            if type(proof) is not dict or set(proof) != {'deadline_ref', 'observation', 'eligible', 'remaining_ns'} \
                    or proof['deadline_ref'] != self._record['record_sha256'] or type(proof['observation']) is not dict:
                raise ValueError('invalid deadline eligibility evidence')
            value = proof['observation']
            seq = value.get('sequence')
            if type(seq) is not int or type(value.get('observed_ns')) is not int or \
                    set(value) != {'sequence', 'previous', 'observed_ns', 'sha256'} or seq < 1 or seq > len(observations) or \
                    payload_digest(observations[seq - 1]) != payload_digest(value):
                raise ValueError('deadline eligibility observation is not anchored')
            remaining = max(0, self._record['seconds'] * 1_000_000_000 -
                            (value['observed_ns'] - self._record['start_ns']))
            if type(proof['remaining_ns']) is not int or proof['remaining_ns'] != remaining or \
                    type(proof['eligible']) is not bool or proof['eligible'] != (remaining > 0):
                raise ValueError('deadline eligibility differs from observation')

    def remaining(self):
        with self._lock, _exclusive(self._store):
            return self._remaining()

    def check(self):
        if self.remaining() <= 0:
            raise DeadlineExpired('cell deadline expired')


class RecordedCellClock:
    """Validate detached clock history against a separately verified campaign claim."""
    def __init__(self, evidence, claim):
        if type(evidence) is not dict or set(evidence) != {'schema_version', 'record', 'observations'} or \
                type(evidence['schema_version']) is not int or evidence['schema_version'] != 1 or \
                type(evidence['record']) is not dict or type(evidence['observations']) is not list:
            raise ValueError('invalid recorded cell clock evidence')
        record = evidence['record']
        if set(record) != {'schema_version', 'cell_id', 'plan_ref', 'seconds', 'boot_id', 'start_ns', 'record_sha256'} or \
                type(record['schema_version']) is not int or record['schema_version'] != 1 or \
                type(record['cell_id']) is not str or not re.fullmatch(r'(?:vendor|mori)-(?:0|[1-9][0-9]*)', record['cell_id']) or \
                type(record['plan_ref']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', record['plan_ref']) or \
                type(record['seconds']) is not int or not 1 <= record['seconds'] <= 86400 or \
                type(record['boot_id']) is not str or not record['boot_id'] or \
                type(record['start_ns']) is not int or record['start_ns'] < 0 or \
                record['record_sha256'] != payload_digest({key: value for key, value in record.items() if key != 'record_sha256'}):
            raise ValueError('recorded cell clock identity differs')
        previous, last = record['record_sha256'], record['start_ns']
        for index, observation in enumerate(evidence['observations'], 1):
            if type(observation) is not dict or set(observation) != {'sequence', 'previous', 'observed_ns', 'sha256'} or \
                    type(observation['sequence']) is not int or observation['sequence'] != index or \
                    observation['previous'] != previous or type(observation['observed_ns']) is not int or \
                    observation['observed_ns'] < last or observation['sha256'] != payload_digest(
                        {key: value for key, value in observation.items() if key != 'sha256'}):
                raise ValueError('recorded cell clock observation differs')
            previous, last = observation['sha256'], observation['observed_ns']
        if type(claim) is not dict or set(claim) != {'plan_ref', 'record_sha256', 'observation_sequence', 'observation_sha256'} or \
                claim['plan_ref'] != record['plan_ref'] or claim['record_sha256'] != record['record_sha256'] or \
                type(claim['observation_sequence']) is not int or \
                (claim['observation_sequence'], claim['observation_sha256']) != (len(evidence['observations']), previous):
            raise ValueError('recorded cell clock differs from campaign anchor')
        self._evidence = json.loads(json.dumps(evidence, allow_nan=False))
        self._record = self._evidence['record']

    def verify_observation(self, proof):
        if type(proof) is not dict or set(proof) != {'deadline_ref', 'observation', 'eligible', 'remaining_ns'} or \
                proof['deadline_ref'] != self._record['record_sha256'] or type(proof['observation']) is not dict:
            raise ValueError('invalid recorded deadline eligibility evidence')
        observation = proof['observation']
        sequence = observation.get('sequence')
        rows = self._evidence['observations']
        if type(sequence) is not int or type(observation.get('observed_ns')) is not int or \
                set(observation) != {'sequence', 'previous', 'observed_ns', 'sha256'} or sequence < 1 or sequence > len(rows) or \
                payload_digest(rows[sequence - 1]) != payload_digest(observation):
            raise ValueError('recorded deadline eligibility observation is not anchored')
        remaining = max(0, self._record['seconds'] * 1_000_000_000 -
                        (observation['observed_ns'] - self._record['start_ns']))
        if type(proof['remaining_ns']) is not int or proof['remaining_ns'] != remaining or \
                type(proof['eligible']) is not bool or proof['eligible'] != (remaining > 0):
            raise ValueError('recorded deadline eligibility differs from observation')
