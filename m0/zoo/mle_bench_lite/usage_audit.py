"""Independent reconciliation of durable provider calls and physical token bills."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.llm import validate_usage
from zoo.mle_bench_lite.agent_common import token_usage_summary


def _audit_currency(root, starts, receipts, completions, ledger):
    """Compare local evidence to the independently durable campaign journal."""
    from zoo.mle_bench_lite.cny_budget import CampaignBudget, validate_detailed_usage, usage_run_id
    result = {"complete": False, "invoice_verified": False,
              "settled_upper_bound_micro_cny": 0, "reserved_micro_cny": 0,
              "pending_calls": [], "errors": [], "known_tokens": 0, "ledger_verified": False}
    try:
        if not isinstance(ledger, CampaignBudget):
            raise ValueError("shared campaign ledger is required for currency audit")
        policy = ledger.manifest_binding()
        snapshot = ledger.snapshot()
        result["ledger_verified"] = True
        result.update(campaign_id=policy["campaign_id"], policy_sha256=policy["policy_sha256"])
        operations = {row["call_id"]: row for row in snapshot["operations"]}
        run_id = usage_run_id(root)
        owned_ids = {key for key, row in operations.items() if row["run_id"] == run_id}
        local_ids = set(starts) | set(receipts) | set(completions)
        result["call_ids"] = sorted(owned_ids)
        if owned_ids != local_ids:
            result["errors"].append({"call_id": "", "reason": "run call set differs from the campaign journal"})
        for call_id in sorted(owned_ids | local_ids):
            try:
                operation = operations.get(call_id)
                if operation is None or operation["run_id"] != run_id:
                    raise ValueError("local call has no campaign reservation")
                if "usage" not in operation:
                    result["reserved_micro_cny"] += operation["reserved_micro_cny"]
                    result["pending_calls"].append(call_id)
                    try:
                        result["known_tokens"] += validate_usage(receipts.get(call_id))["total_tokens"]
                    except (ValueError, RuntimeError, TypeError):
                        pass
                    raise ValueError("campaign call has unresolved monetary usage")
                result["settled_upper_bound_micro_cny"] += operation["upper_bound_micro_cny"]
                result["known_tokens"] += operation["usage"]["total_tokens"]
                start, receipt = starts.get(call_id), receipts.get(call_id)
                if not isinstance(start, dict) or not isinstance(receipt, dict):
                    raise ValueError("campaign settlement lacks local call evidence")
                provider = start.get("provider", {})
                if (provider.get("request_format") != "deepseek" or provider.get("campaign") != policy
                        or provider.get("currency_run_id") != run_id
                        or receipt.get("campaign_id") != policy["campaign_id"]
                        or receipt.get("currency_policy_sha256") != policy["policy_sha256"]
                        or receipt.get("model") != policy["model"]):
                    raise ValueError("local currency identity differs from campaign policy")
                if (start.get("request_sha256") != operation["request_sha256"]
                        or receipt.get("request_sha256") != operation["request_sha256"]
                        or receipt.get("response_sha256") != operation["response_sha256"]
                        or start.get("output_allowance") != operation["output_allowance"]
                        or validate_detailed_usage(receipt) != operation["usage"]):
                    raise ValueError("local receipt differs from independent currency settlement")
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                result["errors"].append({"call_id": call_id, "reason": str(error)})
        result["complete"] = not result["errors"]
    except (ValueError, OSError) as error:
        result["errors"].append({"call_id": "", "reason": str(error)})
    return result


def audit_usage(usage_dir: str | Path, *, allow_fixture_receipts: bool = False,
                spending_ledger=None) -> dict:
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
    currency_required = spending_ledger is not None or any(
        isinstance(row.get('provider'), dict) and row['provider'].get('request_format') == 'deepseek'
        for row in starts.values()) or any('campaign_id' in row for row in receipts.values())
    currency = _audit_currency(root, starts, receipts, completions, spending_ledger) if currency_required else None
    if currency is not None:
        if currency["ledger_verified"]:
            known_tokens = currency["known_tokens"]
        if currency["pending_calls"]:
            unresolved.update(currency["pending_calls"])
            costs_complete = False
        for row in currency['errors']:
            error('currency', row['call_id'], row['reason'])
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
            'currency_audit': currency,
            'fixture_legacy_receipts': fixture_without_calls}
