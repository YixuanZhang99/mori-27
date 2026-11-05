"""Public Framework configuration for frozen OR3 program search."""
import hashlib
import math

from core.composition.defaults import composed_profile, default_registry
from zoo.funsearch_binpacking.domain import OR3Domain

TEMPLATE = 'def priority(item, bins):\n    return -(bins - item)\n'
TEMPLATE_REF = 'sha256:' + hashlib.sha256(TEMPLATE.encode()).hexdigest()


def build_profile(data, *, seed, max_proposals, call_token_bound, timeout=30):
    if (type(max_proposals) is not int or max_proposals < 0 or
            type(call_token_bound) is not int or call_token_bound <= 0 or
            type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('finite timeout and explicit nonnegative proposals/positive token bound required')
    profile = composed_profile(name='funsearch-or3-v1')
    profile.update(schema_version=2,
        domain={'name': 'funsearch_or3', 'options': {'dataset_identity': data.identity, 'timeout': float(timeout)}},
        policy={'name': 'funsearch', 'options': {'case_ids': data.ids('dev'), 'islands': 2, 'seed': seed,
            'prompt_size': 2, 'temperature': 1.0, 'temperature_period': 10, 'metric': 'score',
            'template': TEMPLATE, 'template_ref': TEMPLATE_REF, 'function_name': 'priority', 'reset_interval': 5}},
        operators=[{'name': 'draft'}, {'name': 'funsearch'}],
        frontier={'name': 'population', 'options': {'capacity': max(2, max_proposals + 1)}},
        execution={'schema_version': 1, 'spec': {'role': 'coder', 'hypothesis_frozen': True,
            'context_projection': []}, 'constructor': {'name': 'funsearch_prompt',
            'options': {'template': TEMPLATE, 'function_name': 'priority'}}},
        skills=[{'name': 'instruction', 'options': {'text':
            'Optimize online bin packing. priority(item, bins) returns one finite numeric priority per '
            'eligible bin; the largest priority chooses the bin. bins is a NumPy vector of remaining '
            'capacities, including empty bins, and np is available. Fewer used bins is better. '
            'Change only the target function. No files, network, external data, or random state.'}}],
        admission={'name': 'metric_final', 'options': {'final_request': {
            'fidelity': 'final_audit', 'split_id': 'final_audit'}}})
    limits = {'token': (max_proposals + 1) * call_token_bound, 'node': max_proposals + 1,
              'eval_count': max_proposals + 2}
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {key: dict(limits) for key in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
            'operator': {'token': call_token_bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}}
    return profile


def registry_for(data):
    registry = default_registry()
    def validate(options):
        if (type(options) is not dict or set(options) != {'dataset_identity', 'timeout'} or
                options['dataset_identity'] != data.identity or
                type(options['timeout']) not in (int, float) or
                not math.isfinite(options['timeout']) or options['timeout'] <= 0):
            raise ValueError('OR3 requires frozen data and a finite positive timeout')
        data.validate()
    registry.register('domain', 'funsearch_or3', lambda _ctx, options: OR3Domain(
        data, template=TEMPLATE, timeout=options['timeout']), validate_options=validate)
    return registry
