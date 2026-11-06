"""Observe reference admissions without asserting their independent validity."""
from contextlib import contextmanager
import copy
import hashlib


class _AdmissionCapture:
    def __init__(self):
        self.events = []
        self.database_id = None
        self.failed = False

    def snapshot(self):
        if self.failed or not 1 <= len(self.events) <= 1000:
            raise ValueError('reference admission capture failed or is incomplete')
        return {'schema_version': 2, 'scope': 'host_observed_reference_admissions',
                'events': copy.deepcopy(self.events)}


@contextmanager
def capture_reference_admissions(database_class):
    """Wrap the actual host add method; any failed capture invalidates the trace."""
    capture = _AdmissionCapture()
    original = database_class.add
    def add(database, program, iteration=None, target_island=None):
        try:
            if capture.database_id is None:
                capture.database_id = id(database)
            if id(database) != capture.database_id:
                raise ValueError('reference admission capture requires one database')
            kind = ('migrant' if program.metadata.get('migrant') is True else
                    'seed' if not capture.events else 'candidate')
            event = {'kind': kind, 'id': program.id, 'parent_id': program.parent_id,
                     'program_ref': 'sha256:' + hashlib.sha256(program.code.encode('utf-8')).hexdigest(),
                     'metrics': copy.deepcopy(program.metrics), 'best_before': database.best_program_id,
                     'iteration': iteration, 'target_island': target_island}
            result = original(database, program, iteration=iteration, target_island=target_island)
            if result != program.id:
                raise ValueError('reference admission did not accept the program')
            event['best_after'] = database.best_program_id
            capture.events.append(event)
            return result
        except BaseException:
            capture.failed = True
            raise
    database_class.add = add
    try:
        yield capture
    finally:
        database_class.add = original
