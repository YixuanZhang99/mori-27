"""Reconstruct completed Mori cycle outcomes from a pinned recorded transcript.

This is an audit of one completed transcript, not a reference-arm audit,
invoice verification, complete paired-run certificate, or benchmark result.
"""
import json

from core.x1.checkpoint import RunCheckpoint, payload_digest
from zoo.circle_packing.cell_deadline import RecordedCellClock
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def audit_completed_mori_cycles(evidence, *, expected_input_sha256, view, clock, run_id, plan, expected_plan_ref):
    """Check every seed/search cycle against its recorded decision and clock anchor."""
    if type(evidence) is not dict or payload_digest(evidence) != expected_input_sha256 or \
            type(view) is not RecordedCurrencyView or not view._pinned_head or type(clock) is not RecordedCellClock:
        raise ValueError('cycle audit requires pinned original evidence and clock')
    try:
        expected = build_draft_plan(view.manifest_binding(), source_commit=plan['source_commit'],
                                    dependency_lock_sha256=plan['dependency_lock_sha256'])
        if plan != expected or expected_plan_ref != 'sha256:' + expected['draft_sha256'] or \
                clock._record['plan_ref'] != expected_plan_ref or not clock._record['cell_id'].startswith('mori-'):
            raise ValueError('cycle audit differs from the original pilot')
        clock = RecordedCellClock(clock._evidence, view.cell_deadline_claim(clock._record['cell_id']))
        if view.run_deadline_binding(run_id) != {'cell_id': clock._record['cell_id'],
                'plan_ref': expected_plan_ref, 'deadline_ref': clock._record['record_sha256']}:
            raise ValueError('cycle audit differs from its original run')
        checkpoint = RunCheckpoint.from_bytes(json.dumps(evidence['checkpoint']).encode()).payload
        count = plan['iterations'] + 1  # cycle zero is the initial program
        if checkpoint['config']['max_generations'] != plan['iterations'] or \
                type(checkpoint['next_cycle']) is not int or checkpoint['next_cycle'] != count or \
                checkpoint['halted_reason'] is not None:
            raise ValueError('transcript is not a complete planned Mori run')
        rows = evidence['rows']
        if type(rows) is not list:
            raise ValueError('cycle transcript must be a list')
        starts = [(index, row['payload']['cycle']) for index, row in enumerate(rows)
                  if row['kind'] == 'composed_cycle_started']
        if [cycle for _, cycle in starts] != list(range(count)) or any(
                row['kind'] in ('composed_cycle_aborted', 'composed_cycle_failed', 'composed_stopped') for row in rows):
            raise ValueError('cycle transcript has missing, repeated or interrupted cycles')
        proofs = [(index, row['payload']) for index, row in enumerate(rows)
                  if row['kind'] == 'governed_work_eligibility' and row['payload'].get('phase') == 'cycle_commit']
        if [proof['cycle'] for _, proof in proofs] != list(range(count)):
            raise ValueError('cycle transcript lacks complete ordered eligibility proofs')
        outcomes = []
        for cycle, ((start_index, _), (proof_index, proof)) in enumerate(zip(starts, proofs)):
            candidate = proof['candidate_id']
            end = starts[cycle + 1][0] if cycle + 1 < count else len(rows)
            evidence_rows = [(i, row['payload']) for i, row in enumerate(rows)
                if row['kind'] == 'composed_evidence' and row['payload']['cycle'] == cycle]
            decisions = [(i, row['payload']) for i, row in enumerate(rows)
                if row['kind'] == 'composed_decision' and row['payload']['candidate_id'] == candidate]
            if len(evidence_rows) != 1 or len(decisions) != 1:
                raise ValueError('cycle lacks one candidate evidence and decision')
            evidence_index, event = evidence_rows[0]
            decision_index, decision = decisions[0]
            receipt = {key: value for key, value in decision.items() if key not in {'event_id', 'receipt_id'}}
            if not start_index < proof_index < evidence_index < decision_index < end or \
                    event['proposal']['candidate']['id'] != candidate or \
                    proof['evidence_sha256'] != payload_digest(event) or \
                    proof['decision_sha256'] != payload_digest(receipt):
                raise ValueError('cycle decision differs from its original eligibility proof')
            clock.verify_observation(proof['observation'])
            observation = proof['observation']['observation']
            anchor = view.cycle_eligibility(run_id, payload_digest({'cycle': cycle, 'candidate_id': candidate}))
            if not proof['observation']['eligible'] or anchor is None or \
                    anchor['cell_id'] != clock._record['cell_id'] or anchor['sequence'] != observation['sequence'] or \
                    anchor['observation_sha256'] != observation['sha256'] or anchor['proof_sha256'] != payload_digest(proof):
                raise ValueError('cycle eligibility differs from its original ledger anchor')
            outcomes.append({'cycle': cycle, 'candidate': candidate,
                'evaluation_status': event['evidence']['eval_result']['status'],
                'admitted': decision['decision']['admit']})
        return {'schema_version': 1, 'scope': 'caller_pinned_complete_mori_cycles',
                'performance_claim': False, 'cycles': outcomes}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid recorded Mori cycle evidence') from error
