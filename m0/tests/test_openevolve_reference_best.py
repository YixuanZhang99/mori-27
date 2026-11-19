"""Replay the pinned host's best tracking against independently supplied evaluations."""
from copy import deepcopy
import hashlib

import pytest

from zoo.circle_packing.reference_best_audit import audit_reference_best, audit_reference_best_from_physical
from zoo.circle_packing.reference_best_capture import capture_reference_admissions


def record(kind, ident, program_ref, metrics, before, after, parent=None):
    return {'kind': kind, 'id': ident, 'parent_id': parent, 'program_ref': program_ref,
            'metrics': metrics, 'best_before': before, 'best_after': after}


def test_recalculates_best_from_evaluations_and_migrations_with_stable_ties():
    seed = {'program_ref': 'sha256:' + '1' * 64, 'metrics': {'combined_score': 1.0}}
    child = {'program_ref': 'sha256:' + '2' * 64, 'metrics': {'combined_score': 2.0}}
    tie = {'program_ref': 'sha256:' + '3' * 64, 'metrics': {'combined_score': 2.0}}
    evaluated = {'seed': seed, 'child': child, 'tie': tie}
    events = [record('seed', 'seed', **seed, before=None, after='seed'),
              record('candidate', 'child', **child, before='seed', after='child'),
              record('migrant', 'copy', **child, before='child', after='child', parent='child'),
              record('candidate', 'tie', **tie, before='child', after='child')]
    result = audit_reference_best(events, evaluated=evaluated, selected_id='child')
    assert result['selected_id'] == 'child' and result['fitness'] == 2.0
    assert result['scope'] == 'caller_supplied_reference_admissions'
    assert result['complete_run_certified'] is False

    missing = events[:-1]
    with pytest.raises(ValueError):
        audit_reference_best(missing, evaluated=evaluated, selected_id='child')
    forged = deepcopy(events)
    forged[2]['metrics']['combined_score'] = 9.0
    with pytest.raises(ValueError):
        audit_reference_best(forged, evaluated=evaluated, selected_id='copy')
    wrong_tie = deepcopy(events)
    wrong_tie[-1]['best_after'] = 'tie'
    with pytest.raises(ValueError):
        audit_reference_best(wrong_tie, evaluated=evaluated, selected_id='tie')
    duplicate = deepcopy(events)
    duplicate[-1]['id'] = 'child'
    with pytest.raises(ValueError):
        audit_reference_best(duplicate, evaluated=evaluated, selected_id='child')
    copied_copy = deepcopy(events)
    copied_copy.insert(3, record('migrant', 'second-copy', **child,
                                 before='child', after='child', parent='copy'))
    with pytest.raises(ValueError):
        audit_reference_best(copied_copy, evaluated=evaluated, selected_id='child')


def test_real_upstream_admissions_and_migration_recalculate_the_same_best(monkeypatch):
    from core.openevolve_interop import Program, ProgramDatabase
    from openevolve.config import DatabaseConfig

    events, evaluated = [], {}
    original = ProgramDatabase.add
    def observed(database, program, iteration=None, target_island=None):
        before = database.best_program_id
        measurement = {'program_ref': 'sha256:' + hashlib.sha256(program.code.encode()).hexdigest(),
                       'metrics': deepcopy(program.metrics)}
        kind = 'migrant' if program.metadata.get('migrant') else ('seed' if not events else 'candidate')
        result = original(database, program, iteration=iteration, target_island=target_island)
        events.append(record(kind, program.id, **measurement, parent=program.parent_id,
                             before=before, after=database.best_program_id))
        if kind != 'migrant':
            evaluated[program.id] = measurement
        return result
    monkeypatch.setattr(ProgramDatabase, 'add', observed)
    database = ProgramDatabase(DatabaseConfig(num_islands=2, population_size=60, archive_size=25,
                                               feature_dimensions=['complexity', 'diversity'], random_seed=7))
    database.add(Program(id='seed', code='x = 1', metrics={'combined_score': 1.0}), target_island=0)
    database.add(Program(id='child', code='x = 2', parent_id='seed', generation=1,
                         metrics={'combined_score': 2.0}), target_island=0)
    database._migrate_one('child', 1)
    database.add(Program(id='tie', code='x = 3', parent_id='child', generation=2,
                         metrics={'combined_score': 2.0}), target_island=0)
    assert any(event['kind'] == 'migrant' for event in events)
    assert audit_reference_best(events, evaluated=evaluated,
                                selected_id=database.get_best_program().id)['selected_id'] == 'child'


def test_capture_fails_closed_if_host_swallows_an_admission_exception():
    from core.openevolve_interop import Program, ProgramDatabase
    from openevolve.config import DatabaseConfig

    original = ProgramDatabase.add
    with capture_reference_admissions(ProgramDatabase) as capture:
        database = ProgramDatabase(DatabaseConfig(num_islands=1, feature_dimensions=['unavailable']))
        with pytest.raises(ValueError):
            database.add(Program(id='bad', code='x = 1', metrics={'combined_score': 1.0}))
        with pytest.raises(ValueError, match='failed'):
            capture.snapshot()
    assert ProgramDatabase.add is original


