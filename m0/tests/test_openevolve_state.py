"""C05 O1/O2 and cross-process continuation contracts over the real host.

Staged while C04 CI is frozen. These tests are not a passing implementation or
benchmark result. Move into m0/tests only when the C05 branch becomes active.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest

SOURCE = {
    'upstream_commit': '5153a7d74ee615b7090ec52903629870ecdacdf1',
    'vendor_manifest_ref': 'sha256:' + hashlib.sha256(b'fixture-pinned-source').hexdigest(),
}


def new_adapter(*, seed=7, **overrides):
    module_name = 'core.composition.openevolve_adapter'
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:
            raise
        pytest.fail('C05 is missing the real-host OpenEvolveAdapter', pytrace=False)
    config = dict(num_islands=4, population_size=60, archive_size=25,
                  feature_dimensions=['complexity', 'diversity'], feature_bins=10,
                  elite_selection_ratio=.3, exploration_ratio=.2, exploitation_ratio=.7,
                  migration_interval=2, migration_rate=.1, diversity_reference_size=5)
    config.update(overrides)
    return module.OpenEvolveAdapter(config, seed=seed, source_binding=SOURCE)


def measured(adapter, candidate_id, score, *, iteration, eligible=None, code=None, **metrics):
    selection = None if iteration == 0 else adapter.select(candidate_id, set(eligible))
    artifact = code if code is not None else 'value = ' + repr(candidate_id) + '\n'
    evidence_ref = 'sha256:' + hashlib.sha256((candidate_id + artifact).encode()).hexdigest()
    adapter.register(candidate_id, artifact, {'combined_score': score, **metrics},
                     evidence_ref, iteration=iteration, selection=selection)
    return selection


def test_real_cells_replace_without_losing_lineage_or_nonincumbent_sampling():
    adapter = new_adapter(num_islands=1, feature_dimensions=['novelty'],
                          exploitation_ratio=1., exploration_ratio=0., migration_interval=50)
    measured(adapter, 'root', 1., iteration=0, novelty=.1)
    measured(adapter, 'first', .6, iteration=1, eligible={'root'}, novelty=.9)
    measured(adapter, 'replacement', .8, iteration=2, eligible={'first'}, novelty=.9)
    from core.openevolve_interop import ProgramDatabase
    assert isinstance(adapter.database, ProgramDatabase)
    owners = set(adapter.database.island_feature_maps[0].values())
    assert {'root', 'replacement'} <= owners
    assert 'first' not in owners
    assert adapter.database.best_program_id == 'root'
    assert adapter.database.get('replacement').parent_id == 'first'
    # An evicted cell owner remains in original registration events.
    assert any(row['kind'] == 'register' and row['candidate_id'] == 'first'
               for row in adapter.events)
    chosen = adapter.select('next', {'replacement'})
    assert chosen['source_candidate_id'] == 'replacement'
    assert chosen['host_parent_id'] == 'replacement'


def test_actual_migration_adds_sampleable_migrant_bound_to_original_evidence():
    adapter = new_adapter(num_islands=2, migration_interval=1, migration_rate=1.,
                          feature_dimensions=['novelty'], exploitation_ratio=1., exploration_ratio=0.)
    measured(adapter, 'root', 1., iteration=0, novelty=.1)
    assert not adapter.database.islands[1]
    measured(adapter, 'child', .7, iteration=1, eligible={'root'}, novelty=.9)
    migrants = [adapter.database.get(pid) for pid in adapter.database.islands[1]]
    assert migrants and any(p.metadata.get('migrant') for p in migrants)
    assert adapter.database.last_migration_generation == 1
    selected = adapter.select('after-migration', {'root'})
    assert selected['island'] == 1
    assert selected['host_parent_id'] != 'root'
    assert selected['host_parent_id'] in adapter.database.islands[1]
    assert selected['source_candidate_id'] == 'root'
    assert selected['evidence_ref'] == 'sha256:' + hashlib.sha256(
        ("rootvalue = 'root'\n").encode()).hexdigest()


def populated_adapter():
    adapter = new_adapter()
    known = set()
    for i in range(15):
        candidate_id = f'p{(i * 7) % 15:02d}'
        code = f'def program_{i}(x):\n' + f'    value = x + {i}\n' * (i + 1) + '    return value\n'
        measured(adapter, candidate_id, .1 + i / 30, iteration=i, eligible=known, code=code)
        known.add(candidate_id)
    return adapter, known


def test_empty_eligible_projection_cannot_select_pruned_sources_or_erase_history():
    adapter, known = populated_adapter()
    before = adapter.checkpoint_state()
    with pytest.raises(ValueError, match='eligible'):
        adapter.select('blocked', set())
    assert adapter.checkpoint_state() == before
    assert known <= {e['candidate_id'] for e in adapter.events if e['kind'] == 'register'}


def test_abandoned_proposal_has_no_measured_host_program_and_retains_selection():
    adapter = new_adapter()
    measured(adapter, 'root', .4, iteration=0)
    selection = adapter.select('bad-patch', {'root'})
    adapter.abandon('bad-patch', 'patch_exhausted')
    assert adapter.database.get('bad-patch') is None
    assert adapter.events[-1]['kind'] == 'abandon'
    assert adapter.events[-1]['candidate_id'] == 'bad-patch'
    assert selection['source_candidate_id'] == 'root'
    assert adapter.select('next', {'root'})['source_candidate_id'] == 'root'


def test_host_operations_preserve_unrelated_process_rng():
    random.seed(908)
    before = random.getstate()
    adapter, known = populated_adapter()
    adapter.select('next', known)
    assert random.getstate() == before
    checkpoint = adapter.checkpoint_state()
    restored = new_adapter()
    restored.restore_state(checkpoint, adapter.events)
    assert random.getstate() == before


@pytest.mark.parametrize('field', ['rng', 'program_order', 'diversity_reference_set',
                                   'diversity_cache', 'source_binding'])
def test_checkpoint_cannot_replace_original_host_history(field):
    adapter, _ = populated_adapter()
    state = copy.deepcopy(adapter.checkpoint_state())
    if field == 'rng':
        state[field] = json.loads(json.dumps(random.Random(983).getstate()))
    elif field == 'program_order':
        state[field] = list(reversed(state[field]))
    elif field == 'diversity_reference_set':
        state[field].append('forged reference code')
    elif field == 'diversity_cache':
        assert state[field]
        state[field][0]['value'] += 1
    else:
        state[field]['vendor_manifest_ref'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError):
        new_adapter().restore_state(state, adapter.events)


def _worker(mode, checkpoint_path):
    if mode == 'make':
        adapter, known = populated_adapter()
        checkpoint_path.write_text(json.dumps({'state': adapter.checkpoint_state(),
                                              'events': adapter.events, 'known': sorted(known)}))
    else:
        saved = json.loads(checkpoint_path.read_text())
        adapter, known = new_adapter(), set(saved['known'])
        adapter.restore_state(saved['state'], saved['events'])
    selected = adapter.select('continued', known)
    db = adapter.database
    return {
        'parent': selected['host_parent_id'], 'source': selected['source_candidate_id'],
        'inspirations': selected['inspiration_host_ids'],
        'memberships': [sorted(island) for island in db.islands],
        'cells': db.island_feature_maps,
        'coords': {key: db._calculate_feature_coords(program) for key, program in db.programs.items()},
        'program_order': list(db.programs),
        'diversity_reference_set': db.diversity_reference_set,
    }


def test_fresh_process_continuation_preserves_sampling_cells_migration_and_cache(tmp_path):
    checkpoint = tmp_path / 'original.json'
    env = {**os.environ, 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    # Inherit only the ordinary test import path; no provider or candidate execution.
    def run(mode, **extra):
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), mode, str(checkpoint)],
                              env={**env, **extra}, capture_output=True, text=True, timeout=30)
    original = run('make')
    assert original.returncode == 0, original.stderr
    resumed = run('restore')
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(original.stdout) == json.loads(resumed.stdout)
    changed_environment = run('restore', PYTHONHASHSEED='1')
    assert changed_environment.returncode != 0
    assert 'hash' in changed_environment.stderr.lower()


if __name__ == '__main__':
    print(json.dumps(_worker(sys.argv[1], Path(sys.argv[2])), sort_keys=True))


def test_invalid_registration_is_atomic_and_preserves_original_rng_and_journal():
    adapter = new_adapter()
    measured(adapter, 'root', .4, iteration=0)
    selection = adapter.select('child', {'root'})
    before = adapter.checkpoint_state()
    events = adapter.events
    random.seed(2401)
    rng = random.getstate()
    with pytest.raises((TypeError, ValueError)):
        adapter.register('child', 'child', {'combined_score': float('nan')}, 'not-a-receipt',
                         iteration=1, selection=selection)
    assert adapter.checkpoint_state() == before
    assert adapter.events == events
    assert random.getstate() == rng


def test_restore_rejects_forged_original_event_without_changing_existing_host():
    adapter, _ = populated_adapter()
    state = adapter.checkpoint_state()
    events = adapter.events
    events[0]['args']['artifact'] += '\n# forged'
    restored = new_adapter()
    before = restored.checkpoint_state()
    with pytest.raises(ValueError, match='event replay differs'):
        restored.restore_state(state, events)
    assert restored.checkpoint_state() == before
