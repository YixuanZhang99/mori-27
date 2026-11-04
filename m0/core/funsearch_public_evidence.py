"""Project declared public per-case numeric scores for FunSearch planning.

Callers must persist and authenticate the returned evidence reference against
original execution evidence; this projection is not an admission decision.
"""
from __future__ import annotations

from core.composition.evaluation import encode_evidence, public_projection
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