def test_capture_observes_actual_seed_child_and_migration():
    from core.openevolve_interop import Program, ProgramDatabase
    from openevolve.config import DatabaseConfig

    with capture_reference_admissions(ProgramDatabase) as capture:
        database = ProgramDatabase(DatabaseConfig(num_islands=2, feature_dimensions=['complexity', 'diversity']))
        database.add(Program(id='seed', code='x=1', metrics={'combined_score': 1.0}), target_island=0)
        database.add(Program(id='child', code='x=2', parent_id='seed', generation=1,
                             metrics={'combined_score': 2.0}), iteration=1, target_island=0)
        database._migrate_one('child', 1)
        events = capture.snapshot()['events']
    measured = {event['id']: {'program_ref': event['program_ref'], 'metrics': event['metrics']}
                for event in events if event['kind'] != 'migrant'}
    assert [event['kind'] for event in events] == ['seed', 'candidate', 'migrant']
    assert events[1]['iteration'] == 1 and events[1]['target_island'] == 0
    assert events[2]['iteration'] is None and events[2]['target_island'] == 1
    report = audit_reference_best(events, evaluated=measured, selected_id='child')
    assert report['fitness'] == 2.0
    assert report['host_observed_migrations'] == [{'id': events[2]['id'], 'parent_id': 'child', 'target_island': 1}]


def test_best_reconstruction_uses_original_stage_geometry_and_candidate_identity():
    import json
    from zoo.circle_packing.geometry import validate_geometry
    from zoo.circle_packing.stage import EVALUATOR_SHA256

    seed_ref, child_ref = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
    rows = []
    def stage(request, program_ref, radius, number, prior):
        geometry = {'centers': [[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)],
                    'radii': [radius] * 26}
        encoded = json.dumps(geometry, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        result = {'stage': number, 'program_ref': program_ref, 'evaluator_ref': 'sha256:' + EVALUATOR_SHA256,
                  'status': 'ok', 'wall_seconds': 1.0, 'metrics': validate_geometry(geometry),
                  'geometry': geometry, 'geometry_ref': 'sha256:' + hashlib.sha256(encoded).hexdigest()}
        rows.extend([{'kind': 'host_stage_started', 'payload': {'request_id': request, 'program_ref': program_ref,
                      'stage': number, 'prior_id': prior}},
                     {'kind': 'host_stage_completed', 'payload': {'request_id': request, 'result': result}}])
        return result['metrics']
    seed_first, seed_second, child_first, child_second = [str(i) * 32 for i in range(1, 5)]
    stage(seed_first, seed_ref, .06, 1, None)
    seed_metrics = stage(seed_second, seed_ref, .06, 2, seed_first)
    stage(child_first, child_ref, .07, 1, None)
    child_metrics = stage(child_second, child_ref, .07, 2, child_first)
    events = [record('seed', 'seed', seed_ref, seed_metrics, None, 'seed'),
              record('candidate', 'child', child_ref, child_metrics, 'seed', 'child', parent='seed')]
    trace = {'iterations': [{'iteration': 1, 'state': 'candidate', 'child_id': 'child',
                             'program_sha256': '2' * 64}],
             'stage_bindings': [{'iteration': 1, 'request_id': child_first},
                                {'iteration': 1, 'request_id': child_second}]}
    accounting = {'iteration_accounting_complete': True, 'seed_stage_ids': [seed_first, seed_second]}
    result = audit_reference_best_from_physical(events, trace=trace, rows=rows, accounting=accounting,
                                                seed_sha256='1' * 64, selected_id='child')
    assert result['selected_id'] == 'child' and result['complete_run_certified'] is False
    assert result['candidate_iteration_and_island_verified'] is False
    forged = deepcopy(rows)
    forged[-1]['payload']['result']['metrics']['combined_score'] = 100.0
    with pytest.raises(ValueError):
        audit_reference_best_from_physical(events, trace=trace, rows=forged, accounting=accounting,
                                           seed_sha256='1' * 64, selected_id='child')
    extended = deepcopy(events)
    extended[0].update(iteration=None, target_island=None)
    extended[1].update(iteration=1, target_island=0)
    extended_trace = deepcopy(trace)
    extended_trace['iterations'][0]['target_island'] = 0
    verified = audit_reference_best_from_physical(extended, trace=extended_trace, rows=rows, accounting=accounting,
        seed_sha256='1' * 64, selected_id='child')
    assert verified['selected_id'] == 'child' and verified['candidate_iteration_and_island_verified'] is True
    extended[1]['target_island'] = 1
    with pytest.raises(ValueError):
        audit_reference_best_from_physical(extended, trace=extended_trace, rows=rows, accounting=accounting,
            seed_sha256='1' * 64, selected_id='child')


@pytest.mark.parametrize('status', ['timeout', 'failed_to_run'])
def test_first_stage_failure_reconstructs_the_upstream_zero_score(status):
    from zoo.circle_packing.stage import EVALUATOR_SHA256

    request, ref = 'a' * 32, 'sha256:' + '1' * 64
    rows = [{'kind': 'host_stage_started', 'payload': {'request_id': request, 'program_ref': ref,
                                                       'stage': 1, 'prior_id': None}},
            {'kind': 'host_stage_completed', 'payload': {'request_id': request, 'result': {
                'stage': 1, 'program_ref': ref, 'evaluator_ref': 'sha256:' + EVALUATOR_SHA256,
                'status': status, 'wall_seconds': 1.0}}}]
    metrics = {'combined_score': 0.0, 'fixture_stage_failed': 1.0}
    events = [record('seed', 'seed', ref, metrics, None, 'seed')]
    result = audit_reference_best_from_physical(events, trace={'iterations': [], 'stage_bindings': []},
        rows=rows, accounting={'iteration_accounting_complete': True, 'seed_stage_ids': [request]},
        seed_sha256='1' * 64, selected_id='seed')
    assert result['fitness'] == 0.0 and result['complete_run_certified'] is False
