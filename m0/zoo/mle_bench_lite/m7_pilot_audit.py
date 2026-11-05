"""Independent currency-receipt cross-check for M7 MLE runs.

This establishes currency, response usage and construction provenance, not full
physical settlement, selected artifact or official benchmark score. Callers
must perform those checks separately before accepting an experiment.
"""
from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from core.x1.checkpoint import payload_digest
from core.composition.construction_audit import audit_construction
from core.composition.external_provider import GovernedCallContext, external_call_id
from .cny_budget import validate_detailed_usage
from .governed_currency_audit import verify_governance_evidence


def _record(path):
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('currency record must be a private regular file')
    value = json.loads(path.read_text())
    if type(value) is not dict or set(value) != {'payload', 'sha256'} or \
            value['sha256'] != payload_digest(value['payload']):
        raise ValueError('currency record hash differs')
    return value['payload']


def audit_currency_receipts(run_root, ledger, *, expected_model):
    """Bind the live campaign journal to complete response receipt usage.

    A trusted, current ledger anchors the journal. This is intentionally not
    a substitute for Framework's physical/governance or artifact audit.
    """
    spool = Path(run_root) / '.governed-cny'
    if spool.is_symlink() or not spool.is_dir() or type(expected_model) is not str or not expected_model:
        raise ValueError('invalid currency receipt audit inputs')
    ready = _record(spool / 'ready.json')
    binding = ready['authority_binding']
    if binding['policy_sha256'] != ledger.manifest_binding()['policy_sha256']:
        raise ValueError('campaign policy identity differs')
    head = ledger.snapshot()['journal_head']
    evidence = ledger.export_governance_evidence(binding['currency_run_id'], ready['physical_plan_ref'])
    audit = verify_governance_evidence(evidence, expected_run_id=binding['currency_run_id'],
        expected_plan_ref=ready['physical_plan_ref'], expected_policy_sha256=binding['policy_sha256'], expected_head=head)
    if audit['pending_calls'] or audit['campaign_pending_calls'] or audit['breaches'] or not audit['protection_valid']:
        raise ValueError('currency journal is incomplete or protection failed')
    operations = {row['call_id']: row for row in audit['operations'] if row['kind'] == 'governed_reserve'}
    if not operations or len(operations) != sum(row['kind'] == 'governed_reserve' for row in audit['operations']):
        raise ValueError('missing or duplicate currency operations')
    responses = list(spool.glob('call-*.response.json'))
    if len(responses) != len(operations):
        raise ValueError('currency response coverage differs')
    total = 0
    provider_arguments = {}
    truncated_calls = set()
    for path in responses:
        context_hash = path.name.removeprefix('call-').removesuffix('.response.json')
        prepared = _record(spool / ('call-' + context_hash + '.prepared.json'))
        context = GovernedCallContext.from_dict(prepared['context'])
        body = prepared['wire_body']
        if type(body) is not str or payload_digest(context.to_dict()) != context_hash or \
                hashlib.sha256(body.encode()).hexdigest() != prepared['wire_request_sha256'] or \
                prepared['call_id'] != external_call_id(context, prepared['wire_request_sha256']) or \
                context.currency_run_id != binding['currency_run_id']:
            raise ValueError('prepared call identity differs')
        operation = operations.pop(prepared['call_id'], None)
        wire = json.loads(body)
        prompt = wire['messages'][0]['content']
        provider_arguments[payload_digest(context.to_dict())] = prompt
        response = _record(path)
        # A truncated provider response is a known, billed failed call, not a
        # corrupted receipt. It must contain no usable result and cannot claim
        # a normal stop; construction provenance below still binds every call.
        reason = response.get('integrity_reason')
        complete_or_truncated = reason is None or (reason == 'incomplete_output' and
            response.get('result') is None and response.get('finish_reason') != 'stop')
        if operation is None or response.get('returned_model') != expected_model or \
                not complete_or_truncated or \
                response.get('response_sha256') != operation.get('response_sha256') or \
                operation.get('request_sha256') != prepared['wire_request_sha256']:
            raise ValueError('response identity or outcome differs from currency journal')
        if reason == 'incomplete_output':
            truncated_calls.add(payload_digest(context.to_dict()))
        usage = validate_detailed_usage(response.get('usage'))
        if usage != operation.get('usage') or operation.get('bound_violation'):
            raise ValueError('response usage differs from settled currency journal')
        total += usage['total_tokens']
    if operations:
        raise ValueError('currency operations lack responses')
    preparation = _record(spool / 'plan-prepared.json')
    run = preparation['run']
    if preparation['currency_run_id'] != binding['currency_run_id'] or \
            run['logical_run_id'] != ready['logical_run_id']:
        raise ValueError('construction preparation differs from currency run')
    transcript = Path(run_root) / 'x1.jsonl'
    if transcript.is_symlink() or not transcript.is_file():
        raise ValueError('construction transcript is missing or unsafe')
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    # The receipt envelope alone is not independent proof of failure: require
    # the original provider transcript to mark the same invocation as failed.
    observed_truncated = set()
    pending = None
    for row in rows:
        if row['kind'] == 'composed_provider_started':
            context = row['payload']['invocation'].get('external_context')
            context_ref = payload_digest(context) if context is not None else None
            if context_ref in truncated_calls:
                if pending is not None or context_ref in observed_truncated:
                    raise ValueError('truncated call lacks a unique failed provider transcript')
                pending = (row['payload']['binding'], context_ref)
        elif row['kind'] == 'composed_provider_completed' and pending is not None:
            if row['payload']['binding'] != pending[0] or row['payload'].get('outcome') != 'failed':
                raise ValueError('truncated call differs from its failed provider transcript')
            observed_truncated.add(pending[1])
            pending = None
    if pending is not None or observed_truncated != truncated_calls:
        raise ValueError('truncated call lacks a unique failed provider transcript')
    construction = audit_construction(rows, run['construction'], logical_run_id=run['logical_run_id'],
                                      provider_arguments=provider_arguments)
    if construction['provider_calls'] != len(responses):
        raise ValueError('construction transcript does not cover currency calls')
    return {'total_tokens': total, 'settled_micro_cny': audit['settled_upper_bound_micro_cny'],
            'model': expected_model, 'journal_head': head, 'invoice_verified': False,
            'construction': construction,
            'coverage': 'currency and construction provenance; physical settlement and selected artifact require separate audit'}


