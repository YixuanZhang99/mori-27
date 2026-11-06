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
                   max_completion_tokens=16384, total_token_ceiling=None,
                   cell_deadline=None, draft_plan=None, expected_plan_ref=None, runner=None, recorded_only=False):
    if type(recorded_only) is not bool or recorded_only and (api_key is not None or cell_deadline is not None):
        raise ValueError('recorded-only setup cannot receive a live key or deadline')
    policy = ledger.manifest_binding()
    snapshot = ledger.snapshot()
    if snapshot.get('pending_calls') or snapshot.get('protection_breaches') or \
            snapshot.get('journal_schema_version') != 2:
        raise ValueError('existing campaign must be quiescent and governance enabled')
    pilot = ledger.circle_pilot_binding()
    binding = ledger.circle_runtime_binding()
    if not recorded_only and pilot is not None and not ledger.is_fixture_campaign() and \
            not pilot.get('require_single_run'):
        raise ValueError('live governed setup requires a single-run pilot')
    if not recorded_only and pilot is not None and not ledger.is_fixture_campaign():
        from zoo.circle_packing.mori_live_worker import _require_live_gate
        _require_live_gate({'seed': seed})
    if pilot is not None and pilot.get('require_runtime') and binding is None:
        raise ValueError('frozen pilot requires a bound runtime before setup')
    if runner is not None and type(runner) is not SandboxRunner:
        raise ValueError('control runner requires a trusted sandbox')
    if binding is not None:
        if runner is None or runner._campaign_runtime is None or runner._campaign_runtime[0] is not ledger or \
                runner.manifest_binding.get('runtime_ref') != binding['runtime_ref']:
            raise ValueError('control runner must use the original campaign runtime')
    elif runner is not None and runner._campaign_runtime is not None:
        raise ValueError('control runtime is not bound to this campaign')
    if not recorded_only and pilot is not None and pilot.get('require_runtime') and any(
            value is None for value in (cell_deadline, draft_plan, expected_plan_ref)):
        raise ValueError('frozen pilot setup requires its original cell clock')
    root = Path(output).resolve()
    def fresh():
        return GovernedCNYProvider(policy['model'], base_url or policy['provider_base_url'],
            campaign_binding=policy, api_key=api_key, max_completion_tokens=max_completion_tokens,
            phase_call_limits={'operator': 2, 'evaluation': 0}, reasoning_effort='low',
            message_mode='openevolve_v1')
    provider = fresh()
    bound = provider.governance_binding()['call_bound']['units']['token']
    profile = build_profile(seed=seed, iterations=iterations, call_token_bound=bound, migration_interval=2)
    deadline_binding = None
    if any(value is not None for value in (cell_deadline, draft_plan, expected_plan_ref)):
        from zoo.circle_packing.cell_deadline import CellDeadline
        from zoo.circle_packing.pilot_plan import validate_draft_cell
        if type(cell_deadline) is not CellDeadline or draft_plan is None or expected_plan_ref is None:
            raise ValueError('timed Mori setup requires clock and independently pinned draft')
        cell_id = f'mori-{seed}'
        binding = validate_draft_cell(ledger, draft_plan, cell_id, expected_plan_ref=expected_plan_ref)
        if cell_deadline._lifecycle.ledger is not ledger or cell_deadline._record['cell_id'] != cell_id or \
                cell_deadline._record['plan_ref'] != binding['plan_ref'] or \
                cell_deadline._record['seconds'] != binding['wallclock_seconds']:
            raise ValueError('Mori clock differs from original campaign and draft cell')
        deadline_binding = (cell_deadline, draft_plan, expected_plan_ref, cell_id)
    registry = default_registry()
    registry.install_external_bridge('cny_invocation_v1', lambda: CNYInvocationBridge(
        ledger, cell_deadline_binding=deadline_binding, recorded_only=recorded_only))
    registry.register('provider', 'circle-control', lambda _ctx, _opts: fresh(),
                      governance=fresh().governance_binding())
    registry.register('domain', 'circle-control', lambda ctx, _opts: CirclePackingDomain(
        root / 'controls' / ctx.invocation_scope['slot_id'],
        runner=SandboxRunner() if runner is None else runner.independent_runner()),
        governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    reservations = {'operator': {'token': 2 * bound, 'node': 1, 'eval_count': 0},
                    'evaluation': {'token': 0, 'node': 0, 'eval_count': 2}}
    limits = profile['budget']['options']['limits']['global']
    for unit in limits:
        limits[unit] += sum(part[unit] for part in reservations.values())
    if total_token_ceiling is not None:
        if type(total_token_ceiling) is not int or not 4 * bound <= total_token_ceiling <= limits['token']:
            raise ValueError('token ceiling must fit protected control and one main operation')
        limits['token'] = total_token_ceiling
    profile['governance'] = {'schema_version': 1, 'controls': {'after_main_cycles': [0], 'seed': seed,
        'provider': {'name': 'circle-control'}, 'domain': {'name': 'circle-control'},
        'operator': {'name': 'draft'}, 'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': reservations}}
    return profile, registry, provider
