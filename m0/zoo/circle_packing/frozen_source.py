"""Bind one clean draft snapshot to the original campaign journal.

This is an offline preflight, not authorization for model calls. It does not
freeze the installed dependencies or prevent later source mutation.
"""
from __future__ import annotations

import re

from zoo.circle_packing.clean_source import export_clean_source, verify_clean_source
from zoo.circle_packing.pilot_plan import validate_draft_cell


def _validate_campaign(ledger, plan, expected_plan_ref, expected_campaign_id):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    if type(ledger) is not CampaignBudget or type(expected_campaign_id) is not str or \
            not re.fullmatch(r'[0-9a-f]{32}', expected_campaign_id) or \
            ledger.manifest_binding()['campaign_id'] != expected_campaign_id:
        raise ValueError('campaign differs from the independently supplied identity')
    return validate_draft_cell(ledger, plan, 'vendor-0', expected_plan_ref=expected_plan_ref)


def _validate_lock(plan, manifest):
    lock = [item for item in manifest if item.get('path') == 'm0/uv.lock']
    if len(lock) != 1 or lock[0].get('sha256') != plan['dependency_lock_sha256']:
        raise ValueError('snapshot dependency lock differs from the pilot plan')


def freeze_source_plan(ledger, plan, *, checkout, destination, expected_plan_ref, expected_campaign_id):
    """An export left by a failed ledger binding is not authorized for use."""
    _validate_campaign(ledger, plan, expected_plan_ref, expected_campaign_id)
    result = export_clean_source(ledger, plan, 'vendor-0', checkout=checkout, destination=destination,
                                 expected_plan_ref=expected_plan_ref)
    _validate_lock(plan, result['manifest'])
    verify_clean_source(destination, result['manifest'], expected_tree_ref=result['tree_ref'])
    ledger.freeze_circle_pilot(expected_plan_ref, result['tree_ref'], plan['limits']['wallclock_seconds'])
    return result


def verify_frozen_source(ledger, plan, *, snapshot, manifest, expected_plan_ref, expected_campaign_id):
    _validate_campaign(ledger, plan, expected_plan_ref, expected_campaign_id)
    binding = ledger.circle_pilot_binding()
    if binding is None or binding['plan_ref'] != expected_plan_ref or \
            binding['wallclock_seconds'] != plan['limits']['wallclock_seconds']:
        raise ValueError('campaign lacks the frozen pilot plan')
    result = verify_clean_source(snapshot, manifest, expected_tree_ref=binding['tree_ref'])
    _validate_lock(plan, manifest)
    return result
