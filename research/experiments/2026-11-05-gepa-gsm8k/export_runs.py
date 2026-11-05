"""Export completed GEPA runs; no model calls or credential reads."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics


def read(path):
    return json.loads(path.read_text())


def dump(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def summarize(run, journal):
    report = read(run / 'method-report.json')
    manifest = read(run / 'run-manifest.json')
    rows = [json.loads(line) for line in (run / 'x1.jsonl').read_text().splitlines()]
    started = [r['payload'] for r in rows if r['kind'] == 'composed_provider_started']
    completed = [r['payload'] for r in rows if r['kind'] == 'composed_provider_completed']
    run_ids = {r['invocation']['external_context']['currency_run_id'] for r in started}
    reserves = {r['call_id']: r for r in journal if r['kind'] == 'governed_reserve' and r['run_id'] in run_ids}
    settled = {r['call_id']: r for r in journal if r['kind'] == 'governed_settle' and r['call_id'] in reserves}
    assert report['mode'] == 'live' and not report['source_dirty'] and report['replay_passed']
    assert len(started) == len(completed) == len(reserves) == len(settled), 'unresolved calls'
    assert not any(r['bound_violation'] for r in settled.values())
    evaluation_rows = [r for r in rows if r['kind'] in ('composed_physical_evidence', 'governed_control_terminal', 'metric_final_completed')]
    result = report['result']
    final = result['reporting']['final_audit']
    assert final['state'] in ('completed', 'evaluation_failed'), 'final test was not attempted'
    controls = [r['payload'] for r in rows if r['kind'] == 'governed_control_terminal']
    assert len(controls) == 1
    def score(evidence, metric):
        e = evidence['evidence']['eval_result']
        items = e['contract']['items']
        if e['status'] != 'ok':
            return {'state': e['status'], 'accuracy': None, 'scored_item_count': len(items),
                    'failure': e['text_feedback']}
        assert items
        correct = sum(i['verdict'] for i in items)
        assert correct / len(items) == e['metrics'][metric]
        return {'correct': correct, 'count': len(items), 'accuracy': e['metrics'][metric]}
    usage = defaultdict(int)
    lane_cost = defaultdict(int)
    receipts = []
    for call, reservation in reserves.items():
        settlement = settled[call]
        lane_cost[reservation['lane']] += settlement['upper_bound_micro_cny']
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            usage[key] += settlement['usage'][key]
        receipts.append({'reservation': reservation, 'settlement': settlement})
    paired = [{'candidate_id': r['payload']['candidate_id'], 'parent_id': r['payload']['parent_id'],
        'accepted': r['payload']['accepted'], 'item_ids': r['payload']['plan']['item_ids'],
        'parent_metrics': r['payload']['parent_evidence']['evidence']['eval_result']['metrics'],
        'child_metrics': r['payload']['child_evidence']['evidence']['eval_result']['metrics']}
        for r in rows if r['kind'] == 'paired_evaluation_decision']
    summary = {'seed': report['seed'], 'source_commit': report['source_commit'],
        'dataset_identity': report['dataset_identity'], 'max_proposals': report['max_proposals'],
        'model_alias': manifest['provider']['requested_model'], 'immutable_snapshot_verified': False,
        'max_completion_tokens': manifest['provider']['max_completion_tokens'],
        'final_audit_state': final['state'],
        'cycles': result['cycles'], 'validation_accuracy': result['best_score'],
        'final_test': score(final['evidence'], 'test/score'),
        'initial_iid_rs_validation': score(controls[0]['evidence'], 'dev/score') if controls[0]['evidence'] else
            {'accuracy': None, 'state': controls[0]['status'], 'failure': controls[0]['failure_type']},
        'paired_decisions': paired, 'provider_calls': len(completed), 'tokens': dict(usage),
        'cost_upper_micro_cny': sum(lane_cost.values()), 'cost_by_lane_micro_cny': dict(lane_cost),
        'invoice_verified': False, 'replay_passed': report['replay_passed'],
        'source_journal_sha256': hashlib.sha256((run / 'x1.jsonl').read_bytes()).hexdigest(),
        'event_counts': dict(Counter(r['kind'] for r in rows))}
    failures = []
    for path in (run / '.governed-cny').glob('*.response.json'):
        value = read(path)['payload']
        if value['integrity_reason']:
            failures.append({k: value[k] for k in ('integrity_reason', 'finish_reason', 'usage', 'response_sha256')})
    summary['provider_failures'] = failures
    return summary, receipts, evaluation_rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=Path, nargs='+', required=True)
    p.add_argument('--ledger', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with sqlite3.connect(args.ledger.resolve().as_uri() + '?mode=ro', uri=True) as db:
        journal = [json.loads(r[0]) for r in db.execute('select payload from events order by seq')]
    outputs = [(run, *summarize(run, journal)) for run in args.runs]
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for run, summary, receipts, evaluations in outputs:
        dest = args.output / ('seed-' + str(summary['seed'])); dest.mkdir()
        dump(dest / 'summary.json', summary)
        dump(dest / 'currency-receipts.json.gz', receipts)
        dump(dest / 'evaluations.json.gz', evaluations)
        for name in ('method-report.json', 'run-manifest.json', 'profile.json'):
            dump(dest / (name + '.gz' if name == 'method-report.json' else name), read(run / name))
        (dest / 'x1.jsonl.gz').write_bytes(gzip.compress((run / 'x1.jsonl').read_bytes(), mtime=0))
        summaries.append(summary)
    values = [s['final_test']['accuracy'] for s in summaries]
    out = {'scope': 'adapted GEPA GSM8K pilot; not paper reproduction or budget-matched comparison',
        'runs': summaries, 'total_cost_upper_micro_cny': sum(s['cost_upper_micro_cny'] for s in summaries)}
    if len(values) >= 3 and all(v is not None for v in values) and len({s['max_completion_tokens'] for s in summaries}) == 1:
        out['final_test_mean'] = statistics.mean(values)
        out['final_test_sample_stdev'] = statistics.stdev(values)
    dump(args.output / 'summary.json', out)
    print(json.dumps({'seeds': [s['seed'] for s in summaries], 'test_accuracies': values,
        'cost_upper_cny': out['total_cost_upper_micro_cny'] / 1e6}))


if __name__ == '__main__':
    main()
