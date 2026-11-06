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
