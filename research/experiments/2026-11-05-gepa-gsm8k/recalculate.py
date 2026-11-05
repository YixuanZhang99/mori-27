"""Recalculate published counts and cost totals without credentials or model calls."""
import gzip
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
rows = []
for path in sorted(root.glob('seed-*/method-report.json.gz')):
    report = json.loads(gzip.decompress(path.read_bytes()))
    recorded = json.loads((path.parent / 'summary.json').read_text())
    receipts = json.loads(gzip.decompress((path.parent / 'currency-receipts.json.gz').read_bytes()))
    raw = gzip.decompress((path.parent / 'x1.jsonl.gz').read_bytes())
    assert hashlib.sha256(raw).hexdigest() == recorded['source_journal_sha256']
    events = [json.loads(line) for line in raw.splitlines()]
    calls = [r for r in events if r['kind'] == 'composed_provider_completed']
    assert len(calls) == len(receipts) == recorded['provider_calls']
    assert len({r['reservation']['call_id'] for r in receipts}) == len(receipts)
    for r in receipts:
        assert r['reservation']['call_id'] == r['settlement']['call_id']
        assert not r['settlement']['bound_violation']
        u = r['settlement']['usage']
        # Frozen campaign upper prices: input 2 and output 8 micro-CNY/token.
        assert r['settlement']['upper_bound_micro_cny'] == 2*u['prompt_tokens'] + 8*u['completion_tokens']
    cost = sum(r['settlement']['upper_bound_micro_cny'] for r in receipts)
    assert cost == recorded['cost_upper_micro_cny']
    final = report['result']['reporting']['final_audit']
    evidence = final['evidence']['evidence']['eval_result']
    items = evidence['contract']['items']
    accuracy = None
    if final['state'] == 'completed':
        assert evidence['status'] == 'ok' and len(items) == 128
        assert len({r['item_id'] for r in items}) == 128
        accuracy = sum(r['verdict'] for r in items) / len(items)
        assert accuracy == evidence['metrics']['test/score']
    assert accuracy == recorded['final_test']['accuracy']
    assert report['replay_passed'] is True
    rows.append({'seed': report['seed'], 'test_state': final['state'],
        'test_accuracy': accuracy, 'cost_upper_cny': cost/1e6,
        'max_completion_tokens': recorded['max_completion_tokens']})
print(json.dumps({'recalculated': rows, 'notice': 'No cross-configuration mean; failures retained.'}, indent=2))
