"""Build a versioned continuation proposal without writing or granting authority."""
from __future__ import annotations

import copy
import re

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.cny_budget import _head_anchor, _plan_ref, _sha


def build_continuation_draft(inventory, *, experiment_id, source_commit, dependency_lock_sha256, method_changes):
    """Describe a separate experiment; only a future atomic bind can authorize it."""
    if type(experiment_id) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,96}', experiment_id) is None:
        raise ValueError('experiment identity must be a bounded identifier')
    if type(method_changes) is not list or not method_changes or len(method_changes) > 32 or any(
            type(item) is not str or not item.strip() or len(item) > 512 for item in method_changes):
        raise ValueError('experiment changes must be explicit bounded descriptions')
    fields = {'journal_head', 'campaign', 'governance_enabled', 'pilot', 'runtime', 'first_pair_audit',
              'claims', 'currency'}
    if type(inventory) is not dict or set(inventory) != fields or inventory['governance_enabled'] is not True:
        raise ValueError('continuation requires a governed campaign inventory')
    try:
        _head_anchor(inventory['journal_head'])
        pilot, runtime, audit, currency = (inventory[key] for key in ('pilot', 'runtime', 'first_pair_audit', 'currency'))
        if any(type(value) is not dict for value in (pilot, runtime, audit, currency)):
            raise ValueError('continuation requires the original frozen pilot, runtime and audit')
        if set(pilot) != {'plan_ref', 'tree_ref', 'wallclock_seconds', 'require_runtime', 'require_single_run'} or \
                set(runtime) != {'plan_ref', 'tree_ref', 'runtime_ref', 'python_sha256'} or \
                set(audit) != {'schema_version', 'plan_ref', 'mori_run_id', 'reference_run_id',
                               'mori_rows_sha256', 'reference_rows_sha256', 'reference_bundle_sha256',
                               'replay_input_sha256', 'proof_sha256'} or \
                set(currency) != {'settled_upper_bound_micro_cny', 'reserved_micro_cny', 'protected_micro_cny',
                                  'remaining_micro_cny', 'pending_calls', 'protection_breaches', 'invoice_verified'}:
            raise ValueError('continuation inventory contains unsupported fields')
        pilot_ref, tree_ref = _plan_ref(pilot['plan_ref']), _plan_ref(pilot['tree_ref'])
        if pilot.get('require_runtime') is not True or pilot.get('require_single_run') is not True or \
                runtime['plan_ref'] != pilot_ref or runtime['tree_ref'] != tree_ref or \
                audit['plan_ref'] != pilot_ref or type(audit['schema_version']) is not int or audit['schema_version'] != 1:
            raise ValueError('original experiment bindings do not agree')
        _plan_ref(runtime['runtime_ref'])
        _sha(runtime['python_sha256'])
        for key in ('mori_run_id', 'reference_run_id', 'mori_rows_sha256', 'reference_rows_sha256',
                    'reference_bundle_sha256', 'replay_input_sha256', 'proof_sha256'):
            _sha(audit[key])
        if type(inventory['claims']) is not dict or set(inventory['claims']) != {'mori-0', 'vendor-0'}:
            raise ValueError('original first pair claims differ')
        numbers = ('settled_upper_bound_micro_cny', 'reserved_micro_cny', 'protected_micro_cny', 'remaining_micro_cny')
        if any(type(currency[key]) is not int or currency[key] < 0 for key in numbers) or \
                currency['reserved_micro_cny'] != 0 or currency['protected_micro_cny'] != 0 or \
                currency['pending_calls'] != [] or currency['protection_breaches'] != [] or \
                currency['invoice_verified'] is not False or \
                currency['settled_upper_bound_micro_cny'] + currency['remaining_micro_cny'] != inventory['campaign']['limit_micro_cny']:
            raise ValueError('campaign must be quiescent at the recorded head')
        draft = build_draft_plan(inventory['campaign'], source_commit=source_commit,
                                 dependency_lock_sha256=dependency_lock_sha256)
    except (KeyError, TypeError) as error:
        raise ValueError('continuation inventory is incomplete') from error
    draft.pop('draft_sha256')
    draft.update(schema_version=3, experiment_id=experiment_id, reasoning_effort='none',
                 predecessor_head=copy.deepcopy(inventory['journal_head']),
                 predecessor_pilot=copy.deepcopy(pilot), predecessor_runtime=copy.deepcopy(runtime),
                 predecessor_audit=copy.deepcopy(audit), method_changes=copy.deepcopy(method_changes),
                 cells=[{'seed': seed, 'arm': arm, 'cell_id': f'{experiment_id}--{arm}-{seed}', 'status': 'unrun'}
                        for seed in (0, 1, 2) for arm in ('vendor', 'mori')])
    draft['draft_sha256'] = payload_digest(draft)
    return draft
