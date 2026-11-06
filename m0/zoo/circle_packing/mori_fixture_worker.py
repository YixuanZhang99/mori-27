"""Named Mori controller for a frozen loopback fixture, never a live pilot.

The process is a trusted controller holding only a fixed fake credential and a
fixture campaign; candidate programs remain in the existing execution sandbox.
This entrypoint does not establish whole-cell supervision or live readiness.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


from zoo.circle_packing.mori_controller import CONFIG_FIELDS, final_measurement


def validate_config(value):
    if type(value) is not dict or set(value) != CONFIG_FIELDS or type(value['seed']) is not int or value['seed'] not in (0, 1, 2):
        raise ValueError('fixture requires its exact configuration and declared seed')
    try:
        url = urlsplit(value['base_url'])
        if url.scheme != 'http' or url.hostname not in {'127.0.0.1', '::1'} or not url.port or \
                url.username or url.password or url.query or url.fragment:
            raise ValueError('fixture requires an explicit loopback service')
    except (TypeError, ValueError) as error:
        raise ValueError('fixture requires an explicit loopback service') from error
    for name in ('source', 'runtime', 'ledger', 'clock', 'output'):
        if type(value[name]) is not str or not Path(value[name]).is_absolute():
            raise ValueError('fixture paths must be absolute')
    return value


def prepare_fixture_authorities(config, *, ledger):
    """Restore the existing fixture clock and its bound source/runtime."""
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.frozen_source import verify_frozen_source
    from zoo.circle_packing.pilot_plan import validate_draft_cell
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    config = validate_config(config)
    if type(ledger) is not CampaignBudget or not ledger.is_fixture_campaign() or \
            Path(config['ledger']).resolve(strict=True) != ledger.path.resolve(strict=True) or \
            config['campaign_id'] != ledger.manifest_binding()['campaign_id']:
        raise ValueError('fixture authorities require the original fixture campaign')
    plan, ref, seed = config['plan'], config['ref'], config['seed']
    source, runtime = Path(config['source']), Path(config['runtime'])
    clock_path = Path(config['clock'])
    if clock_path.is_symlink() or not clock_path.is_file():
        raise ValueError('fixture requires its original cell clock')
    if type(plan) is dict and type(plan.get('schema_version')) is int and plan['schema_version'] == 3:
        cell_id = f"{plan.get('experiment_id')}--mori-{seed}"
        validate_draft_cell(ledger, plan, cell_id, expected_plan_ref=ref)
        runner = SandboxRunner.for_fixture_continuation(ledger, draft=plan,
            source_directory=source.parent.parent, runtime_directory=runtime.parent,
            base_python='/usr/bin/python3.12')
        if source != source.parent.parent / 'source/m0' or runner.runtime_root != runtime:
            raise ValueError('fixture source or runtime differs from its bound bundle')
    else:
        cell_id = f'mori-{seed}'
        verify_frozen_source(ledger, plan, snapshot=source.parent, manifest=config['source_manifest'],
                             expected_plan_ref=ref, expected_campaign_id=config['campaign_id'])
        runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=config['runtime_manifest'],
                                                    base_python='/usr/bin/python3.12')
    clock = CellDeadline.restore(ContinuationStore(clock_path), lifecycle=CellLifecycle(ledger),
        cell_id=cell_id, plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    return clock, runner


def run(config):
    config = validate_config(config)
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.circle_packing.mori_controller import build_controller
    from zoo.circle_packing.reproducibility import require_hash_seed_zero
    from zoo.circle_packing.runner import TASK
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider

    ledger = CampaignBudget(config['ledger'])
    if not ledger.is_fixture_campaign():
        raise ValueError('fixture controller requires a marked unused fixture campaign')
    require_hash_seed_zero()
    source, runtime = Path(config['source']), Path(config['runtime'])
    if source.resolve(strict=True) != Path(__file__).resolve().parents[2] or \
            str(runtime / 'bin' / 'python') != sys.executable:
        raise ValueError('fixture controller must use the original frozen source and runtime')
    plan = config['plan']
    clock, runner = prepare_fixture_authorities(config, ledger=ledger)
    framework, provider, profile, adapters = build_controller(
        config, ledger=ledger, clock=clock, runner=runner, api_key='fixture-only-secret')
    outcome = framework.evolve(TASK)
    def forbidden(*args, **kwargs):
        raise AssertionError('fixture replay attempted external work')
    original_provider, original_evaluate = GovernedCNYProvider.perform_request, CirclePackingDomain.evaluate
    try:
        GovernedCNYProvider.perform_request = forbidden
        CirclePackingDomain.evaluate = forbidden
        certificate = framework.replay(adapter_factory=adapters)['replay_certificate']
    finally:
        GovernedCNYProvider.perform_request, CirclePackingDomain.evaluate = original_provider, original_evaluate
    import core.loop
    import openevolve
    from zoo.circle_packing import governed
    measurement = final_measurement(outcome['reporting']['final_audit'], outcome['best_candidate_id'],
                                    plan['public_range_sum_radii'])
    return {'mode': 'fixture', 'performance_claim': False, 'final_measurement': measurement,
            'limits': profile['budget']['options']['limits']['global'],
            'model_config': {'model': provider.manifest_binding()['requested_model'],
                             'max_completion_tokens': provider.manifest_binding()['max_completion_tokens']},
            'candidate': outcome['best_candidate_id'], 'final_state': outcome['reporting']['final_audit']['state'],
            'replay_passed': certificate['passed'], 'source': core.loop.__file__,
            'governed_source': governed.__file__, 'vendor_source': openevolve.__file__, 'executable': sys.executable}


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: python -m zoo.circle_packing.mori_fixture_worker CONFIG')
    config = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(run(config), sort_keys=True))


if __name__ == '__main__':
    main()
