"""Trusted Mori host; the live pilot gate remains closed until completed."""
from __future__ import annotations

import os


def _prepare(config, *, api_key):
    from zoo.circle_packing.mori_live_controller import prepare_live_controller
    return prepare_live_controller(config, api_key=api_key)


def _take_credential():
    api_key = os.environ.pop('DEEPSEEK_API_KEY', None)
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('live host requires an in-memory provider credential')
    return api_key


def prepare(config):
    """Remove the provider key from the environment before preparing children."""
    return _prepare(config, api_key=_take_credential())


def _require_live_gate(config):
    # The draft remains non-executable until the complete paired-cell pilot
    # readiness and independent verification are implemented.
    raise ValueError('live pilot gate is not complete')


def run(config):
    """Run the prepared controller only after the live gate is satisfied."""
    api_key = _take_credential()
    _require_live_gate(config)
    framework, provider, profile, adapters = _prepare(config, api_key=api_key)
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.circle_packing.mori_controller import final_measurement
    from zoo.circle_packing.runner import TASK
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    outcome = framework.evolve(TASK)
    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay attempted external work')
    original_provider, original_evaluate = GovernedCNYProvider.perform_request, CirclePackingDomain.evaluate
    try:
        GovernedCNYProvider.perform_request = forbidden
        CirclePackingDomain.evaluate = forbidden
        replay = framework.replay(adapter_factory=adapters)['replay_certificate']
    finally:
        GovernedCNYProvider.perform_request, CirclePackingDomain.evaluate = original_provider, original_evaluate
    final = outcome['reporting']['final_audit']
    return {'mode': 'live', 'performance_claim': False, 'candidate': outcome['best_candidate_id'],
            'final_state': final['state'],
            'final_measurement': final_measurement(final, outcome['best_candidate_id'],
                                                   config['plan']['public_range_sum_radii']),
            'replay_passed': replay['passed'], 'limits': profile['budget']['options']['limits']['global'],
            'model_config': {'model': provider.manifest_binding()['requested_model'],
                             'max_completion_tokens': provider.manifest_binding()['max_completion_tokens']}}
