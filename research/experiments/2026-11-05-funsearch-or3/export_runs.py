"""Export OR3 attempts, including partial failures, without executing programs."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def dump(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def score(result, ids, split, context):
    items = result.get('contract', {}).get('items') or []
    if result['status'] != 'ok':
        return {'state': result['status'], 'mean_bins': None, 'scored_item_count': len(items)}
    binding = result['contract']['binding']
    require(binding['split_id'] == split and binding['evaluation_context'] == context, 'evaluation partition differs')
    values = {item['item_id']: item['metrics']['score'] for item in items}
    require(len(values) == len(items) == len(ids) and set(values) == set(ids), 'case coverage differs')
    require(all(type(v) in (int, float) and v < 0 and float(v).is_integer() for v in values.values()), 'invalid bin count')
    mean = sum(values.values()) / len(values)
    require(mean == result['metrics']['test/score' if split == 'final_audit' else 'dev/score'], 'mean differs from cases')
    return {'state': 'ok', 'mean_bins': -mean, 'case_bins': {k: -v for k, v in values.items()}}


def currency(receipts, run_ids):
    seen, tokens, lanes = set(), defaultdict(int), defaultdict(int)
    pending, reserved = 0, 0
    for receipt in receipts:
        r, s = receipt['reservation'], receipt['settlement']
        require(r['call_id'] not in seen and r['run_id'] in run_ids, 'duplicate or unrelated currency receipt')
        seen.add(r['call_id'])
        if s is None:
            pending += 1
            reserved += r['reserved_micro_cny']
            continue
        require(s['call_id'] == r['call_id'] and not s['bound_violation'], 'invalid settlement binding or bound violation')
        usage = s['usage']
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            require(type(usage[key]) is int and usage[key] >= 0, 'invalid usage')
            tokens[key] += usage[key]
        require(usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens'], 'usage total differs')
        # Original campaign frozen upper prices; no new price authority.
        cost = 2 * usage['prompt_tokens'] + 8 * usage['completion_tokens']
        require(s['upper_bound_micro_cny'] == cost, 'settlement differs from frozen upper prices')
        lanes[r['lane']] += cost
    total = sum(lanes.values())
    return {'cost_upper_micro_cny': None if pending else total, 'settled_upper_micro_cny': total,
            'pending_calls': pending, 'pending_reserved_micro_cny': reserved,
            'settled_calls': len(receipts) - pending, 'tokens': dict(tokens),
            'cost_by_lane_micro_cny': dict(lanes), 'invoice_verified': False}


def search_counts(attempted, evaluations):
    successful = sum(e['state'] == 'ok' for e in evaluations)
    incomplete = attempted - len(evaluations)
    require(incomplete >= 0, 'more evaluations than attempts')
    return {'attempted': attempted, 'successful': successful, 'failed': len(evaluations) - successful,
            'incomplete': incomplete, 'failure_rate': (attempted - successful) / attempted if attempted else None}


def summarize(manifest, baseline_raw, journal_raw, receipts, report):
    require(sha(baseline_raw) == manifest['baseline_sha256'], 'baseline hash differs')
    baseline = json.loads(baseline_raw)
    require(baseline['dataset_identity'] == manifest['dataset_identity'], 'baseline dataset differs')
    ids = {k: list(v['case_scores']) for k, v in baseline['splits'].items()}
    require(set(ids['dev']).isdisjoint(ids['held_out']), 'overlapping splits')
    require(set(ids['dev']) == set(manifest['profile']['policy']['options']['case_ids']), 'profile cases differ')
    rows = [json.loads(line) for line in journal_raw.splitlines()]
    def events(kind):
        return [r['payload'] for r in rows if r['kind'] == kind]
    evaluations, programs = [], {}
    for payload in events('composed_evidence'):
        evidence = payload['evidence']
        candidate = evidence['candidate_id']
        result = score(evidence['eval_result'], ids['dev'], 'dev', manifest['split_hashes']['dev'])
        result.update(candidate_id=candidate, cycle=payload['cycle'])
        evaluations.append(result)
        proposal = payload.get('proposal')
        if proposal:
            artifact = proposal['artifact']
            require(proposal['candidate']['id'] == candidate, 'proposal candidate differs')
            if result['state'] == 'ok':
                require(sha(artifact.encode()) == evidence['eval_result']['contract']['binding']['artifact_sha256'], 'program hash differs')
            programs[candidate] = artifact
    successful = [e for e in evaluations if e['state'] == 'ok']
    best = min(successful, key=lambda e: e['mean_bins']) if successful else None
    frozen, final = events('metric_final_frozen'), events('metric_final_completed')
    require(len(frozen) <= 1 and len(final) <= 1, 'multiple final selections or results')
    final_score = {'state': 'frozen_pending' if frozen else 'not_frozen', 'mean_bins': None}
    if frozen and frozen[0]['candidate_id'] is None:
        require(best is None and frozen[0]['binding'] is None, 'null freeze with a successful candidate')
    elif frozen:
        require(best is not None and frozen[0]['candidate_id'] == best['candidate_id'], 'final winner is not first development optimum')
        require(frozen[0]['binding']['artifact_sha256'] == sha(programs[best['candidate_id']].encode()), 'frozen program differs')
    if final and final[0]['state'] == 'skipped':
        require(best is None and final[0]['candidate_id'] is None and (not frozen or frozen[0]['candidate_id'] is None), 'successful winner was skipped')
        final_score = {'state': 'skipped', 'mean_bins': None}
    elif final:
        require(bool(frozen) and final[0]['candidate_id'] == frozen[0]['candidate_id'], 'unfrozen final candidate')
        kinds = [r['kind'] for r in rows]
        require(kinds.index('metric_final_frozen') < kinds.index('metric_final_completed'), 'final before freeze')
        e = final[0].get('evidence')
        if e:
            result = e['evidence']['eval_result']
            require(result['contract']['binding'] == frozen[0]['binding'], 'final binding differs')
            final_score = score(result, ids['held_out'], 'final_audit', manifest['split_hashes']['held_out'])
        else:
            final_score = {'state': final[0]['state'], 'mean_bins': None}
    controls = []
    for c in events('governed_control_terminal'):
        controls.append(score(c['evidence']['evidence']['eval_result'], ids['dev'], 'dev', manifest['split_hashes']['dev'])
                        if c.get('evidence') else {'state': c['status'], 'mean_bins': None})
    started, completed = events('composed_provider_started'), events('composed_provider_completed')
    starts, ends = {e['binding'] for e in started}, {e['binding'] for e in completed}
    require(len(starts) == len(started) and len(ends) == len(completed) and ends <= starts, 'invalid provider event pairing')
    run_ids = {r['invocation']['external_context']['currency_run_id'] for r in started
               if r['invocation'].get('external_context', {}).get('currency_run_id')}
    cost = currency(receipts, run_ids)
    if manifest['mode'] == 'live':
        require(not manifest['source_dirty'] and manifest['source_commit'], 'live source is not clean')
        require(len(receipts) <= len(started) and cost['settled_calls'] >= len(completed), 'currency receipt coverage differs')
        if len(receipts) < len(started) or starts != ends:
            cost['cost_upper_micro_cny'] = None
    counts = search_counts(len(events('composed_cycle_started')), evaluations)
    if report is not None:
        for key in ('source_commit', 'dataset_identity', 'split_hashes', 'mode'):
            require(report[key] == manifest[key], 'report manifest differs: ' + key)
        for key, value in report['search'].items():
            require(counts[key] == value, 'reported search counts differ')
        if report.get('result'):
            require(report['result']['best_candidate_id'] == (best['candidate_id'] if best else None), 'reported winner differs')
    summary = {'seed': manifest['profile']['policy']['options']['seed'], 'mode': manifest['mode'],
        'source_commit': manifest['source_commit'], 'dataset_identity': manifest['dataset_identity'],
        'split_hashes': manifest['split_hashes'], 'source_journal_sha256': sha(journal_raw),
        'provider': manifest['provider'], 'immutable_snapshot_verified': False,
        'run_state': report.get('run_state', 'legacy_report') if report else 'report_missing',
        'replay_passed': report.get('replay_passed') if report else None,
        'search': counts, 'best_development': best, 'held_out': final_score,
        'independent_initial_controls': controls, 'provider_attempts': len(started),
        'provider_completed': len(completed), 'unresolved_provider_bindings': sorted(starts - ends),
        'currency': cost, 'event_counts': dict(Counter(r['kind'] for r in rows)),
        'evaluations': evaluations, 'baseline': baseline}
    return summary, programs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=Path, nargs='+', required=True)
    p.add_argument('--ledger', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with sqlite3.connect(args.ledger.resolve().as_uri() + '?mode=ro', uri=True) as db:
        journal = [json.loads(r[0]) for r in db.execute('select payload from events order by seq')]
    outputs = []
    for run in args.runs:
        manifest = read(run / 'run-manifest.json')
        raw = (run / 'x1.jsonl').read_bytes()
        rows = [json.loads(line) for line in raw.splitlines()]
        run_ids = {r['payload']['invocation']['external_context']['currency_run_id'] for r in rows
                   if r['kind'] == 'composed_provider_started' and
                   r['payload']['invocation'].get('external_context', {}).get('currency_run_id')}
        reserves = [r for r in journal if r['kind'] == 'governed_reserve' and r['run_id'] in run_ids]
        settled = {r['call_id']: r for r in journal if r['kind'] == 'governed_settle'}
        receipts = [{'reservation': r, 'settlement': settled.get(r['call_id'])} for r in reserves]
        report = read(run / 'method-report.json') if (run / 'method-report.json').is_file() else None
        baseline = (run / 'baseline-reference.json').read_bytes()
        summary, programs = summarize(manifest, baseline, raw, receipts, report)
        outputs.append((manifest, raw, receipts, report, baseline, summary, programs))
    require(len({v[5]['seed'] for v in outputs}) == len(outputs), 'duplicate seed attempts require separate named batches')
    args.output.mkdir(parents=True, exist_ok=False)
    for manifest, raw, receipts, report, baseline, summary, programs in outputs:
        dest = args.output / ('seed-' + str(summary['seed'])); dest.mkdir()
        dump(dest / 'run-manifest.json', manifest)
        dump(dest / 'method-report.json.gz', report)
        dump(dest / 'currency-receipts.json.gz', receipts)
        dump(dest / 'summary.json', summary)
        dump(dest / 'programs.json.gz', programs)
        (dest / 'baseline-reference.json').write_bytes(baseline)
        (dest / 'x1.jsonl.gz').write_bytes(gzip.compress(raw, mtime=0))
        if summary['best_development']:
            (dest / 'selected-program.py').write_text(programs[summary['best_development']['candidate_id']])
    dump(args.output / 'summary.json', {'scope': 'Adapted FunSearch OR3 pilot; not paper reproduction or equal-budget comparison',
                                       'runs': [v[5] for v in outputs]})
    print(json.dumps({'exported_seeds': [v[5]['seed'] for v in outputs]}))


if __name__ == '__main__':
    main()
