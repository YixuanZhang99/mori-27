"""Project declared public per-case numeric scores for FunSearch planning.

Callers must persist and authenticate the returned evidence reference against
original execution evidence; this projection is not an admission decision.
"""
from __future__ import annotations

import hashlib

from core.composition.evaluation import decode_evidence, encode_evidence, public_projection
from core.executor.types import EvalStatus
from core.funsearch_population import _finite
from core.x1.checkpoint import payload_digest


def project_program_scores(evidence, *, case_ids, metric, logical_run_id):
    if (type(case_ids) is not list or not case_ids or any(type(x) is not str or not x for x in case_ids)
            or case_ids != sorted(set(case_ids)) or type(metric) is not str or not metric
            or type(logical_run_id) is not str or not logical_run_id):
        raise ValueError('frozen public case identities, metric and logical run are required')
    public = public_projection(evidence)
    result, contract = public.eval_result, public.eval_result.contract
    if (result.status is not EvalStatus.OK or contract.binding.split_id != 'dev'
            or contract.binding.fidelity != 'dev' or contract.items is None):
        raise ValueError('successful development item evidence is required')
    scores = {}
    for item in contract.items:
        if item.visibility != 'public' or item.seed is not None or item.item_id in scores or metric not in item.metrics:
            raise ValueError('unique unseeded public case metrics are required')
        value = item.metrics[metric]
        if not _finite(value):
            raise ValueError('public case score must be finite')
        scores[item.item_id] = float(value)
    if set(scores) != set(case_ids):
        raise ValueError('public case metrics differ from the frozen case set')
    evidence_ref = 'sha256:' + payload_digest({'logical_run_id': logical_run_id, 'evidence': encode_evidence(evidence)})
    return {'candidate_id': evidence.candidate_id, 'scores': {case: scores[case] for case in case_ids},
            'evidence_ref': evidence_ref}


def project_program_candidate(evidence, artifact, *, case_ids, metric, logical_run_id):
    if type(artifact) is not str or not artifact:
        raise ValueError('evaluated artifact must be nonempty text')
    try:
        digest = hashlib.sha256(artifact.encode('utf-8')).hexdigest()
    except UnicodeEncodeError as exc:
        raise ValueError('evaluated artifact must be valid UTF-8') from exc
    projection = project_program_scores(evidence, case_ids=case_ids, metric=metric,
                                        logical_run_id=logical_run_id)
    if digest != evidence.eval_result.contract.binding.artifact_sha256:
        raise ValueError('artifact differs from original evaluation binding')
    return {**projection, 'program_ref': 'sha256:' + digest, 'program_length': len(artifact)}


def verify_selected_projections(rows, projections, selected, *, case_ids, metric, logical_run_id,
                                evaluator_version, evaluation_context):
    """Compare selected projections with trusted main-lane composed evidence.

    The caller must supply rows from its authenticated run journal, never an
    untrusted checkpoint or a control-lane store.
    """
    if (type(rows) is not list or type(projections) is not dict or
            type(selected) not in (set, frozenset) or not selected or
            any(type(x) is not str or not x for x in selected) or set(projections) != selected or
            type(evaluator_version) is not str or not evaluator_version or
            type(evaluation_context) is not str or not evaluation_context):
        raise ValueError('trusted evidence rows and exact selected identities are required')
    found = {}
    for row in rows:
        try:
            if type(row) is not dict or set(row) != {'cycle', 'proposal', 'evidence_ref', 'evidence'}:
                raise ValueError('invalid composed evidence event')
            proposal = row['proposal']
            candidate_id = proposal['candidate']['id']
            if type(candidate_id) is not str or not candidate_id:
                raise ValueError('invalid candidate identity')
            if candidate_id not in selected:
                continue
            if candidate_id in found:
                raise ValueError('duplicate original evidence for selected candidate')
            evidence = decode_evidence({'schema_version': 1, 'evidence': row['evidence']})
            binding = evidence.eval_result.contract.binding
            if (candidate_id != evidence.candidate_id or binding.evaluator_version != evaluator_version or
                    binding.evaluation_context != evaluation_context):
                raise ValueError('selected evidence differs from frozen evaluation identity')
            actual = project_program_candidate(evidence, proposal['artifact'], case_ids=case_ids,
                                               metric=metric, logical_run_id=logical_run_id)
            if row['evidence_ref'] != actual['evidence_ref'] or payload_digest(actual) != payload_digest(projections[candidate_id]):
                raise ValueError('selected evidence or program projection differs from original')
            found[candidate_id] = actual['evidence_ref']
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError('invalid composed evidence event') from exc
    if set(found) != selected:
        raise ValueError('selected candidate lacks original evidence')
    return True
