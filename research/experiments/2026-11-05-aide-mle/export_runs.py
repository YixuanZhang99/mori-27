"""Export AIDE records and independently recompute selection, counts and billed usage.

Does not train programs, call providers, read credentials, or recalculate hidden
label losses. Task losses come from original trusted evaluations; official scores
come from the separate post-selection audit. Only named evidence files are copied.
"""
import argparse
from collections import Counter, defaultdict
import fcntl
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3


def require(condition,message):
    if not condition: raise ValueError(message)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def dump(path,value):
    raw=(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    path.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)


def journal_bytes(path):
    with path.open('rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_SH)
        return stream.read()


def currency(receipts,run_ids):
    seen,tokens,lanes=set(),defaultdict(int),defaultdict(int)
    pending=reserved=0
    for receipt in receipts:
        r,s=receipt['reservation'],receipt['settlement']
        require(r['call_id'] not in seen and r['run_id'] in run_ids,'duplicate or unrelated currency receipt')
        seen.add(r['call_id'])
        if s is None:
            pending+=1;reserved+=r['reserved_micro_cny'];continue
        require(s['call_id']==r['call_id'] and not s['bound_violation'],'invalid settlement')
        usage=s['usage']
        for key in ('prompt_tokens','completion_tokens','total_tokens'):
            require(type(usage[key]) is int and usage[key]>=0,'invalid usage')
            tokens[key]+=usage[key]
        require(usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens'],'invalid token total')
        # Recompute the original campaign's frozen upper prices; not a new budget.
        cost=2*usage['prompt_tokens']+8*usage['completion_tokens']
        require(cost==s['upper_bound_micro_cny'],'currency differs from frozen upper prices')
        lanes[r['lane']]+=cost
    total=sum(lanes.values())
    return {'cost_upper_micro_cny':None if pending else total,'settled_upper_micro_cny':total,
        'pending_calls':pending,'pending_reserved_micro_cny':reserved,'settled_calls':len(receipts)-pending,
        'tokens':dict(tokens),'cost_by_lane_micro_cny':dict(lanes),'invoice_verified':False}


def score(result,manifest,split):
    binding=result['contract']['binding']
    require(binding['split_id']==split and binding['seed_set']==[manifest['split_seed']] and
        binding['evaluation_context']==manifest['dataset_manifest']['split_contexts'][split],
        'evaluation split, context or seed differs')
    if result['status']!='ok':return None
    value=result['metrics']['dev/score' if split=='dev' else 'gate/score']
    require(type(value) in (int,float) and math.isfinite(value) and value<=0,'invalid signed task loss')
    return -value


def summarize(manifest,rows,receipts,report,official):
    def events(kind):return [r['payload'] for r in rows if r['kind']==kind]
    programs,evaluations={},[]
    dev_results={}
    for payload in events('composed_evidence'):
        proposal=payload['proposal'];candidate=proposal['candidate'];identifier=candidate['id']
        evidence=payload['evidence'];result=evidence['eval_result'];binding=result['contract']['binding']
        require(identifier not in programs and identifier==evidence['candidate_id']==binding['candidate_id'],
                'duplicate or mismatched candidate')
        require(sha(proposal['artifact'].encode())==binding['artifact_sha256'],'artifact differs from original evaluation')
        loss=score(result,manifest,'dev')
        programs[identifier]=proposal['artifact'];dev_results[identifier]=result
        evaluations.append({'candidate_id':identifier,'cycle':payload['cycle'],'operator':candidate['operator'],
            'parents':candidate['parents'],'status':result['status'],'validation_loss':loss})
    cycles=[e['cycle'] for e in evaluations]
    require(cycles==sorted(set(cycles)),'duplicate or unordered main cycles')
    valid=[e for e in evaluations if e['status']=='ok']
    best=min(valid,key=lambda e:e['validation_loss']) if valid else None
    attempted=len(events('composed_cycle_started'));incomplete=attempted-len(evaluations)
    require(incomplete>=0,'too many terminal evaluations')
    counts={'attempted':attempted,'successful':len(valid),'failed':len(evaluations)-len(valid),
        'incomplete':incomplete,'failure_rate':(attempted-len(valid))/attempted if attempted else None}
    frozen,final=events('metric_final_frozen'),events('metric_final_completed')
    require(len(frozen)<=1 and len(final)<=1,'multiple final freezes/results')
    winner=best['candidate_id'] if best else None
    final_loss=None
    final_state='not_frozen'
    if frozen:
        require(frozen[0]['candidate_id']==winner,'frozen winner differs from first validation optimum')
        final_state='frozen_pending'
        if winner:
            require(frozen[0]['binding']['artifact_sha256']==sha(programs[winner].encode()),'frozen artifact differs')
        else:require(frozen[0]['binding'] is None,'null winner with artifact binding')
    if final:
        require(bool(frozen) and final[0]['candidate_id']==winner,'final lacks original freeze')
        kinds=[r['kind'] for r in rows]
        require(kinds.index('metric_final_frozen')<kinds.index('metric_final_completed'),'final preceded freeze')
        final_state=final[0]['state']
        if 'evidence' in final[0]:
            outcome=final[0]['evidence']['evidence']['eval_result']
            require(winner is not None and outcome['contract']['binding']==frozen[0]['binding'],'final binding differs')
            require(outcome['contract']['private']['data']['prediction_sha256']==
                dev_results[winner]['contract']['private']['data']['prediction_sha256'],'final retrained or replaced predictions')
            final_loss=score(outcome,manifest,'final_audit')
        elif final_state=='skipped':require(winner is None,'valid winner skipped final evaluation')
    decisions=events('composed_decision')
    if decisions:
        admitted=[d['candidate_id'] for d in decisions if d['decision']['admit']]
        require((admitted[-1] if admitted else None)==winner,'admission differs from validation optimum')
    controls=[]
    for c in events('governed_control_terminal'):
        value={'state':c['status'],'validation_loss':None}
        if c.get('evidence'):
            result=c['evidence']['evidence']['eval_result']
            value.update(evaluation_status=result['status'],validation_loss=score(result,manifest,'dev'))
        controls.append(value)
    starts,ends=events('composed_provider_started'),events('composed_provider_completed')
    started={r['binding'] for r in starts};ended={r['binding'] for r in ends}
    require(len(started)==len(starts) and len(ended)==len(ends) and ended<=started,'invalid provider event coverage')
    run_ids={(r['invocation'].get('external_context') or {}).get('currency_run_id') for r in starts}-{None}
    cost=currency(receipts,run_ids)
    if manifest['mode']=='live':
        require(manifest['source']['commit'] and manifest['source']['dirty'] is False,'live source not clean')
        require(len(ends)<=cost['settled_calls']<=len(receipts)<=len(starts),'currency coverage differs')
        if ended!=started or len(receipts)!=len(starts):cost['cost_upper_micro_cny']=None
    submission=None
    if report is not None:
        for key in ('source','task_id','search_seed','split_seed','dataset_identity','dataset_manifest','mode'):
            require(report[key]==manifest[key],'report manifest mismatch: '+key)
        require(report['search']==counts,'reported failure denominator differs')
        if report.get('result'):
            require(report['result']['best_candidate_id']==winner,'reported winner differs')
        require(report['final_score']==(-final_loss if final_loss is not None else None),'reported final score differs')
        if report.get('independent_currency_receipts'):
            require(report['independent_currency_receipts']['total_tokens']==cost['tokens'].get('total_tokens',0) and
                report['independent_currency_receipts']['settled_micro_cny']==cost['settled_upper_micro_cny'],
                'report currency differs from original receipts')
        submission=report.get('submission')
        if submission:
            require(winner is not None and submission['candidate_id']==winner and submission['artifact_sha256']==
                sha(programs[winner].encode()),'submission selects another artifact')
            require(submission['prediction_sha256']==dev_results[winner]['contract']['private']['data']['prediction_sha256'],
                    'submission prediction binding differs')
    official_score=None;official_state='not_graded'
    if official:
        require(submission is not None and official['binding']['selection']==submission,'official score selects another submission')
        require(official['binding']['task_id']==manifest['task_id'],'official task differs')
        official_state=official['state'];official_score=official['official_score']
        if official_score is not None:
            require(type(official_score) in (int,float) and math.isfinite(official_score),'invalid official score')
    summary={'task_id':manifest['task_id'],'search_seed':manifest['search_seed'],'split_seed':manifest['split_seed'],
        'mode':manifest['mode'],'source':manifest['source'],'dataset_identity':manifest['dataset_identity'],
        'scoring':manifest['dataset_manifest']['scoring'],'run_state':report['run_state'] if report else 'report_missing',
        'search':counts,'best_development':best,'final_state':final_state,'final_loss':final_loss,
        'official_state':official_state,'official_score':official_score,'submission':submission,
        'independent_initial_controls':controls,'evaluations':evaluations,
        'tree_choices':events('aide_selection'),'currency':cost,'provider_attempts':len(starts),
        'provider_completed':len(ends),'unresolved_provider_bindings':sorted(started-ended),
        'replay_passed':report.get('replay_certificate',{}).get('passed') if report and report.get('replay_certificate') else None,
        'wall_seconds_this_process':report.get('wall_seconds_this_process') if report else None,
        'deviations':report.get('deviations') if report else None,'event_counts':dict(Counter(r['kind'] for r in rows))}
    return summary,programs


def matrix_summary(plan,summaries):
    cells=plan['cells'];expected={c['output'] for c in cells}
    require(len(expected)==len(cells) and set(summaries)<=expected,'unexpected or duplicate matrix cell')
    runs=[dict(cell,**summaries[cell['output']]) if cell['output'] in summaries else
        dict(cell,run_state='not_run',official_score=None,final_loss=None) for cell in cells]
    return {'scope':'Adapted AIDE CSV pilot; not paper-budget reproduction or a medal-rate estimate',
        'declared_cells':len(cells),'runs':runs,
        'audit_scope':'Selection, denominators and currency recalculated from original records; losses originate in trusted evaluations. No hidden labels redistributed.'}


def validate_cell(manifest,plan,cell):
    require(all(manifest[k]==cell[k] for k in ('task_id','search_seed','split_seed')),
            'run task or seeds differ from declared cell')
    require(manifest['source']==plan['source'] and manifest['profile']==plan['profiles'][cell['output']] and
            manifest['dataset_identity']==plan['datasets'][cell['task_id']]['identity'],
            'run differs from predeclared protocol')
    relative=Path(cell['output'])
    require(not relative.is_absolute() and '..' not in relative.parts,'invalid cell path')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matrix',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args(argv)
    plan=read(args.matrix/'matrix-manifest.json')
    with sqlite3.connect(args.ledger.resolve().as_uri()+'?mode=ro',uri=True) as db:
        currency_rows=[json.loads(r[0]) for r in db.execute('select payload from events order by seq')]
    settlements={r['call_id']:r for r in currency_rows if r['kind']=='governed_settle'}
    args.output.mkdir(parents=True,exist_ok=False)
    summaries={};seen_calls=set()
    for cell in plan['cells']:
        root=args.matrix/cell['output']
        if not (root/'run-manifest.json').is_file():continue
        manifest=read(root/'run-manifest.json')
        validate_cell(manifest,plan,cell)
        raw=journal_bytes(root/'composed/x1.jsonl');rows=[json.loads(l) for l in raw.splitlines()]
        ids={(r['payload']['invocation'].get('external_context') or {}).get('currency_run_id') for r in rows
             if r['kind']=='composed_provider_started'}-{None}
        receipts=[{'reservation':r,'settlement':settlements.get(r['call_id'])} for r in currency_rows
                  if r['kind']=='governed_reserve' and r['run_id'] in ids]
        call_ids={r['reservation']['call_id'] for r in receipts}
        require(not seen_calls & call_ids,'currency calls attributed to multiple cells');seen_calls|=call_ids
        report=read(root/'method-report.json') if (root/'method-report.json').is_file() else None
        official=read(root/'official/result.json') if (root/'official/result.json').is_file() else None
        summary,programs=summarize(manifest,rows,receipts,report,official)
        dest=args.output/cell['output'];dest.mkdir(parents=True)
        (dest/'run-manifest.json').write_bytes((root/'run-manifest.json').read_bytes())
        dump(dest/'currency-receipts.json.gz',receipts)
        if report is not None:
            report_raw=(root/'method-report.json').read_bytes()
            (dest/'method-report.json.gz').write_bytes(gzip.compress(report_raw,mtime=0))
            summary['source_report_sha256']=sha(report_raw)
        else:
            dump(dest/'method-report.json.gz',None)
            summary['source_report_sha256']=None
        summary['source_journal_sha256']=sha(raw)
        dump(dest/'official-result.json',official)
        dump(dest/'summary.json',summary);dump(dest/'programs.json.gz',programs)
        (dest/'x1.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
        if summary['submission']:
            submission=(root/'submission.csv').read_bytes()
            require('sha256:'+sha(submission)==summary['submission']['submission_sha256'],'submission bytes differ')
            (dest/'submission.csv').write_bytes(submission)
            (dest/'selected-program.py').write_text(programs[summary['submission']['candidate_id']])
        if (root/'official/audit.jsonl').is_file():
            (dest/'official-audit.jsonl.gz').write_bytes(gzip.compress(journal_bytes(root/'official/audit.jsonl'),mtime=0))
        summaries[cell['output']]=summary
    (args.output/'matrix-manifest.json').write_bytes((args.matrix/'matrix-manifest.json').read_bytes())
    (args.output/'official-prepared-identity.json').write_bytes((args.matrix/'official-prepared-identity.json').read_bytes())
    dump(args.output/'summary.json',matrix_summary(plan,summaries))
    print(json.dumps({'declared_cells':len(plan['cells']),'exported_cells':len(summaries)}))


if __name__=='__main__':main()
