"""Prepare the trusted Mori controller for a frozen non-fixture campaign.

This function neither starts the search nor authorizes a live pilot. Its
caller must enforce the completed pilot gate and supervise the whole cell.
"""
from __future__ import annotations

from pathlib import Path
import sys

from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_source import verify_frozen_source
from zoo.circle_packing.mori_controller import CONFIG_FIELDS, build_controller
from zoo.circle_packing.reproducibility import require_hash_seed_zero
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner


def prepare_live_controller(config, *, api_key):
    """Bind original campaign, frozen code/runtime and clock before composition."""
    if type(config) is not dict or set(config) != CONFIG_FIELDS or \
            type(config['seed']) is not int or config['seed'] not in (0, 1, 2):
        raise ValueError('live controller requires its exact cell configuration')
    if any(type(config[name]) is not str or not Path(config[name]).is_absolute()
           for name in ('source', 'runtime', 'ledger', 'clock', 'output')):
        raise ValueError('live controller paths must be absolute')
    ledger = CampaignBudget(config['ledger'])
    if ledger.is_fixture_campaign():
        raise ValueError('live controller requires a non-fixture campaign')
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('live controller requires an in-memory credential')
    source, runtime = Path(config['source']), Path(config['runtime'])
    if source.resolve(strict=True) != Path(__file__).resolve().parents[2] or \
            str(runtime / 'bin' / 'python') != sys.executable:
        raise ValueError('live controller must use its frozen source and runtime')
    clock_path = Path(config['clock'])
    if clock_path.is_symlink() or not clock_path.is_file():
        raise ValueError('live controller requires its original cell clock')
    plan, ref = config['plan'], config['ref']
    verify_frozen_source(ledger, plan, snapshot=source.parent, manifest=config['source_manifest'],
                         expected_plan_ref=ref, expected_campaign_id=config['campaign_id'])
    require_hash_seed_zero()
    clock = CellDeadline.restore(ContinuationStore(clock_path), lifecycle=CellLifecycle(ledger),
        cell_id=f"mori-{config['seed']}", plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=config['runtime_manifest'],
                                                base_python='/usr/bin/python3.12')
    return build_controller(config, ledger=ledger, clock=clock, runner=runner, api_key=api_key)
