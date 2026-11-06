"""Join two recorded final snapshots at one campaign head, without new work.

This does not certify complete runs, replay, elapsed-time enforcement, or a
benchmark result; unverified and unrun matrix cells remain explicit.
"""
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.host_runtime import reference_budget_config
from zoo.circle_packing.mori_final import audit_anchored_mori_geometry
from zoo.circle_packing.reference_currency import audit_reference_currency
from zoo.circle_packing.reference_recovery import recover_reference_snapshot
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def _require_currency_prefix(original, common):
    prefix = original['events']
    if original['policy_json'] != common['policy_json'] or type(prefix) is not list or \
            len(prefix) > len(common['events']) or prefix != common['events'][:len(prefix)] or \
            original['journal_head']['seq'] != len(prefix) or \
            (prefix and prefix[-1]['sha256'] != original['journal_head']['sha256']):
        raise ValueError('reference currency evidence is not a prefix of the paired campaign head')


def audit_pair_snapshot(*, seed, plan, expected_plan_ref, mori_rows, mori_rows_sha256, mori_view, mori_clock,
                        mori_run_id, reference_rows, reference_view, reference_clock, reference_run_id,
                        reference_worker_directory, reference_bundle):
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
        common = reference_view.export_governance_evidence(reference_run_id, next(iter(reference_plans)))
        original = reference_bundle['currency_evidence']
        _require_currency_prefix(original, common)
        reference_receipts = audit_reference_currency(reference_bundle, rows=reference_rows,
            expected_head=original['journal_head'], expected_plan_ref=expected_plan_ref, plan=plan, seed=seed)
        if reference_receipts['run_id'] != reference_run_id or \
                reference_receipts['settled_upper_bound_micro_cny'] != reference_currency['settled_upper_bound_micro_cny']:
            raise ValueError('reference receipt audit differs from paired currency state')
        mori = audit_anchored_mori_geometry(mori_rows, view=mori_view, clock=mori_clock, run_id=mori_run_id,
            plan=plan, expected_plan_ref=expected_plan_ref, expected_rows_sha256=mori_rows_sha256)
        options, stamp, governance = reference_budget_config(plan, reference_view.manifest_binding(), seed=seed)
        reference = recover_reference_snapshot(reference_view, reference_clock, reference_run_id, plan=plan,
            expected_plan_ref=expected_plan_ref, worker_directory=reference_worker_directory,
            options=options, stamp=stamp, governance=governance, rows=reference_rows)
        if not reference['selection_frozen']:
            raise ValueError('reference selection is not frozen')
        from zoo.circle_packing.reference_iteration_trace import (
            audit_reference_iteration_provider, audit_reference_iteration_receipts, audit_reference_iteration_stages)
        reference_trace = reference.get('iteration_trace')
        reference_receipts = (audit_reference_iteration_receipts(reference_trace, reference_rows,
                               planned_iterations=plan['iterations']) if reference_trace is not None else
                              {'schema_version': 1, 'scope': 'reference_iteration_receipts_unverified',
                               'performance_claim': False})
        reference_provider = (audit_reference_iteration_provider(reference_trace, reference_rows, reference_bundle,
                              planned_iterations=plan['iterations']) if reference_trace is not None and
                              'prompt_bindings' in reference_trace else
                              {'schema_version': 1, 'scope': 'reference_iteration_provider_unverified',
                               'performance_claim': False})
        reference_stages = (audit_reference_iteration_stages(reference_trace, reference_rows,
                            planned_iterations=plan['iterations']) if reference_trace is not None and
                            'stage_bindings' in reference_trace else
                            {'schema_version': 1, 'scope': 'reference_iteration_stages_unverified',
                             'performance_claim': False})
        summaries = {'mori': {'candidate': mori['candidate'], 'sum_radii': mori['measurement']['sum_radii'],
                              'validity': mori['measurement']['validity'],
                              'settled_upper_bound_micro_cny': mori['settled_upper_bound_micro_cny']},
                     'reference': {'selected_program': reference['selected_program'],
                                   'sum_radii': reference['metrics']['sum_radii'],
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
                'reference_iteration_receipts': reference_receipts,
                'reference_iteration_provider': reference_provider,
                'reference_iteration_stages': reference_stages,
                'sum_radii_difference': summaries['mori']['sum_radii'] - summaries['reference']['sum_radii'],
                'invoice_verified': False}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid recorded pair evidence') from error


def audit_supervised_pair_snapshot(*, mori_config, reference_config, mori_supervisor_directory,
                                   reference_supervisor_directory, **pair_arguments):
    """Join successful supervisor reports to independently recalculated snapshots.

    This checks recorded supervisor assertions and final snapshots only. It is
    not a full-run certificate and does not authorize subsequent seed cells.
    """
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.supervisor_audit import audit_supervisor_result
    try:
        for config in (mori_config, reference_config):
            if config['plan'] != pair_arguments['plan'] or config['ref'] != pair_arguments['expected_plan_ref'] or \
                    config['seed'] != pair_arguments['seed']:
                raise ValueError('supervisor configuration differs from the audited pair')
        mori_report = audit_supervisor_result(mori_config, directory=mori_supervisor_directory,
            view=pair_arguments['mori_view'], clock=pair_arguments['mori_clock'])
        reference_report = audit_supervisor_result(reference_config, directory=reference_supervisor_directory,
            view=pair_arguments['reference_view'], clock=pair_arguments['reference_clock'])
        result = audit_pair_snapshot(**pair_arguments)
        if mori_report.get('mode') != 'live' or mori_report.get('final_state') != 'completed' or \
                mori_report.get('candidate') != result['mori']['candidate'] or \
                mori_report['final_measurement']['sum_radii'] != result['mori']['sum_radii'] or \
                mori_report['final_measurement']['validity'] != result['mori']['validity'] or \
                reference_report.get('mode') != 'live' or reference_report.get('state') != 'completed' or \
                reference_report.get('currency_bundle_sha256') != payload_digest(pair_arguments['reference_bundle']) or \
                payload_digest(reference_report['selected_program']) != payload_digest(result['reference']['selected_program']) or \
                reference_report['selected_program']['metrics']['sum_radii'] != result['reference']['sum_radii'] or \
                reference_report['selected_program']['metrics']['validity'] != result['reference']['validity']:
            raise ValueError('supervisor reports differ from the independently audited snapshots')
        return {**result, 'scope': 'paired_supervised_anchored_final_snapshots'}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid supervised pair evidence') from error


def audit_replayed_supervised_pair(*, replay_input, ledger, runner, replay_output, mori_config,
                                   mori_supervisor_directory, **pair_arguments):
    """Independently replay the recorded Mori inputs alongside the paired audit.

    Run this from the frozen source and runtime in a fresh process. This still
    is not a durable authorization for later cells or a benchmark claim.
    """
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.mori_recorded import replay_mori_snapshot
    from zoo.circle_packing.supervisor_audit import audit_supervisor_result
    try:
        result = audit_supervised_pair_snapshot(mori_config=mori_config,
            mori_supervisor_directory=mori_supervisor_directory, **pair_arguments)
        report = audit_supervisor_result(mori_config, directory=mori_supervisor_directory,
            view=pair_arguments['mori_view'], clock=pair_arguments['mori_clock'])
        if type(replay_input) is not dict or payload_digest(replay_input) != report['replay_input_sha256']:
            raise ValueError('replay inputs differ from the original supervisor report')
        rows, original = replay_input['rows'], replay_input['currency_bundle']['currency_evidence']
        if type(rows) is not list or rows != pair_arguments['mori_rows'][:len(rows)]:
            raise ValueError('replay transcript is not the original Mori journal prefix')
        context = next(row['payload']['invocation']['external_context'] for row in pair_arguments['mori_rows']
                       if row['kind'] == 'composed_provider_started')
        common = pair_arguments['mori_view'].export_governance_evidence(
            pair_arguments['mori_run_id'], context['physical_plan_ref'])
        _require_currency_prefix(original, common)
        if ledger.snapshot()['journal_head'] != result['journal_head']:
            raise ValueError('original campaign head changed before independent replay')
        replay = replay_mori_snapshot(mori_config, replay_input,
            expected_evidence_sha256=report['replay_input_sha256'],
            expected_campaign_head=original['journal_head'], ledger=ledger, runner=runner, output=replay_output)
        if replay.get('passed') is not True or replay.get('external_calls') != 0 or \
                replay.get('candidate') != result['mori']['candidate'] or \
                ledger.snapshot()['journal_head'] != result['journal_head']:
            raise ValueError('independent replay differs from the paired result or campaign head')
        checkpoint = replay_input['checkpoint']['payload']
        if checkpoint['next_cycle'] == pair_arguments['plan']['iterations'] + 1 and checkpoint['halted_reason'] is None:
            from zoo.circle_packing.mori_cycle_audit import audit_completed_mori_cycles
            cycles = audit_completed_mori_cycles(replay_input, expected_input_sha256=report['replay_input_sha256'],
                view=pair_arguments['mori_view'], clock=pair_arguments['mori_clock'],
                run_id=pair_arguments['mori_run_id'], plan=pair_arguments['plan'],
                expected_plan_ref=pair_arguments['expected_plan_ref'])
        else:
            cycles = {'schema_version': 1, 'scope': 'mori_cycle_coverage_unverified', 'performance_claim': False,
                      'next_cycle': checkpoint['next_cycle'], 'stop_reason': checkpoint['halted_reason']}
        return {**result, 'scope': 'paired_supervised_snapshots_with_independent_replay',
                'replay': replay, 'mori_cycle_coverage': cycles}
    except (KeyError, TypeError, AttributeError, StopIteration) as error:
        raise ValueError('invalid paired replay evidence') from error


def record_first_pair_audit(*, replay_input, ledger, runner, replay_output, **pair_arguments):
    """Rerun the independent audit, then atomically record it at its original head.

    The event records a trusted verifier's assertion; it does not authorize a
    live pilot or replace verification of the retained original evidence.
    """
    from core.x1.checkpoint import payload_digest
    if type(pair_arguments.get('seed')) is not int or pair_arguments['seed'] != 0:
        raise ValueError('only the original first pair can be recorded')
    result = audit_replayed_supervised_pair(replay_input=replay_input, ledger=ledger, runner=runner,
                                            replay_output=replay_output, **pair_arguments)
    proof = {'schema_version': 1, 'plan_ref': pair_arguments['expected_plan_ref'],
             'mori_run_id': pair_arguments['mori_run_id'], 'reference_run_id': pair_arguments['reference_run_id'],
             'mori_rows_sha256': payload_digest(pair_arguments['mori_rows']),
             'reference_rows_sha256': payload_digest(pair_arguments['reference_rows']),
             'reference_bundle_sha256': payload_digest(pair_arguments['reference_bundle']),
             'replay_input_sha256': payload_digest(replay_input), 'result': result}
    ledger._record_first_pair_audit(proof, expected_head=result['journal_head'])
    return proof
