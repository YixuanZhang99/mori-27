import copy
import hashlib
import json
import unittest
import importlib.util
from pathlib import Path


def load(name):
    path = Path(__file__).resolve().parents[2] / 'research/experiments/2026-11-05-aide-mle' / (name + '.py')
    spec = importlib.util.spec_from_file_location('aide_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = load('export_runs')
recalculate = load('recalculate')


def sha(value): return hashlib.sha256(value).hexdigest()


def fixture():
    manifest={'mode':'fixture','source':{'commit':None,'dirty':None},'task_id':'task','search_seed':0,'split_seed':7,
        'dataset_identity':'data','dataset_manifest':{'scoring':'negative_log_loss','split_contexts':{'dev':'dev','final_audit':'final'}},
        'profile':{},'provider':{}}
    artifact='print(1)\n'
    def evidence(identifier,score,status='ok'):
        return {'candidate_id':identifier,'eval_result':{'status':status,'metrics':{'dev/score':score} if status=='ok' else {},
            'contract':{'binding':{'candidate_id':identifier,'artifact_sha256':sha(artifact.encode()),
                'split_id':'dev','seed_set':[7],'evaluation_context':'dev'},'private':{'data':{'prediction_sha256':'p'}}}}}
    rows=[]
    for i,(identifier,score,status) in enumerate([('a',-.4,'ok'),('b',None,'failed_to_run'),('c',-.4,'ok')]):
        rows.append({'kind':'composed_cycle_started','payload':{}})
        rows.append({'kind':'composed_evidence','payload':{'cycle':i,'proposal':{'candidate':{'id':identifier,'operator':'draft','parents':[]},'artifact':artifact},'evidence':evidence(identifier,score,status)}})
    rows.append({'kind':'composed_cycle_started','payload':{}})
    return manifest,rows


class EvidenceTests(unittest.TestCase):
    def test_failed_and_incomplete_attempts_remain_in_denominator_and_ties_keep_first(self):
        manifest,rows=fixture()
        summary,programs=exporter.summarize(manifest,rows,[],None,None)
        self.assertEqual(summary['search'],{'attempted':4,'successful':2,'failed':1,'incomplete':1,'failure_rate':.5})
        self.assertEqual(summary['best_development']['candidate_id'],'a')
        self.assertIsNone(summary['final_loss'])
        self.assertEqual(set(programs),{'a','b','c'})

    def test_forged_score_source_or_artifact_is_rejected(self):
        manifest,rows=fixture()
        for mutation in ('artifact','seed','context','candidate'):
            modified=copy.deepcopy(rows)
            p=modified[1]['payload'];b=p['evidence']['eval_result']['contract']['binding']
            if mutation=='artifact':p['proposal']['artifact']='forged'
            elif mutation=='seed':b['seed_set']=[2]
            elif mutation=='context':b['evaluation_context']='final'
            else:b['candidate_id']='other'
            with self.assertRaises(ValueError):exporter.summarize(manifest,modified,[],None,None)

    def test_unknown_cost_retains_reservation_and_known_usage_is_recalculated(self):
        receipt={'reservation':{'call_id':'c','run_id':'r','lane':'main','reserved_micro_cny':2000000},'settlement':None}
        pending=exporter.currency([receipt],{'r'})
        self.assertIsNone(pending['cost_upper_micro_cny'])
        self.assertEqual(pending['pending_reserved_micro_cny'],2000000)
        receipt['settlement']={'call_id':'c','bound_violation':False,'upper_bound_micro_cny':100,
            'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
        self.assertEqual(exporter.currency([receipt],{'r'})['cost_upper_micro_cny'],100)
        receipt['settlement']['upper_bound_micro_cny']=99
        with self.assertRaises(ValueError):exporter.currency([receipt],{'r'})

    def test_missing_declared_cells_are_explicit_and_never_shrink_matrix(self):
        plan={'cells':[{'output':'task/seed-0','task_id':'task','search_seed':0},
                       {'output':'task/seed-1','task_id':'task','search_seed':1}]}
        summary=exporter.matrix_summary(plan,{'task/seed-0':{'run_state':'execution_failed'}})
        self.assertEqual(summary['declared_cells'],2)
        self.assertEqual(summary['runs'][1]['run_state'],'not_run')
        self.assertEqual(summary['runs'][0]['run_state'],'execution_failed')

    def test_final_score_cannot_replace_first_validation_winner(self):
        manifest,rows=fixture();rows.pop()
        binding=copy.deepcopy(rows[1]['payload']['evidence']['eval_result']['contract']['binding'])
        binding.update(split_id='final_audit',evaluation_context='final')
        rows.append({'kind':'metric_final_frozen','payload':{'candidate_id':'a','binding':binding}})
        rows.append({'kind':'metric_final_completed','payload':{'candidate_id':'a','state':'completed','evidence':{'evidence':{
            'eval_result':{'status':'ok','metrics':{'gate/score':-.9},'contract':{'binding':binding,'private':{'data':{'prediction_sha256':'p'}}}}}}}})
        summary,_=exporter.summarize(manifest,rows,[],None,None)
        self.assertEqual(summary['best_development']['candidate_id'],'a')
        self.assertEqual(summary['final_loss'],.9)
        forged=copy.deepcopy(rows);forged[-2]['payload']['candidate_id']='c'
        with self.assertRaises(ValueError):exporter.summarize(manifest,forged,[],None,None)
        forged=copy.deepcopy(rows)
        forged[-1]['payload']['evidence']['evidence']['eval_result']['contract']['private']['data']['prediction_sha256']='new-training'
        with self.assertRaises(ValueError):exporter.summarize(manifest,forged,[],None,None)

    def test_all_failed_attempts_have_no_winner_and_null_final(self):
        manifest,rows=fixture();rows.pop()
        for row in rows:
            if row['kind']=='composed_evidence':
                result=row['payload']['evidence']['eval_result']
                result.update(status='failed_to_run',metrics={})
        rows.extend([{'kind':'metric_final_frozen','payload':{'candidate_id':None,'binding':None}},
                     {'kind':'metric_final_completed','payload':{'candidate_id':None,'state':'skipped'}}])
        summary,_=exporter.summarize(manifest,rows,[],None,None)
        self.assertIsNone(summary['best_development'])
        self.assertIsNone(summary['final_loss'])
        self.assertEqual(summary['search']['failure_rate'],1)
        self.assertEqual(summary['search']['attempted'],3)

    def test_cell_cannot_be_relabelled_as_another_task_seed_or_source(self):
        manifest,_=fixture()
        cell={'task_id':'task','search_seed':0,'split_seed':7,'output':'task/seed-0'}
        plan={'source':manifest['source'],'profiles':{'task/seed-0':{}},'datasets':{'task':{'identity':'data'}}}
        exporter.validate_cell(manifest,plan,cell)
        for key,value in [('task_id','other'),('search_seed',1),('split_seed',2),('dataset_identity','other')]:
            modified=copy.deepcopy(manifest);modified[key]=value
            with self.assertRaises(ValueError):exporter.validate_cell(modified,plan,cell)

    def test_official_score_is_bound_to_original_raw_grader_report(self):
        manifest,_=fixture()
        prepared={'revision':'pinned'}
        frozen={'candidate_id':'a','binding':{}}
        digest=lambda v:'sha256:'+sha(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
        raw={'competition_id':'task','valid_submission':True,'score':.5,'any_medal':False}
        public={'competition_id':'task','valid_submission':True,'audit/score':.5,
                **{'audit/'+k:False for k in ('any_medal','above_median','gold_medal','silver_medal','bronze_medal')}}
        result={'binding':{'task_id':'task','run_manifest_sha256':digest(manifest),
            'prepared_identity_sha256':digest(prepared),'final_freeze_sha256':digest(frozen),'fixture':False},
            'state':'completed','error_type':None,'report':public,'official_score':.5,
            'external_benchmark_score_produced':True}
        audit=[{'kind':'aide_grading_started','payload':result['binding']},
            {'kind':'official_grading_report','payload':{'official_revision':'pinned','competition_id':'task',
                'report_sha256':sha(json.dumps(raw,sort_keys=True,default=str).encode()),'report':raw}},
            {'kind':'aide_grading_completed','payload':result}]
        recalculate.verify_official(result,audit,manifest,prepared,frozen)
        # Altering the result AND its terminal copy must not alter the raw grader score.
        bad=copy.deepcopy(result);bad['official_score']=.1;bad['report']['audit/score']=.1
        altered=copy.deepcopy(audit);altered[-1]['payload']=bad
        with self.assertRaises(ValueError):recalculate.verify_official(bad,altered,manifest,prepared,frozen)
        altered=copy.deepcopy(audit);altered[1]['payload']['report']['score']=.1
        with self.assertRaises(ValueError):recalculate.verify_official(result,altered,manifest,prepared,frozen)
        changed=copy.deepcopy(prepared);changed['revision']='different'
        with self.assertRaises(ValueError):recalculate.verify_official(result,audit,manifest,changed,frozen)

if __name__=='__main__':unittest.main()
