"""Join two recorded final snapshots at one campaign head, without new work.

This does not certify complete runs, replay, elapsed-time enforcement, or a
benchmark result; unverified and unrun matrix cells remain explicit.
"""
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.host_runtime import reference_budget_config
from zoo.circle_packing.mori_final import audit_anchored_mori_geometry
from zoo.circle_packing.reference_recovery import recover_reference_snapshot
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def audit_pair_snapshot(*, seed, plan, expected_plan_ref, mori_rows, mori_rows_sha256, mori_view, mori_clock,
                        mori_run_id, reference_rows, reference_view, reference_clock, reference_run_id,
                        reference_worker_directory):
    """Recalculate one pair's anchored final snapshots and recorded costs."""
    if type(seed) is not int or seed not in (0, 1, 2) or \
            any(type(view) is not RecordedCurrencyView or not view._pinned_head
                for view in (mori_view, reference_view)) or \
            any(type(clock) is not RecordedCellClock for clock in (mori_clock, reference_clock)):
        raise ValueError('pair audit requires a declared seed and pinned evidence')
    try:
        if mori_clock._record['cell_id'] != f'mori-{seed}' or \
                reference_clock._record['cell_id'] != f'vendor-{seed}' or \
                mori_view.manifest_binding() != reference_view.manifest_binding():
            raise ValueError('pair evidence differs from its seed or campaign')
        mori_contexts = [row['payload']['invocation']['external_context'] for row in mori_rows
                         if row['kind'] == 'composed_provider_started']
        reference_plans = {row['payload']['plan_ref'] for row in reference_rows
                           if row['kind'] == 'governed_control_started'}
        if not mori_contexts or len(reference_plans) != 1:
            raise ValueError('pair lacks original physical run identities')
        mori_currency = mori_view.audit_run(mori_run_id, mori_contexts[0]['physical_plan_ref'])
        reference_currency = reference_view.audit_run(reference_run_id, next(iter(reference_plans)))
        if mori_currency['journal_head'] != reference_currency['journal_head']:
            raise ValueError('pair evidence must share one pinned campaign head')
        reference_claim = reference_view.reference_authority_claim(f'vendor-{seed}')
        if reference_claim is None or reference_claim['currency_run_id'] != reference_run_id or \
                not reference_claim['work_started'] or reference_claim['deadline_ref'] != reference_clock._record['record_sha256']:
            raise ValueError('reference result lacks its original authority claim')
        reference_clock = RecordedCellClock(reference_clock._evidence,
                                             reference_view.cell_deadline_claim(f'vendor-{seed}'))
        if not reference_currency['protection_valid'] or reference_currency['breaches'] or \
                reference_currency['pending_calls'] or reference_currency['outstanding_micro_cny'] or \
                reference_currency['reserved_micro_cny']:
            raise ValueError('reference currency run is unresolved or invalid')
        mori = audit_anchored_mori_geometry(mori_rows, view=mori_view, clock=mori_clock, run_id=mori_run_id,
            plan=plan, expected_plan_ref=expected_plan_ref, expected_rows_sha256=mori_rows_sha256)
        options, stamp, governance = reference_budget_config(plan, reference_view.manifest_binding(), seed=seed)
        reference = recover_reference_snapshot(reference_view, reference_clock, reference_run_id, plan=plan,
            expected_plan_ref=expected_plan_ref, worker_directory=reference_worker_directory,
            options=options, stamp=stamp, governance=governance, rows=reference_rows)
        if not reference['selection_frozen']:
            raise ValueError('reference selection is not frozen')
        summaries = {'mori': {'sum_radii': mori['measurement']['sum_radii'],
                              'validity': mori['measurement']['validity'],
                              'settled_upper_bound_micro_cny': mori['settled_upper_bound_micro_cny']},
                     'reference': {'sum_radii': reference['metrics']['sum_radii'],
                                   'validity': reference['metrics']['validity'],
                                   'settled_upper_bound_micro_cny': reference_currency['settled_upper_bound_micro_cny']}}
        cells = []
        for cell in plan['cells']:
            name = f"{cell['arm']}-{cell['seed']}"
            claim = mori_view.cell_deadline_claim(name)
            state = 'not_claimed' if claim is None else 'claimed_outcome_unverified'
            if cell['seed'] == seed and cell['arm'] in ('mori', 'vendor'):
                if claim is None:
                    raise ValueError('audited cell lacks its campaign claim')
                state = 'audited_final_snapshot'
            cells.append({'cell_id': name, 'seed': cell['seed'], 'arm': cell['arm'], 'state': state})
        return {'schema_version': 1, 'scope': 'paired_anchored_final_snapshots', 'performance_claim': False,
                'seed': seed, 'plan_ref': expected_plan_ref, 'journal_head': mori_currency['journal_head'],
                'cells': cells, **summaries,
                'sum_radii_difference': summaries['mori']['sum_radii'] - summaries['reference']['sum_radii'],
                'invoice_verified': False}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid recorded pair evidence') from error
