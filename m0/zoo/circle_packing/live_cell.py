"""Start one frozen live cell only after the paired-pilot gate is complete."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def start_live_cell(arm, config, *, directory, api_key, _resume_unstarted=False):
    """Start one original cell clock, then launch its bounded trusted host."""
    if arm == 'mori':
        from zoo.circle_packing.mori_live_worker import _require_live_gate
        _require_live_gate(config)
        from zoo.circle_packing.mori_controller import CONFIG_FIELDS
        fields = CONFIG_FIELDS
    elif arm == 'vendor':
        from zoo.circle_packing.host_runtime import _require_reference_live_gate
        _require_reference_live_gate()
        from zoo.circle_packing.reference_live_worker import REFERENCE_CONFIG_FIELDS
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
    from zoo.circle_packing.pilot_plan import require_first_pair_audit, validate_draft_cell
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget(config['ledger'])
    if ledger.is_fixture_campaign() or config['campaign_id'] != ledger.manifest_binding()['campaign_id'] or \
            config['base_url'] != ledger.manifest_binding()['provider_base_url']:
        raise ValueError('live cell requires its original non-fixture campaign')
    cell = f"{arm}-{config['seed']}"
    binding = validate_draft_cell(ledger, config['plan'], cell, expected_plan_ref=config['ref'])
    require_first_pair_audit(config['seed'], ledger=ledger, expected_plan_ref=config['ref'])
    if _resume_unstarted:
        original = ledger.cell_deadline_claim(cell)
        if (original is None and not Path(config['clock']).is_file()) or \
                (original is not None and original['plan_ref'] != config['ref']):
            raise ValueError('resume requires the original cell clock and plan')
        if ledger.cell_worker_claim(cell) is not None or (arm == 'vendor' and (
                ledger.reference_host_claim(cell) is not None or ledger.reference_authority_claim(cell) is not None)):
            raise ValueError('resume refuses a cell with an already claimed worker or host')
    state = ledger.snapshot()
    if state['pending_calls'] or state['protected_micro_cny'] or state['protection_breaches']:
        raise ValueError('live cell requires a quiescent original campaign')
    from zoo.circle_packing.cell_containment import delegated_cell_group
    from zoo.circle_packing.mori_supervisor import preflight_live_controller, _launch_controller
    preflight_live_controller(config, ledger=ledger, directory=directory, reference=arm == 'vendor')
    entry = ('zoo.circle_packing.mori_live_worker' if arm == 'mori'
             else 'zoo.circle_packing.reference_live_worker')
    with delegated_cell_group() as group:
        kwargs = {'cell_id': cell, 'plan_ref': config['ref'], 'seconds': binding['wallclock_seconds']}
        if _resume_unstarted:
            kwargs['reconcile_unstarted'] = True
        create = CellDeadline.restore if _resume_unstarted else CellDeadline.start
        clock = create(ContinuationStore(config['clock']), lifecycle=CellLifecycle(ledger), **kwargs)
        return _launch_controller(config, ledger=ledger, deadline=clock, directory=directory,
                                  entry=entry, api_key=api_key, containment_group=group)


def resume_unstarted_live_cell(arm, config, *, directory, api_key):
    """Resume only an original clock with no worker or reference host claim."""
    return start_live_cell(arm, config, directory=directory, api_key=api_key, _resume_unstarted=True)


def main():
    if len(sys.argv) not in (4, 5) or (len(sys.argv) == 5 and sys.argv[4] != '--resume-unstarted'):
        raise SystemExit('usage: python -m zoo.circle_packing.live_cell ARM CONFIG SUPERVISOR_DIRECTORY [--resume-unstarted]')
    key = os.environ.pop('DEEPSEEK_API_KEY', None)
    config = json.loads(Path(sys.argv[2]).read_text())
    start = resume_unstarted_live_cell if len(sys.argv) == 5 else start_live_cell
    print(json.dumps(start(sys.argv[1], config, directory=Path(sys.argv[3]), api_key=key), sort_keys=True))


if __name__ == '__main__':
    main()
