"""C05 host adapter under development; not registered with the Framework."""
from __future__ import annotations

import copy
import json
import random

from core.composition.contracts import json_copy
from core.openevolve_interop import DatabaseConfig, ProgramDatabase


class OpenEvolveAdapter:
    """Own the pinned host and isolate its global RNG from other components.

    Host registration, selection, and journal-bound restoration are implemented;
    policy wiring and production acceptance remain in progress.
    """

    def __init__(self, config: dict, *, seed: int, source_binding: dict):
        if type(seed) is not int or seed < 0:
            raise ValueError('OpenEvolve seed must be a nonnegative integer')
        self._seed = seed
        self._sources = {}
        self._pending = None
        self.config = json_copy(config)
        self.source_binding = json_copy(source_binding)
        if not self.source_binding:
            raise ValueError('OpenEvolve source binding is required')
        prohibited = {'db_path', 'in_memory', 'random_seed', 'novelty_llm',
                      'embedding_model', 'embedding_api_base', 'artifacts_base_path'}
        if prohibited & self.config.keys():
            raise ValueError('OpenEvolve host side effects are not configurable')
        host_config = DatabaseConfig(**self.config, random_seed=seed, db_path=None,
                                     in_memory=True, novelty_llm=None,
                                     embedding_model=None, embedding_api_base=None,
                                     artifacts_base_path=None)
        unrelated_rng = random.getstate()
        try:
            self.database = ProgramDatabase(host_config)
            self._host_rng = random.getstate()
        finally:
            random.setstate(unrelated_rng)
        self._events = []

    @property
    def events(self):
        return copy.deepcopy(self._events)

    def _state(self):
        from core.openevolve_interop import _config_payload
        from core.x1.checkpoint import payload_digest
        db = self.database
        return {'database': {'config': _config_payload(db.config, len(db.islands), db.feature_scaling_method),
                    'programs': [db.programs[k].to_dict() for k in sorted(db.programs)],
                    'state': {'island_feature_maps': copy.deepcopy(db.island_feature_maps),
                              'islands': [sorted(x) for x in db.islands], 'archive': sorted(db.archive),
                              'best_program_id': db.best_program_id, 'island_best_programs': list(db.island_best_programs),
                              'last_iteration': db.last_iteration, 'current_island': db.current_island,
                              'island_generations': list(db.island_generations),
                              'last_migration_generation': db.last_migration_generation,
                              'feature_stats': db._serialize_feature_stats()}},
                'rng': json.loads(json.dumps(self._host_rng)), 'program_order': list(db.programs),
                'diversity_reference_set': list(db.diversity_reference_set),
                'diversity_cache': [dict(key=k, **copy.deepcopy(v)) for k, v in db.diversity_cache.items()],
                'source_binding': copy.deepcopy(self.source_binding),
                'sources': copy.deepcopy(self._sources), 'pending': copy.deepcopy(self._pending),
                'hash_fingerprint': hash('mori-openevolve-host-v1'),
                'events_ref': payload_digest(self._events)}

    def checkpoint_state(self):
        return self._state()

    def _apply_unchecked(self, kind, args, replay_tape=None):
        import contextlib
        import types
        import uuid
        import time
        from unittest.mock import patch
        from core.openevolve_interop import Program
        import openevolve.database as host
        from core.x1.checkpoint import payload_digest

        tape, index = [], 0
        def take(name, fn):
            nonlocal index
            if replay_tape is None:
                value = fn()
                tape.append([name, value])
            else:
                if index >= len(replay_tape) or replay_tape[index][0] != name:
                    raise ValueError('host nondeterminism journal differs')
                value = replay_tape[index][1]
                tape.append([name, value]); index += 1
            return value
        class RecordedProgram(Program):
            def __init__(self, *a, **kw):
                if 'timestamp' not in kw:
                    kw['timestamp'] = take('time', time.time)
                super().__init__(*a, **kw)
        time_proxy = types.SimpleNamespace(time=lambda: take('time', time.time))
        uuid_proxy = types.SimpleNamespace(uuid4=lambda: take('uuid', lambda: str(uuid.uuid4())))
        before = payload_digest(self._state())
        saved_rng = random.getstate()
        random.setstate(self._host_rng)
        try:
            with patch.object(host, 'time', time_proxy), patch.object(host, 'uuid', uuid_proxy), patch.object(host, 'Program', RecordedProgram):
                result = self._perform(kind, args, RecordedProgram)
                if replay_tape is not None and index != len(replay_tape):
                    raise ValueError('unused host nondeterminism journal')
                self._host_rng = random.getstate()
        finally:
            random.setstate(saved_rng)
        event = {'kind': kind, 'candidate_id': args['candidate_id'], 'args': json_copy(args),
                 'tape': tape, 'before_ref': before, 'result': json_copy(result)}
        self._events.append(event)
        event['after_ref'] = payload_digest(self._state())
        return copy.deepcopy(result)

    def _apply(self, kind, args, replay_tape=None):
        # Reject non-JSON arguments before the host can mutate state.
        args = json_copy(args)
        prior = self.events
        try:
            return self._apply_unchecked(kind, args, replay_tape)
        except Exception:
            rebuilt = type(self)(self.config, seed=self._seed, source_binding=self.source_binding)
            for event in prior:
                rebuilt._apply_unchecked(event['kind'], event['args'], event['tape'])
                if rebuilt._events[-1] != event:
                    raise ValueError('cannot restore host after failed operation')
            self.__dict__.update(rebuilt.__dict__)
            raise

    def register(self, candidate_id, artifact, metrics, evidence_ref, *, iteration, selection):
        import re
        if not isinstance(evidence_ref, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', evidence_ref):
            raise ValueError('canonical original evidence reference required')
        if type(artifact) is not str or not artifact or type(metrics) is not dict:
            raise ValueError('measured artifact and metrics required')
        return self._apply('register', dict(candidate_id=candidate_id, artifact=artifact,
                           metrics=metrics, evidence_ref=evidence_ref, iteration=iteration,
                           selection=selection))

    def select(self, candidate_id, eligible_ids):
        if not eligible_ids:
            raise ValueError('no eligible host source remains')
        return self._apply('select', dict(candidate_id=candidate_id, eligible_ids=sorted(eligible_ids)))

    def abandon(self, candidate_id, reason):
        return self._apply('abandon', dict(candidate_id=candidate_id, reason=reason))

    def _perform(self, kind, args, Program):
        db = self.database
        candidate = args['candidate_id']
        if type(candidate) is not str or not candidate:
            raise ValueError('candidate identity required')
        if kind == 'register':
            if candidate in self._sources:
                raise ValueError('candidate already registered')
            selection = args['selection']
            if self._sources and (self._pending is None or self._pending != selection or self._pending['candidate_id'] != candidate):
                raise ValueError('registration requires its pending selection')
            if not self._sources and (selection is not None or args['iteration'] != 0):
                raise ValueError('initial program requires zero iteration and no selection')
            parent = selection['host_parent_id'] if selection else None
            island = selection['island'] if selection else 0
            program = Program(id=candidate, code=args['artifact'], parent_id=parent,
                              metrics=args['metrics'], generation=(db.programs[parent].generation + 1 if parent else 0))
            db.add(program, iteration=args['iteration'], target_island=island)
            self._sources[candidate] = {'candidate_id': candidate, 'evidence_ref': args['evidence_ref']}
            self._pending = None
            if selection is not None:
                db.increment_island_generation(island)
                if db.should_migrate():
                    db.migrate_programs()
                for ident, migrant in db.programs.items():
                    if ident not in self._sources:
                        if migrant.parent_id not in self._sources:
                            raise ValueError('unbound migrant source')
                        self._sources[ident] = copy.deepcopy(self._sources[migrant.parent_id])
                db.next_island()
            return {'candidate_id': candidate, 'island': island}
        if kind == 'select':
            if self._pending is not None:
                raise ValueError('pending selection must be settled')
            eligible = set(args['eligible_ids'])
            allowed = {key for key in db.programs if key in self._sources and self._sources[key]['candidate_id'] in eligible}
            if not allowed:
                raise ValueError('no eligible host source remains')
            # Selection sees only eligible sources, while the authoritative history stays intact.
            view = copy.deepcopy(db)
            view.programs = {k: v for k, v in view.programs.items() if k in allowed}
            for island in view.islands:
                island.intersection_update(allowed)
            view.archive.intersection_update(allowed)
            view.island_feature_maps = [{k: v for k, v in row.items() if v in allowed} for row in view.island_feature_maps]
            view.island_best_programs = [v if v in allowed else None for v in view.island_best_programs]
            if view.best_program_id not in allowed:
                view.best_program_id = None
            island = db.current_island
            parent, inspirations = view.sample_from_island(island)
            for ident, created in view.programs.items():
                if ident not in db.programs:
                    if created.parent_id not in self._sources:
                        raise ValueError('host selection generated an unbound parent')
                    db.programs[ident] = created
                    for index, members in enumerate(view.islands):
                        if ident in members:
                            db.islands[index].add(ident)
                    self._sources[ident] = copy.deepcopy(self._sources[created.parent_id])
            db.diversity_cache = view.diversity_cache
            db.diversity_reference_set = view.diversity_reference_set
            db.feature_stats = view.feature_stats
            if parent.id not in self._sources:
                raise ValueError('host selection generated an unbound parent')
            self._pending = {'candidate_id': candidate, 'host_parent_id': parent.id,
                             'source_candidate_id': self._sources[parent.id]['candidate_id'],
                             'evidence_ref': self._sources[parent.id]['evidence_ref'],
                             'island': island, 'inspiration_host_ids': [p.id for p in inspirations]}
            return self._pending
        if kind == 'abandon':
            if self._pending is None or self._pending['candidate_id'] != candidate:
                raise ValueError('no matching selection to abandon')
            self._pending = None
            return {'candidate_id': candidate, 'reason': args['reason']}
        raise ValueError('unknown host event')

    def restore_state(self, state, original_events):
        if state.get('hash_fingerprint') != hash('mori-openevolve-host-v1'):
            raise ValueError('OpenEvolve process hash fingerprint differs')
        other = type(self)(self.config, seed=self._seed, source_binding=self.source_binding)
        for event in original_events:
            other._apply(event['kind'], event['args'], event['tape'])
            if other._events[-1] != event:
                raise ValueError('host event replay differs from original')
        if other.checkpoint_state() != state:
            raise ValueError('checkpoint differs from original host events')
        self.__dict__.update(other.__dict__)
