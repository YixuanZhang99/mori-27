"""Six-cell recovery inventory from one independently pinned campaign head.

This is a claim inventory, not a score reducer or authorization to launch.
An absent claim applies only to the inspected head; a claimed cell may have
completed, failed, or remain in progress, and needs its own terminal evidence.
"""
from __future__ import annotations

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def snapshot_matrix(ledger, plan, *, expected_plan_ref, expected_head):
    """Read one atomic ledger snapshot without creating or modifying any cell."""
    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('matrix requires the original campaign and frozen plan')
    inventory = ledger.circle_claim_inventory(expected_head=expected_head)
    try:
        expected = build_draft_plan(inventory['campaign'], source_commit=plan['source_commit'],
                                    dependency_lock_sha256=plan['dependency_lock_sha256'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('matrix plan differs from the original campaign') from error
    ref = 'sha256:' + expected['draft_sha256']
    if expected_plan_ref != ref or payload_digest(plan) != payload_digest(expected):
        raise ValueError('matrix plan differs from its original campaign')
    pilot, claims = inventory['pilot'], inventory['claims']
    if pilot is None or pilot['plan_ref'] != ref or pilot['wallclock_seconds'] != expected['limits']['wallclock_seconds']:
        raise ValueError('matrix requires the frozen original pilot')
    cells = []
    for cell in expected['cells']:
        identifier = f"{cell['arm']}-{cell['seed']}"
        claim = claims.get(identifier)
        if claim is not None and claim['plan_ref'] != ref:
            raise ValueError('cell claim differs from frozen matrix plan')
        cells.append({'cell_id': identifier, 'seed': cell['seed'], 'arm': cell['arm'],
                      'state': 'not_claimed' if claim is None else 'claimed_outcome_unverified', 'score': None})
    if set(claims) - {cell['cell_id'] for cell in cells}:
        raise ValueError('campaign has a cell outside the frozen matrix')
    return {'schema_version': 1, 'scope': 'campaign_claim_inventory_at_pinned_head',
            'performance_claim': False, 'plan_ref': ref, 'journal_head': inventory['journal_head'], 'cells': cells}
