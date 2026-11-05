"""Opt-in reporting-only held-out evaluation after a metric gate freezes selection.

Unlike layered admission, this gate uses development performance for selection.
The final score never changes the incumbent or enters search memory.
"""
from dataclasses import asdict
import json

from core.composition.evaluation import encode_evidence, decode_evidence, validate_evidence
from core.executor.types import EvalRequest, EvalStatus


def final_metric_options(options):
    if type(options) is not dict or 'final_request' not in options:
        raise ValueError('final metric gate requires a frozen final_request')
    request = EvalRequest(**options['final_request'])
    request.validate()
    if request.split_id != 'final_audit' or request.resume_from is not None:
        raise ValueError('final metric gate requires the final_audit split')


def final_report(runtime):
    if getattr(runtime.parts['admission'], 'final_request', None) is None:
        return None
    rows = [r['payload'] for r in runtime.store.read('metric_final_completed')]
    if len(rows) > 1:
        raise ValueError('final evaluation has multiple terminal reports')
    return {'selection': 'development_only', 'final_audit': rows[0] if rows else {'state': 'not_frozen'}}


async def finish(runtime):
    admission = runtime.parts['admission']
    if getattr(admission, 'final_request', None) is None:
        return
    if not runtime.hierarchical or not runtime.construction_enabled:
        raise ValueError('final metric gate requires metered M7 execution')
    request = admission.final_request
    runtime._validate_domain(request)
    proposal = runtime.proposals.get(runtime.incumbent)
    frozen = {'candidate_id': runtime.incumbent, 'request': asdict(request),
              'binding': asdict(runtime._binding(proposal, request)) if proposal else None}
    frozen = json.loads(json.dumps(frozen, allow_nan=False))
    previous = [r['payload'] for r in runtime.store.read('metric_final_frozen')]
    if previous and previous != [frozen]:
        raise ValueError('final selection differs from its immutable freeze')
    report = final_report(runtime)['final_audit']
    if report['state'] != 'not_frozen':
        if not previous or report['candidate_id'] != runtime.incumbent:
            raise ValueError('final report lacks its selected candidate freeze')
        if 'evidence' in report:
            evidence = decode_evidence(report['evidence'])
            validate_evidence(evidence, expected_binding=runtime._binding(proposal, request))
        return
    if not previous:
        runtime.store.append('metric_final_frozen', frozen)
    outcome = {'candidate_id': runtime.incumbent, 'state': 'skipped', 'reason': 'no successful candidate'}
    if proposal:
        receipt = runtime._reserve_physical(proposal.candidate, 'final', 'metric-final', request=request)
        if receipt.granted:
            evidence = await runtime._evaluate_physical(proposal, request, receipt)
            outcome = {'candidate_id': runtime.incumbent,
                'state': 'completed' if evidence.eval_result.status is EvalStatus.OK else 'evaluation_failed',
                'evidence': encode_evidence(evidence)}
        else:
            outcome['reason'] = receipt.reason
    runtime.store.append('metric_final_completed', outcome)
    runtime._save()
