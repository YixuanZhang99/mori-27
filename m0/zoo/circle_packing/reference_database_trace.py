"""Capture original reference database admissions for independent replay.

Artifacts contain candidate source and are private local evidence. This trace
alone does not certify all database mutations or the final winner.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import re
import stat

from core.openevolve_interop import OpenEvolveDatabaseSnapshot, Program


class _DatabaseCapture:
    def __init__(self, root):
        self.root = Path(root)
        self.events = []
        self.database_id = None
        self.finished = False
        self.failed = False

    def finish(self):
        if self.finished or self.failed:
            raise ValueError('reference database capture has already been finished')
        payload = {'schema_version': 1, 'events': self.events}
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError('reference database capture exceeds its size bound')
        fd = os.open(self.root / 'database-additions.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
        self.finished = True
        return {'schema_version': 1, 'scope': 'reference_database_additions',
                'sha256': hashlib.sha256(raw).hexdigest(), 'count': len(self.events)}


@contextmanager
def capture_database_additions(database_class, root):
    """Record actual `add` inputs and snapshots while preserving its result."""
    capture = _DatabaseCapture(root)
    original = database_class.add
    def add(database, program, iteration=None, target_island=None):
        try:
            if capture.database_id is None:
                capture.database_id = id(database)
            if capture.finished or capture.database_id != id(database):
                raise ValueError('reference database capture requires one active database')
            before = OpenEvolveDatabaseSnapshot.from_database(database).payload
            program_input = copy.deepcopy(program.to_dict())
        except BaseException:
            capture.failed = True
            raise
        returned = original(database, program, iteration=iteration, target_island=target_island)
        try:
            after = OpenEvolveDatabaseSnapshot.from_database(database).payload
            capture.events.append({'before': before, 'program': program_input, 'iteration': iteration,
                                   'target_island': target_island, 'returned': returned, 'after': after})
        except BaseException:
            capture.failed = True
            raise
        return returned
    database_class.add = add
    try:
        yield capture
    finally:
        database_class.add = original


def replay_database_additions(path, *, expected_sha256, expected_count):
    """Replay isolated admissions; this does not prove continuity or the winner."""
    if (not isinstance(expected_sha256, str) or
            not re.fullmatch(r'[0-9a-f]{64}', expected_sha256) or
            type(expected_count) is not int or not 1 <= expected_count <= 1000):
        raise ValueError('invalid reference database capture commitment')
    path = Path(path)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    before.st_nlink != 1 or before.st_size > 64 * 1024 * 1024):
                raise ValueError('unsafe reference database capture')
            raw = stream.read(64 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != expected_sha256):
            raise ValueError('reference database capture commitment mismatch')
    finally:
        os.close(parent_fd)

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key in reference database capture')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError('nonfinite number in reference database capture')

    payload = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    if (not isinstance(payload, dict) or set(payload) != {'schema_version', 'events'} or
            type(payload['schema_version']) is not int or payload['schema_version'] != 1 or
            not isinstance(payload['events'], list) or len(payload['events']) != expected_count):
        raise ValueError('invalid reference database capture envelope')
    random_state = random.getstate()
    try:
        for event in payload['events']:
            if (not isinstance(event, dict) or
                    set(event) != {'before', 'program', 'iteration', 'target_island', 'returned', 'after'} or
                    not isinstance(event['program'], dict) or
                    (event['iteration'] is not None and
                     (type(event['iteration']) is not int or event['iteration'] < 0)) or
                    (event['target_island'] is not None and
                     (type(event['target_island']) is not int or event['target_island'] < 0)) or
                    (event['returned'] is not None and not isinstance(event['returned'], str))):
                raise ValueError('invalid reference database admission')
            database = OpenEvolveDatabaseSnapshot(event['before']).to_database()
            if database.embedding_client is not None and database.similarity_threshold > 0:
                raise ValueError('network-backed novelty cannot be replayed offline')
            returned = database.add(Program.from_dict(copy.deepcopy(event['program'])),
                                    iteration=event['iteration'], target_island=event['target_island'])
            actual = OpenEvolveDatabaseSnapshot.from_database(database).payload
            canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False,
                                                   separators=(',', ':'), allow_nan=False)
            if returned != event['returned'] or canonical(actual) != canonical(event['after']):
                raise ValueError('reference database admission replay mismatch')
    finally:
        random.setstate(random_state)
    return {'schema_version': 1, 'scope': 'independent_reference_database_additions',
            'verified_additions': expected_count, 'continuity_verified': False,
            'final_winner_certified': False}