def audit_physical_and_submission(run_root, bundle, submission, *, expected_tokens, candidates_root=None):
    """Rebuild physical accounting and rederive the submission from frozen predictions."""
    import tempfile
    from core.budget.types import AccountingStamp
    from core.composition.budget import HierarchicalBudget
    from core.x1.checkpoint import RunCheckpoint
    from core.x1.store import AppendOnlyStore

    bundle.validate()
    root = Path(run_root)
    checkpoint_path, transcript = root / 'checkpoint.json', root / 'x1.jsonl'
    if any(path.is_symlink() or not path.is_file() for path in (checkpoint_path, transcript)):
        raise ValueError('physical checkpoint or transcript missing')
    checkpoint = RunCheckpoint.load(checkpoint_path).payload
    assembly = checkpoint['manifest']['assembly']
    budget_checkpoint = checkpoint['budget_checkpoint']
    budget = HierarchicalBudget(assembly['budget']['options'], AccountingStamp(**budget_checkpoint['stamp']),
                                AppendOnlyStore(transcript), governance=assembly['governance'])
    budget.restore_state(budget_checkpoint)
    state = budget.state()
    if state['open_intents'] or state['halt_reasons'] or state['global']['used']['token'] != expected_tokens:
        raise ValueError('physical settlement differs from provider receipt coverage')
    candidate_id = checkpoint['incumbent']
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    all_decisions = [row['payload'] for row in rows if row['kind'] == 'composed_decision']
    for decision in all_decisions:
        original_receipt = {name: decision[name] for name in ('candidate_id', 'incumbent', 'evidence', 'decision')}
        if decision['event_id'] != 'sha256:' + payload_digest(original_receipt):
            raise ValueError('admission decision identity differs')
    admitted = [decision['candidate_id'] for decision in all_decisions if decision['decision']['admit']]
    if not admitted or admitted[-1] != candidate_id:
        raise ValueError('selected candidate differs from final admitted decision')
    decisions = [decision for decision in all_decisions if decision['candidate_id'] == candidate_id]
    evidences = [row['payload'] for row in rows if row['kind'] == 'composed_evidence'
                 and row['payload']['proposal']['candidate']['id'] == candidate_id]
    if len(decisions) != 1 or not decisions[0]['decision']['admit'] or len(evidences) != 1:
        raise ValueError('selected candidate lacks unique admitted evidence')
    proposal = evidences[0]['proposal']
    original = evidences[0]['evidence']['eval_result']
    if original['status'] != 'ok' or original['contract']['binding']['candidate_id'] != candidate_id:
        raise ValueError('selected evaluation is invalid')
    artifact_hash = hashlib.sha256(proposal['artifact'].encode()).hexdigest()
    if original['contract']['binding']['artifact_sha256'] != artifact_hash:
        raise ValueError('selected artifact differs from evaluation binding')
    candidate_root = (Path(candidates_root) if candidates_root is not None else
                      root.parent / 'composed_candidates') / hashlib.sha256(candidate_id.encode()).hexdigest()
    outcome_path, prediction_path = candidate_root / 'outcome.json', candidate_root / 'predictions.csv'
    if candidate_root.is_symlink() or any(path.is_symlink() or not path.is_file() for path in (outcome_path, prediction_path)):
        raise ValueError('selected prediction evidence missing')
    outcome = json.loads(outcome_path.read_text())
    identity = outcome['identity']
    if identity['candidate_id'] != candidate_id or identity['artifact_sha256'] != artifact_hash or \
            identity['dataset_identity'] != bundle.identity or outcome['status'] != 'ok':
        raise ValueError('selected prediction identity differs')
    prediction_hash = 'sha256:' + hashlib.sha256(prediction_path.read_bytes()).hexdigest()
    if prediction_hash != outcome['prediction_sha256'] or \
            prediction_hash != original['contract']['private']['data']['prediction_sha256']:
        raise ValueError('selected prediction differs from original evaluation')
    submission = Path(submission)
    if submission.is_symlink() or not submission.is_file():
        raise ValueError('submission must be a regular file')
    with tempfile.TemporaryDirectory(prefix='mori-mle-submission-audit-') as directory:
        expected = Path(directory) / 'submission.csv'
        bundle.submission(bundle.predictions(prediction_path), expected)
        if submission.read_bytes() != expected.read_bytes():
            raise ValueError('submission differs from frozen selected predictions')
    return {'selected_candidate_id': candidate_id,
            'submission_sha256': 'sha256:' + hashlib.sha256(submission.read_bytes()).hexdigest(),
            'physical_tokens': expected_tokens, 'prediction_sha256': prediction_hash}
