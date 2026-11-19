"""Recalculate one Mori frozen geometry from a caller-pinned journal snapshot.

This is not a complete-run, accounting, replay or benchmark certification.
It never runs candidate code or calls a model.
"""
from core.composition.evaluation import decode_evidence, request_digest
from core.executor.types import EvalRequest
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.mori_controller import final_measurement
from zoo.circle_packing.reference_final import recalculate_geometry


def recalculate_mori_geometry(rows, *, expected_rows_sha256, public_range_threshold):
    """Check selection, final metrics and original recorded geometry together."""
    if type(rows) is not list or type(expected_rows_sha256) is not str or \
            payload_digest(rows) != expected_rows_sha256:
        raise ValueError('Mori journal differs from its independently pinned digest')
    try:
        freezes = [row['payload'] for row in rows if row['kind'] == 'metric_final_frozen']
        finals = [row['payload'] for row in rows if row['kind'] == 'metric_final_completed']
        if len(freezes) != 1 or len(finals) != 1 or finals[0]['state'] != 'completed':
            raise ValueError('Mori journal lacks a unique completed final selection')
        freeze, final = freezes[0], finals[0]
        candidate = freeze['candidate_id']
        measurement = final_measurement(final, candidate, public_range_threshold)
        final_evidence = decode_evidence(final['evidence'])
        binding = final['evidence']['evidence']['eval_result']['contract']['binding']
        request = EvalRequest(**freeze['request'])
        request.validate()
        if final_evidence.candidate_id != candidate or freeze['binding'] != binding or \
                request.split_id != 'final_audit' or binding['request_sha256'] != request_digest(request):
            raise ValueError('Mori final evidence differs from the frozen selection')
        matches = [row['payload']['evidence'] for row in rows if row['kind'] == 'composed_physical_evidence'
                   and row['payload']['request']['split_id'] == 'dev'
                   and row['payload']['evidence']['evidence']['candidate_id'] == candidate]
        if len(matches) != 1:
            raise ValueError('Mori selection lacks a unique original development evaluation')
        dev = matches[0]
        decode_evidence(dev)
        dev_result = dev['evidence']['eval_result']
        dev_binding = dev_result['contract']['binding']
        data = dev_result['contract']['private']['data']
        record = data['record']
        domain = object.__new__(CirclePackingDomain)
        domain._base_identity = record['identity']['context']
        domain._validate_record(candidate, record)
        if record['status'] != 'ok' or dev_binding['artifact_sha256'] != binding['artifact_sha256'] or \
                record['identity']['program_ref'] != 'sha256:' + binding['artifact_sha256'] or \
                data['geometry_ref'] != record['geometry_ref'] or \
                final['evidence']['evidence']['eval_result']['contract']['private']['data']['geometry_ref'] != record['geometry_ref']:
            raise ValueError('Mori final geometry differs from the recorded candidate')
        geometry = recalculate_geometry(record['stages'][-1], expected_program_ref=record['identity']['program_ref'],
            expected_geometry_ref=record['geometry_ref'], expected_metrics=record['metrics'])
        if measurement['sum_radii'] != geometry['metrics']['sum_radii'] or \
                measurement['normalized_score'] != geometry['metrics']['combined_score'] or \
                measurement['validity'] != geometry['metrics']['validity']:
            raise ValueError('Mori final metrics differ from independently recalculated geometry')
        return {'schema_version': 1, 'scope': 'caller_pinned_mori_journal_geometry', 'performance_claim': False,
                'candidate': candidate, 'measurement': measurement, 'geometry_ref': record['geometry_ref']}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid Mori journal geometry evidence') from error


