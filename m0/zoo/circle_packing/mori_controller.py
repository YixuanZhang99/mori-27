"""Build a governed Mori controller from explicitly supplied authorities.

This composition helper does not authorize or start a live pilot. Credentials
stay in memory and must never be placed in the configuration or evidence.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

CONFIG_FIELDS = {'plan', 'ref', 'runtime_manifest', 'source_manifest', 'source', 'runtime', 'ledger',
                 'clock', 'output', 'base_url', 'campaign_id', 'seed'}


def build_controller(config, *, ledger, clock, runner, api_key):
    """Compose Framework and independent replay adapters for the frozen cell."""
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('controller requires an in-memory credential')
    if type(config) is not dict or set(config) != CONFIG_FIELDS:
        raise ValueError('controller requires an exact credential-free configuration')
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    try:
        if type(ledger) is not CampaignBudget or type(config['ledger']) is not str or \
                not Path(config['ledger']).is_absolute() or Path(config['ledger']).is_symlink() or \
                Path(config['ledger']).resolve(strict=True) != ledger.path.resolve(strict=True):
            raise ValueError('controller ledger differs from its configuration')
    except (OSError, RuntimeError) as error:
        raise ValueError('controller ledger differs from its configuration') from error
    policy = ledger.manifest_binding()
    if ledger.is_fixture_campaign():
        try:
            url = urlsplit(config['base_url'])
            if url.scheme != 'http' or url.hostname not in {'127.0.0.1', '::1'} or not url.port or \
                    url.username or url.password or url.query or url.fragment:
                raise ValueError('fixture controller requires a loopback provider')
        except (TypeError, ValueError) as error:
            raise ValueError('fixture controller requires a loopback provider') from error
    elif config['base_url'] != policy['provider_base_url']:
        raise ValueError('controller requires the original campaign provider')
    if config['campaign_id'] != policy['campaign_id']:
        raise ValueError('controller campaign identity differs')
    from zoo.circle_packing.cell_deadline import CellDeadline
    try:
        if type(clock) is not CellDeadline or clock._lifecycle.ledger is not ledger or \
                type(config['seed']) is not int or config['seed'] not in (0, 1, 2) or \
                clock._record['cell_id'] != f"mori-{config['seed']}" or \
                clock._record['plan_ref'] != config['ref'] or type(config['clock']) is not str or \
                Path(config['clock']).resolve(strict=True) != clock._store.path.resolve(strict=True):
            raise ValueError('controller clock differs from its original cell')
    except (OSError, RuntimeError) as error:
        raise ValueError('controller clock differs from its original cell') from error
    from core.loop import Framework, LoopConfig
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.circle_packing.governed import governed_setup

    plan, ref, seed = config['plan'], config['ref'], config['seed']
    root = Path(config['output'])
    options = dict(ledger=ledger, api_key=api_key, seed=seed, iterations=plan['iterations'],
        base_url=config['base_url'], max_completion_tokens=plan['max_completion_tokens'],
        total_token_ceiling=plan['limits']['token'], cell_deadline=clock,
        draft_plan=plan, expected_plan_ref=ref, runner=runner)
    profile, registry, provider = governed_setup(root, **options)
    cfg = LoopConfig(max_generations=plan['iterations'], total_budget=plan['limits']['token'],
                     reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(root / 'domain', runner=runner.independent_runner())
    framework = Framework.from_profile(profile, provider, domain, cfg, str(root / 'framework'),
                                       component_registry=registry)

    def adapters(path, store):
        _, _, replay_provider = governed_setup(root, **options)
        return replay_provider, CirclePackingDomain(root / 'replay-domain', runner=runner.independent_runner())

    return framework, provider, profile, adapters
