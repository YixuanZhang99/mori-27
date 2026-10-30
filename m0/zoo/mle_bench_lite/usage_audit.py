"""Independent reconciliation of durable provider calls and physical token bills."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.llm import validate_usage
from zoo.mle_bench_lite.agent_common import token_usage_summary


def audit_usage(usage_dir: str | Path, *, allow_fixture_receipts: bool = False) -> dict:
    """Preserve known bills even when identity or another request is unresolved.

    ``costs_complete`` concerns unknown operations/usage; ``complete`` additionally
    requires call/receipt identity and hash evidence. Missing model identity does
    not turn a measured bill into zero or an unknown token amount. Fixture-only
    legacy receipts may omit call sidecars, but that mode is explicit in output.
    """
    root = Path(usage_dir)
    calls = root.parent / (root.name + '_calls')
    errors, unresolved, receipts, starts, completions = [], set(), {}, {}, {}
    known_tokens = 0
    costs_complete = True

    def error(kind, call_id, reason):
        errors.append({'kind': kind, 'call_id': call_id, 'reason': reason})

    def read(path, call_id, kind):
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError('not a regular file')
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError('not an object')
            return value
        except (OSError, ValueError, TypeError):
            error(kind, call_id, 'unreadable or malformed JSON evidence')
            return None

    for path in sorted(root.glob('*.json')):
        call_id = path.stem
        record = read(path, call_id, 'receipt')
        if record is None:
            costs_complete = False
            unresolved.add(call_id)
            continue
        try:
            usage = validate_usage(record)
            known_tokens += usage['total_tokens']
        except (ValueError, TypeError, RuntimeError):
            error('usage', call_id, 'token usage is invalid or missing')
            costs_complete = False
            unresolved.add(call_id)
            usage = None
        receipts[call_id] = record
        if record.get('usage_id') != call_id:
            error('identity', call_id, 'receipt ID differs from filename')
        if not isinstance(record.get('model'), str) or not record['model'].strip():
            error('identity', call_id, 'actual response model is missing')
        if not isinstance(record.get('source'), str) or not record['source']:
            error('identity', call_id, 'receipt source is missing')

    for suffix, target in (('.started.json', starts), ('.completed.json', completions)):
        for path in sorted(calls.glob('*' + suffix)):
            call_id = path.name.removesuffix(suffix)
            value = read(path, call_id, 'call')
            if value is None:
                costs_complete = False
                unresolved.add(call_id)
                continue
            target[call_id] = value
            if value.get('call_id') != call_id:
                error('identity', call_id, 'call ID differs from filename')

    fixture_without_calls = allow_fixture_receipts and not starts and not completions
    if not fixture_without_calls:
        for call_id in set(starts) | set(completions) | set(receipts):
            start, completed, receipt = starts.get(call_id), completions.get(call_id), receipts.get(call_id)
            if start is None or completed is None or receipt is None:
                error('operation', call_id, 'started/completed/receipt evidence is incomplete')
                unresolved.add(call_id)
                costs_complete = False
                continue
            request_hash = start.get('request_sha256')
            if (not isinstance(request_hash, str) or len(request_hash) != 64
                    or request_hash != receipt.get('request_sha256')):
                error('identity', call_id, 'request hash differs between start and receipt')
            provider = start.get('provider')
            if (not isinstance(provider, dict) or not provider.get('requested_model')
                    or provider.get('requested_model') != receipt.get('requested_model')):
                error('identity', call_id, 'requested model differs between start and receipt')
            expected = hashlib.sha256((root / f'{call_id}.json').read_bytes()).hexdigest()
            if completed.get('usage_receipt_sha256') != expected:
                error('integrity', call_id, 'completed call does not bind the exact receipt bytes')
                costs_complete = False
                unresolved.add(call_id)

    models = sorted({record['model'] for record in receipts.values()
                     if isinstance(record.get('model'), str) and record['model'].strip()})
    if len(models) > 1:
        error('identity', '', 'actual response model changed within the run')
    usage = None
    if not errors:
        try:
            usage = token_usage_summary(root, require_nonempty=False)
        except (ValueError, RuntimeError, TypeError):
            error('integrity', '', 'strict receipt aggregation failed')
    return {'known_tokens': known_tokens, 'receipt_count': len(receipts),
            'started_calls': len(starts), 'completed_calls': len(completions),
            'unresolved_calls': sorted(unresolved), 'errors': errors,
            'costs_complete': costs_complete, 'complete': not errors and costs_complete,
            'actual_models': models, 'usage': usage,
            'fixture_legacy_receipts': fixture_without_calls}
