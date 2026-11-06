"""Trusted component factories for the serial adapted OpenEvolve recipe."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from core.composition.construction_recipes import DEFAULT_ROLES
from core.composition.openevolve_adapter import OpenEvolveAdapter
from core.composition.openevolve_construction import OpenEvolveMaterializer
from core.composition.openevolve_policy import OpenEvolvePolicy
from core.x1.checkpoint import payload_digest

_ROOT = Path(__file__).resolve().parents[2] / 'vendor/openevolve'
_SEED = _ROOT / 'examples/circle_packing/initial_program.py'
_DATABASE = _ROOT / 'openevolve/database.py'
_SEED_SHA = '9d87e817e4039a01c79362a133f1f057f315517be98996e27cfd9d90d2189188'
_DATABASE_SHA = 'b74b36897346df1bb166c95ddfb4c5319ac69af4d6c0e2b4d848c7b4f797c2ac'


def _frozen_source(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('pinned OpenEvolve source changed')
    return raw


def policy_options(options):
    if type(options) is not dict or set(options) != {'seed', 'migration_interval'} \
            or type(options['seed']) is not int or options['seed'] < 0 \
            or type(options['migration_interval']) is not int or options['migration_interval'] < 1:
        raise ValueError('OpenEvolve requires nonnegative seed and positive migration interval')
    _frozen_source(_DATABASE, _DATABASE_SHA)


def policy_factory(context, options):
    policy_options(options)
    config = {'num_islands': 4, 'population_size': 60, 'archive_size': 25,
              'feature_dimensions': ['complexity', 'diversity'], 'feature_bins': 10,
              'elite_selection_ratio': .3, 'exploration_ratio': .2, 'exploitation_ratio': .7,
              'migration_interval': options['migration_interval'], 'migration_rate': .1}
    binding = {'upstream_commit': '5153a7d74ee615b7090ec52903629870ecdacdf1',
               'database_ref': 'sha256:' + _DATABASE_SHA}
    return OpenEvolvePolicy(context.scope_context, adapter=OpenEvolveAdapter(
        config, seed=options['seed'], source_binding=binding))


def constructor_options(options):
    if type(options) is not dict or options:
        raise ValueError('OpenEvolve constructor uses only the pinned seed')
    _frozen_source(_SEED, _SEED_SHA)


def constructor_factory(context, options):
    constructor_options(options)
    return OpenEvolveMaterializer(DEFAULT_ROLES, seed_program=_frozen_source(_SEED, _SEED_SHA).decode('utf-8'),
                                  require_bound_prompt=True)


class OpenEvolveRecipeOperator:
    measured_cost_units = ('token', 'node', 'eval_count')

    def recipe(self, request):
        if len(request.parents) != 1 or len(request.evidence) != 1:
            raise ValueError('OpenEvolve mutation requires one measured parent')
        data = request.strategy.get('openevolve')
        if type(data) is not dict or set(data) != {'selection', 'materialization'}:
            raise ValueError('OpenEvolve mutation requires a journal-bound prompt')
        selection, prompt = data['selection'], data['materialization']
        parent, evidence = request.parents[0], request.evidence[0]
        if selection['source_candidate_id'] != parent.candidate.id or evidence.candidate_id != parent.candidate.id \
                or prompt['selection'] != selection or prompt['primary']['artifact'] != parent.artifact \
                or prompt['primary']['score'] != evidence.eval_result.metrics['dev/score']:
            raise ValueError('OpenEvolve prompt differs from its selected parent and evidence')
        messages = {'system': prompt['system'], 'user': prompt['user']}
        if prompt['prompt_ref'] != 'sha256:' + payload_digest(messages):
            raise ValueError('OpenEvolve vendor message reference differs')
        bound = {**messages, 'input_ref': prompt['input_ref'], 'prompt_ref': prompt['prompt_ref'],
                 'selection_ref': 'sha256:' + payload_digest(selection)}
        return {'kind': 'reflective', 'task_desc': request.task_desc,
                'parent_artifacts': [{'candidate_id': parent.candidate.id, 'artifact': parent.artifact}],
                'instructions': [json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(',', ':'))],
                'comparison': {parent.candidate.id: evidence.eval_result.metrics['dev/score']}}


def register_openevolve(registry):
    registry.register('policy', 'openevolve', policy_factory, validate_options=policy_options)
    registry.register('operator', 'openevolve', lambda _context, _options: OpenEvolveRecipeOperator(),
                      execution={'schema_version': 1, 'contract': 'recipe_v1'})
    registry.register('constructor', 'openevolve_diff', constructor_factory, validate_options=constructor_options,
        execution={'schema_version': 1, 'roles': {key: asdict(role) for key, role in DEFAULT_ROLES.items()}})
