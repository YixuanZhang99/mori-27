"""Frozen serial OpenEvolve circle-packing Framework composition."""
from __future__ import annotations

from core.composition.defaults import composed_profile


def build_profile(*, seed, iterations, call_token_bound, migration_interval=50):
    for name, value, minimum in (('seed', seed, 0), ('iterations', iterations, 0),
                                 ('call_token_bound', call_token_bound, 1), ('migration_interval', migration_interval, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(name + ' must be a bounded integer')
    count = iterations + 1
    profile = composed_profile(name='openevolve-circle-v1')
    profile.update(schema_version=2, domain={'name': 'native'}, executor={'name': 'inprocess'},
        policy={'name': 'openevolve', 'options': {'seed': seed, 'migration_interval': migration_interval}},
        operators=[{'name': 'draft'}, {'name': 'openevolve'}],
        frontier={'name': 'tree', 'options': {'retain_rejected': True}},
        execution={'schema_version': 1, 'spec': {'role': 'general', 'hypothesis_frozen': True,
                     'context_projection': []},
                   'constructor': {'name': 'openevolve_diff', 'options': {}}},
        admission={'name': 'metric_final', 'options': {'final_request': {
                   'fidelity': 'final_audit', 'split_id': 'final_audit'}}})
    limits = {'token': count * 2 * call_token_bound, 'node': count, 'eval_count': count * 2 + 1}
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {level: dict(limits) for level in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 2},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
            'operator': {'token': 2 * call_token_bound, 'node': 1, 'eval_count': 0},
            'final': {'token': 0, 'node': 0, 'eval_count': 1}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}}
    return profile
