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
        if operation is None or response.get('returned_model') != expected_model or \
                response.get('integrity_reason') is not None or \
                response.get('response_sha256') != operation.get('response_sha256') or \
                operation.get('request_sha256') != prepared['wire_request_sha256']:
            raise ValueError('response identity or outcome differs from currency journal')
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
    construction = audit_construction(rows, run['construction'], logical_run_id=run['logical_run_id'],
                                      provider_arguments=provider_arguments)
    if construction['provider_calls'] != len(responses):
        raise ValueError('construction transcript does not cover currency calls')
    return {'total_tokens': total, 'settled_micro_cny': audit['settled_upper_bound_micro_cny'],
            'model': expected_model, 'journal_head': head, 'invoice_verified': False,
            'construction': construction,
            'coverage': 'currency and construction provenance; physical settlement and selected artifact require separate audit'}
