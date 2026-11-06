"""Start one frozen live cell only after the paired-pilot gate is complete."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def start_live_cell(arm, config, *, directory, api_key):
    """Start one original cell clock, then launch its bounded trusted host."""
    if arm == 'mori':
        from zoo.circle_packing.mori_live_worker import _require_live_gate
        _require_live_gate(config)
        from zoo.circle_packing.mori_controller import CONFIG_FIELDS
        from zoo.circle_packing.mori_supervisor import launch_live_controller as launch
        fields = CONFIG_FIELDS
    elif arm == 'vendor':
        from zoo.circle_packing.host_runtime import _require_reference_live_gate
        _require_reference_live_gate()
        from zoo.circle_packing.reference_live_worker import REFERENCE_CONFIG_FIELDS
        from zoo.circle_packing.mori_supervisor import launch_reference_live_controller as launch
        fields = REFERENCE_CONFIG_FIELDS
    else:
        raise ValueError('live cell arm must be mori or vendor')
    path_names = ('source', 'runtime', 'ledger', 'clock', 'output') + \
        (('worker_directory', 'workspace') if arm == 'vendor' else ())
    if type(config) is not dict or set(config) != fields or type(config['seed']) is not int or \
            config['seed'] not in (0, 1, 2) or type(api_key) is not str or not api_key.strip() or \
            any(type(config[name]) is not str or not Path(config[name]).is_absolute()
                for name in path_names) or \
            not Path(directory).is_absolute():
        raise ValueError('live cell requires its exact configuration and in-memory credential')
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.pilot_plan import validate_draft_cell
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget(config['ledger'])
    if ledger.is_fixture_campaign() or config['campaign_id'] != ledger.manifest_binding()['campaign_id'] or \
            config['base_url'] != ledger.manifest_binding()['provider_base_url']:
        raise ValueError('live cell requires its original non-fixture campaign')
    cell = f"{arm}-{config['seed']}"
    binding = validate_draft_cell(ledger, config['plan'], cell, expected_plan_ref=config['ref'])
    state = ledger.snapshot()
    if state['pending_calls'] or state['protected_micro_cny'] or state['protection_breaches']:
        raise ValueError('live cell requires a quiescent original campaign')
    clock = CellDeadline.start(ContinuationStore(config['clock']), lifecycle=CellLifecycle(ledger),
                               cell_id=cell, plan_ref=config['ref'], seconds=binding['wallclock_seconds'])
    return launch(config, deadline=clock, directory=directory, api_key=api_key)


def main():
    if len(sys.argv) != 4:
        raise SystemExit('usage: python -m zoo.circle_packing.live_cell ARM CONFIG SUPERVISOR_DIRECTORY')
    key = os.environ.pop('DEEPSEEK_API_KEY', None)
    config = json.loads(Path(sys.argv[2]).read_text())
    print(json.dumps(start_live_cell(sys.argv[1], config, directory=Path(sys.argv[3]), api_key=key), sort_keys=True))


if __name__ == '__main__':
    main()
