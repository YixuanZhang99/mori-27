"""Recalculate reference geometry from a pinned host-attested snapshot.

This does not prove a complete run, a final winner, or a benchmark score.
It never executes the candidate or calls a model.
"""
from __future__ import annotations

import ast
import hashlib
import json

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.geometry import validate_geometry
from zoo.circle_packing.host_physical import _validate_stage_result
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.circle_packing.reference_selection import audit_anchored_reference_cell
from zoo.circle_packing.stage import _EVALUATOR, EVALUATOR_SHA256


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _validate_with_pinned_upstream(geometry):
    """Run only the pinned upstream geometry function, never candidate code."""
    import numpy as np
    source = _EVALUATOR.read_bytes()
    if hashlib.sha256(source).hexdigest() != EVALUATOR_SHA256:
        raise ValueError('pinned upstream evaluator source changed')
    tree = ast.parse(source, filename='pinned-circle-evaluator')
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'validate_packing']
    if len(functions) != 1:
        raise ValueError('pinned upstream geometry validator is missing')
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    namespace = {'np': np, 'print': lambda *args, **kwargs: None}
    exec(compile(module, 'pinned-circle-evaluator', 'exec'), namespace)
    return bool(namespace['validate_packing'](np.asarray(geometry['centers'], dtype=float),
                                               np.asarray(geometry['radii'], dtype=float)))


def recalculate_geometry(result, *, expected_program_ref, expected_geometry_ref, expected_metrics):
    """Revalidate measured geometry; this alone does not establish provenance."""
    try:
        if type(result) is not dict or type(result.get('stage')) is not int or result['stage'] not in (1, 2):
            raise ValueError('final geometry requires an original stage result')
        _validate_stage_result(result, stage=result['stage'], program_ref=expected_program_ref)
        if result['status'] != 'ok' or result['geometry_ref'] != expected_geometry_ref or \
                _json(result['metrics']) != _json(expected_metrics):
            raise ValueError('final geometry differs from the selected stage')
        geometry = json.loads(_json(result['geometry']))
        metrics = validate_geometry(geometry)
        if _json(metrics) != _json(expected_metrics):
            raise ValueError('final geometry metrics differ from independent calculation')
        if not _validate_with_pinned_upstream(geometry):
            raise ValueError('pinned upstream geometry validator rejected the result')
        return {'geometry': geometry, 'geometry_ref': expected_geometry_ref, 'metrics': metrics}
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError('invalid final geometry evidence') from error


def recalculate_reference_snapshot(view, clock, run_id, *, plan, expected_plan_ref, worker_proof,
                                   stdout, stderr, selected, options, stamp, governance, rows, request_ids):
    """Join the original anchored worker, selected stages and frozen task plan."""
    try:
        selected = json.loads(_json(selected))
        expected = build_draft_plan(view.manifest_binding(), source_commit=plan['source_commit'],
                                    dependency_lock_sha256=plan['dependency_lock_sha256'])
        if expected_plan_ref != 'sha256:' + expected['draft_sha256'] or \
                payload_digest(plan) != payload_digest(expected) or \
                clock._record['plan_ref'] != expected_plan_ref:
            raise ValueError('reference result differs from its frozen plan')
        joined = audit_anchored_reference_cell(view, clock, run_id, worker_proof=worker_proof,
            stdout=stdout, stderr=stderr, selected=selected, options=options, stamp=stamp,
            governance=governance, rows=rows, request_ids=request_ids)
        final = [row['payload']['result'] for row in rows if row['kind'] == 'host_stage_completed'
                 and row['payload']['request_id'] == request_ids[-1]]
        if len(final) != 1:
            raise ValueError('reference result lacks a unique original final stage')
        stage = joined['stage']
        geometry = recalculate_geometry(final[0], expected_program_ref=stage['program_ref'],
            expected_geometry_ref=stage['geometry_ref'], expected_metrics=stage['metrics'])
        return {'schema_version': 1, 'scope': 'host_attested_reference_snapshot',
                'performance_claim': False, 'plan_ref': expected_plan_ref, 'run_id': run_id,
                'selected_program': selected, 'stage_request_id': request_ids[-1],
                'stage_evidence_ref': stage['evidence_ref'], **geometry,
                'public_range_threshold': expected['public_range_sum_radii'],
                'public_range_condition_met': geometry['metrics']['sum_radii'] >= expected['public_range_sum_radii']}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid reference snapshot result evidence') from error
