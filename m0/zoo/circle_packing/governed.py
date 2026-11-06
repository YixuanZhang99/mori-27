"""Compose the existing CNY governance bridge with the circle recipe.

This factory does not start runs, load credentials, or make live calls.
"""
from __future__ import annotations

from pathlib import Path

from core.composition.defaults import default_registry
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.profile import build_profile
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


def governed_setup(output, *, ledger, api_key, seed, iterations, base_url=None,
                   max_completion_tokens=16384):
    policy = ledger.manifest_binding()
    snapshot = ledger.snapshot()
    if snapshot.get('pending_calls') or snapshot.get('protection_breaches') or \
            snapshot.get('journal_schema_version') != 2:
        raise ValueError('existing campaign must be quiescent and governance enabled')
    root = Path(output).resolve()
    def fresh():
        return GovernedCNYProvider(policy['model'], base_url or policy['provider_base_url'],
            campaign_binding=policy, api_key=api_key, max_completion_tokens=max_completion_tokens,
            phase_call_limits={'operator': 2, 'evaluation': 0}, reasoning_effort='low',
            message_mode='openevolve_v1')
    provider = fresh()
    bound = provider.governance_binding()['call_bound']['units']['token']
    profile = build_profile(seed=seed, iterations=iterations, call_token_bound=bound, migration_interval=2)
    registry = default_registry()
    registry.install_external_bridge('cny_invocation_v1', lambda: CNYInvocationBridge(ledger))
    registry.register('provider', 'circle-control', lambda _ctx, _opts: fresh(),
                      governance=fresh().governance_binding())
    registry.register('domain', 'circle-control', lambda ctx, _opts: CirclePackingDomain(
        root / 'controls' / ctx.invocation_scope['slot_id'], runner=SandboxRunner()),
        governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    reservations = {'operator': {'token': 2 * bound, 'node': 1, 'eval_count': 0},
                    'evaluation': {'token': 0, 'node': 0, 'eval_count': 2}}
    limits = profile['budget']['options']['limits']['global']
    for unit in limits:
        limits[unit] += sum(part[unit] for part in reservations.values())
    profile['governance'] = {'schema_version': 1, 'controls': {'after_main_cycles': [0], 'seed': seed,
        'provider': {'name': 'circle-control'}, 'domain': {'name': 'circle-control'},
        'operator': {'name': 'draft'}, 'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': reservations}}
    return profile, registry, provider