def audit_anchored_mori_geometry(rows, *, view, clock, run_id, plan, expected_plan_ref, expected_rows_sha256):
    """Join frozen geometry to a pinned campaign and final evaluation anchor.

    This verifies one final evaluation and the currency run at that campaign
    head. It does not establish complete-run coverage or a benchmark result.
    """
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView
    if type(view) is not RecordedCurrencyView or not view._pinned_head or type(clock) is not RecordedCellClock:
        raise ValueError('Mori audit requires a pinned campaign and recorded clock')
    try:
        expected = build_draft_plan(view.manifest_binding(), source_commit=plan['source_commit'],
                                    dependency_lock_sha256=plan['dependency_lock_sha256'])
        if expected_plan_ref != 'sha256:' + expected['draft_sha256'] or \
                payload_digest(plan) != payload_digest(expected) or clock._record['plan_ref'] != expected_plan_ref or \
                clock._record['cell_id'] not in {f'mori-{seed}' for seed in (0, 1, 2)} or \
                clock._record['seconds'] != expected['limits']['wallclock_seconds']:
            raise ValueError('Mori audit differs from its frozen plan or cell')
        clock = RecordedCellClock(clock._evidence, view.cell_deadline_claim(clock._record['cell_id']))
        binding = view.run_deadline_binding(run_id)
        if binding != {'cell_id': clock._record['cell_id'], 'plan_ref': expected_plan_ref,
                       'deadline_ref': clock._record['record_sha256']}:
            raise ValueError('Mori currency run differs from its original deadline')
        contexts = [row['payload']['invocation']['external_context'] for row in rows
                    if row['kind'] == 'composed_provider_started']
        if not contexts or any(value['currency_run_id'] != run_id for value in contexts):
            raise ValueError('Mori journal differs from its original currency run')
        physical_refs = {value['physical_plan_ref'] for value in contexts}
        if len(physical_refs) != 1:
            raise ValueError('Mori journal has inconsistent physical plans')
        currency = view.audit_run(run_id, next(iter(physical_refs)))
        if not currency['protection_valid'] or currency['pending_calls'] or currency['breaches'] or \
                currency['outstanding_micro_cny'] or currency['reserved_micro_cny']:
            raise ValueError('Mori currency run is unresolved or invalid')
        physical = [row['payload'] for row in rows if row['kind'] == 'composed_physical_evidence'
                    and row['payload']['request']['split_id'] == 'final_audit']
        finals = [row['payload'] for row in rows if row['kind'] == 'metric_final_completed']
        if len(physical) != 1 or len(finals) != 1 or physical[0]['evidence'] != finals[0]['evidence']:
            raise ValueError('Mori final audit differs from its physical evidence')
        intent = physical[0]['intent_id']
        proofs = [row['payload'] for row in rows if row['kind'] == 'governed_work_eligibility'
                  and row['payload'].get('phase') == 'evaluation' and row['payload'].get('intent_id') == intent]
        if len(proofs) != 1 or proofs[0]['evidence_sha256'] != payload_digest(physical[0]['evidence']):
            raise ValueError('Mori final evaluation lacks its original eligibility proof')
        proof = proofs[0]
        clock.verify_observation(proof['observation'])
        observation = proof['observation']['observation']
        anchor = view.evaluation_eligibility(run_id, payload_digest(intent))
        if not proof['observation']['eligible'] or anchor is None or \
                anchor['cell_id'] != clock._record['cell_id'] or anchor['sequence'] != observation['sequence'] or \
                anchor['observation_sha256'] != observation['sha256'] or anchor['proof_sha256'] != payload_digest(proof):
            raise ValueError('Mori final evaluation differs from its campaign anchor')
        geometry = recalculate_mori_geometry(rows, expected_rows_sha256=expected_rows_sha256,
                                             public_range_threshold=expected['public_range_sum_radii'])
        return {**geometry, 'scope': 'campaign_anchored_mori_final_geometry_and_currency', 'run_id': run_id,
                'settled_upper_bound_micro_cny': currency['settled_upper_bound_micro_cny'],
                'invoice_verified': False}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid anchored Mori final evidence') from error
