"""Recalculate published Arbor selection, failure counts and charges without live calls."""
import argparse
import gzip
import json
from pathlib import Path

import importlib.util

_spec = importlib.util.spec_from_file_location('arbor_evidence_export', Path(__file__).with_name('export_runs.py'))
_exporter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_exporter)
matrix_summary, read, require, sha, summarize, validate_cell, frozen_selection = (
    getattr(_exporter, name) for name in ('matrix_summary', 'read', 'require', 'sha', 'summarize', 'validate_cell', 'frozen_selection'))


def digest(value):
    return 'sha256:'+sha(json.dumps(value,sort_keys=True,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode())


def verify_official(official,audit,manifest,prepared,frozen):
    starts=[r['payload'] for r in audit if r['kind']=='arbor_grading_started']
    ends=[r['payload'] for r in audit if r['kind']=='arbor_grading_completed']
    require(starts==[official['binding']] and ends==[official],
            'official report differs from single original audit')
    binding=official['binding']
    require(binding['task_id']==manifest['task_id'] and binding['run_manifest_sha256']==digest(manifest)
        and binding['prepared_identity_sha256']==digest(prepared) and binding['final_freeze_sha256']==digest(frozen)
        and binding['fixture'] is False,'official source identity differs')
    reports=[r['payload'] for r in audit if r['kind']=='official_grading_report']
    require(len(reports)<=1,'multiple original grader reports')
    for entry in reports:
        raw=entry['report']
        require(entry['official_revision']==prepared['revision'] and entry['competition_id']==manifest['task_id']
            and entry['report_sha256']==sha(json.dumps(raw,sort_keys=True,default=str).encode()),
            'original grader report identity or digest differs')
    if official['state']=='completed':
        require(len(reports)==1,'completed official grading lacks raw report')
        raw=reports[0]['report']
        public={'competition_id':raw.get('competition_id'),'valid_submission':bool(raw.get('valid_submission')),
            'audit/score':raw.get('score'),**{'audit/'+key:bool(raw.get(key)) for key in
            ('any_medal','above_median','gold_medal','silver_medal','bronze_medal')}}
        require(public['competition_id']==manifest['task_id'] and official['report']==public
            and official['official_score']==raw.get('score') and official['error_type'] is None
            and official['external_benchmark_score_produced'] is True,'published official score differs from raw grader')
    else:
        require(official['state']=='grading_failed' and official['official_score'] is None
            and official['report'] is None and official['external_benchmark_score_produced'] is False,
            'failed official grading cannot publish a score')


def verify(root):
    plan=read(root/'matrix-manifest.json')
    prepared=read(root/'official-prepared-identity.json')
    summaries={};seen_calls=set()
    for cell in plan['cells']:
        run=root/cell['output']
        if not run.exists():continue
        manifest=read(run/'run-manifest.json')
        validate_cell(manifest,plan,cell)
        raw=gzip.decompress((run/'x1.jsonl.gz').read_bytes())
        rows=[json.loads(line) for line in raw.splitlines()]
        receipts=read(run/'currency-receipts.json.gz')
        ids={r['reservation']['call_id'] for r in receipts}
        require(not seen_calls & ids,'currency calls attributed to multiple cells');seen_calls|=ids
        report=read(run/'method-report.json.gz');official=read(run/'official-result.json')
        summary,programs=summarize(manifest,rows,receipts,report,official)
        summary['source_journal_sha256']=sha(raw)
        summary['source_report_sha256']=sha(gzip.decompress((run/'method-report.json.gz').read_bytes())) if report else None
        require(summary==read(run/'summary.json'),'published summary differs: '+cell['output'])
        require(programs==read(run/'programs.json.gz'),'published programs differ')
        if summary['submission']:
            chosen=summary['submission']['candidate_id']
            require((run/'selected-program.py').read_text()==programs[chosen],'selected program differs')
            require('sha256:'+sha((run/'submission.csv').read_bytes())==summary['submission']['submission_sha256'],
                'selected submission differs')
        if official:
            audit=[json.loads(line) for line in gzip.decompress((run/'official-audit.jsonl.gz').read_bytes()).splitlines()]
            frozen=frozen_selection(rows)
            require(len(frozen)==1,'official result lacks unique original selection freeze')
            verify_official(official,audit,manifest,prepared,frozen[0])
        summaries[cell['output']]=summary
    result=matrix_summary(plan,summaries)
    require(result==read(root/'summary.json'),'matrix coverage differs')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',nargs='?',type=Path,default=Path(__file__).resolve().parent)
    args=p.parse_args(argv)
    result=verify(args.root)
    for row in result['runs']:
        print(json.dumps({'task':row['task_id'],'seed':row['search_seed'],'state':row['run_state'],
            'validation_loss':(row.get('best_development') or {}).get('validation_loss'),
            'final_loss':row.get('final_loss'),'official_score':row.get('official_score'),
            'search':row.get('search'),'cost_upper_micro_cny':row.get('currency',{}).get('cost_upper_micro_cny')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
