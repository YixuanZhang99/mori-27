"""Independent evidence reduction must retain rejected winners and missing work."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / 'research/experiments/2026-11-05-arbor-mle'


def load(name):
    spec = importlib.util.spec_from_file_location('arbor_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(exporter):
    manifest = {'mode': 'fixture', 'source': {'commit': None, 'dirty': None}, 'task_id': 'task',
        'search_seed': 0, 'split_seed': 7, 'dataset_identity': 'data',
        'dataset_manifest': {'scoring': 'negative_log_loss', 'split_contexts':
            {'dev': 'dev-context', 'admission': 'gate-context', 'final_audit': 'final-context'}},
        'profile': {'admission': {'options': {'margin': 0, 'trigger': {'min_dev_gain': 0}, 'call_budget': 3}}}}
    rows = []
    def result(identifier, split, loss):
        return {'status': 'ok', 'metrics': {'dev/score' if split == 'dev' else 'gate/score': -loss},
            'contract': {'binding': {'candidate_id': identifier, 'artifact_sha256': exporter.sha(identifier.encode()),
                'split_id': split, 'seed_set': [7], 'evaluation_context': manifest['dataset_manifest']['split_contexts'][split]},
                'private': {'data': {'prediction_sha256': 'prediction-' + identifier}}}}
    dev = {i: result(i, 'dev', loss) for i, loss in [('a', .4), ('b', .2)]}
    gates = {i: result(i, 'admission', loss) for i, loss in [('a', .5), ('b', .8)]}
    def view(identifier, r):
        return {'candidate_id': identifier, 'eval_result': {'binding': r['contract']['binding'],
            'status': r['status'], 'metrics': r['metrics']}}
    calls = {}
    for cycle, identifier in enumerate(['a', 'b']):
        rows.append({'kind': 'composed_cycle_started', 'payload': {}})
        calls[identifier] = {'phase': 'admission', 'status': 'complete', 'binding': gates[identifier]['contract']['binding']}
        rows.append({'kind': 'layered_admission_state', 'payload': {'event': 'call_completed', 'state': {'calls': copy.deepcopy(calls)}}})
        rows.append({'kind': 'layered_evidence', 'payload': {'key': identifier, 'phase': 'admission',
            'evidence': {'evidence': {'candidate_id': identifier, 'eval_result': gates[identifier]}}}})
        context = {'candidate_id': identifier, 'incumbent_id': 'a' if cycle else None,
            'rules': {'metric': 'gate/score', 'direction': 'maximize', 'dev_metric': 'dev/score',
                'dev_direction': 'maximize', 'margin': 0, 'min_dev_gain': 0, 'monotonicity': True},
            'development': {'candidate': view(identifier, dev[identifier]), 'incumbent': view('a', dev['a']) if cycle else None},
            'admission': {'candidate': view(identifier, gates[identifier]), 'incumbent': view('a', gates['a']) if cycle else None},
            'admission_rule_evaluated': True, 'development_trigger_passed': True,
            'decision': {'admit': not cycle, 'reason': 'fixture'}}
        receipt = {'admit': not cycle, 'reason': 'fixture', 'receipt_id': exporter.digest(context), 'decision_context': context}
        rows.append({'kind': 'layered_admission_receipt', 'payload': receipt})
        rows.append({'kind': 'composed_evidence', 'payload': {'cycle': cycle,
            'proposal': {'candidate': {'id': identifier, 'parents': ['a'] if cycle else [], 'operator': 'hypothesis_refine'}, 'artifact': identifier},
            'evidence': {'candidate_id': identifier, 'eval_result': dev[identifier]}}})
        rows.append({'kind': 'arbor_admission_verdict', 'payload': {'candidate_id': identifier, 'admit': not cycle, 'receipt_id': receipt['receipt_id']}})
    frozen = {'selected_id': 'a', 'key': 'final-a', 'status': 'ready'}
    rows.append({'kind': 'layered_admission_state', 'payload': {'event': 'selection_frozen', 'state': {'final': frozen, 'calls': calls}}})
    rows.append({'kind': 'layered_evidence', 'payload': {'key': 'final-a', 'phase': 'final_audit',
        'evidence': {'evidence': {'candidate_id': 'a', 'eval_result': result('a', 'final_audit', .6)}}}})
    rows.append({'kind': 'layered_admission_state', 'payload': {'event': 'call_completed',
        'state': {'final': dict(frozen, status='complete'), 'calls': calls}}})
    return manifest, rows


class ArborExportTests(unittest.TestCase):
    def setUp(self):
        self.exporter = load('export_runs')
        self.manifest, self.rows = fixture(self.exporter)

    def reduce(self, rows=None):
        return self.exporter.summarize(self.manifest, rows or self.rows, [], None, None)[0]

    def test_gate_rejects_development_winner_and_keeps_original_final(self):
        summary = self.reduce()
        self.assertEqual(summary['best_development']['candidate_id'], 'b')
        self.assertEqual(summary['gate_selected_id'], 'a')
        self.assertEqual(summary['final_loss'], .6)
        self.assertEqual(summary['gate_calls'], 2)

    def test_forged_receipt_even_with_rehashed_context_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        receipt = [r['payload'] for r in rows if r['kind'] == 'layered_admission_receipt'][-1]
        receipt['admit'] = receipt['decision_context']['decision']['admit'] = True
        receipt['receipt_id'] = self.exporter.digest(receipt['decision_context'])
        with self.assertRaises(ValueError): self.reduce(rows)

    def test_receipt_scores_cannot_replace_original_evaluations(self):
        rows = copy.deepcopy(self.rows)
        receipt = [r['payload'] for r in rows if r['kind'] == 'layered_admission_receipt'][-1]
        receipt['decision_context']['admission']['candidate']['eval_result']['metrics'] = {'gate/score': -.1}
        receipt['receipt_id'] = self.exporter.digest(receipt['decision_context'])
        with self.assertRaises(ValueError): self.reduce(rows)

    def test_final_cannot_select_dev_winner_or_retrain(self):
        for change in ('winner', 'predictions', 'context'):
            rows = copy.deepcopy(self.rows)
            if change == 'winner': rows[-3]['payload']['state']['final']['selected_id'] = 'b'
            else:
                result = rows[-2]['payload']['evidence']['evidence']['eval_result']
                if change == 'predictions': result['contract']['private']['data']['prediction_sha256'] = 'new'
                else: result['contract']['binding']['evaluation_context'] = 'dev-context'
            with self.assertRaises(ValueError): self.reduce(rows)

    def test_incomplete_attempts_and_unrun_cells_stay_in_denominator(self):
        rows = self.rows[:1]
        summary = self.reduce(rows)
        self.assertEqual(summary['search']['incomplete'], 1)
        self.assertIsNone(summary['gate_selected_id'])
        plan = {'cells': [{'output': 'task/seed-0', 'task_id': 'task', 'search_seed': 0},
                          {'output': 'task/seed-1', 'task_id': 'task', 'search_seed': 1}]}
        matrix = self.exporter.matrix_summary(plan, {'task/seed-0': summary})
        self.assertEqual(matrix['declared_cells'], 2)
        self.assertEqual(matrix['runs'][1]['run_state'], 'not_run')

    def test_governed_admission_lane_is_used_without_control_contamination(self):
        rows = []
        for row in self.rows:
            if row['kind'].startswith('layered_admission_'):
                wrapped = {'kind': 'governed_component', 'payload': dict(row, lane='main', slot_id=None, component='admission')}
                rows.extend([wrapped, {'kind': 'governed_component', 'payload': dict(row, lane='control', slot_id=0, component='admission')}])
            else: rows.append(row)
        self.assertEqual(self.reduce(rows)['gate_selected_id'], 'a')

    def test_fixture_provider_records_do_not_require_currency_invocation(self):
        rows = self.rows + [{'kind': 'composed_provider_started', 'payload': {'binding': 'fixture'}},
                            {'kind': 'composed_provider_completed', 'payload': {'binding': 'fixture'}}]
        self.assertEqual(self.reduce(rows)['provider_completed'], 1)


    def test_exported_packet_recalculates_and_detects_summary_tampering(self):
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); matrix = root / 'matrix'; run = matrix / 'task/seed-0'
            (run / 'composed').mkdir(parents=True)
            self.exporter.dump(run / 'run-manifest.json', self.manifest)
            (run / 'composed/x1.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.rows))
            plan = {'cells': [{'output': 'task/seed-0', 'task_id': 'task', 'search_seed': 0, 'split_seed': 7}],
                'source': self.manifest['source'], 'profiles': {'task/seed-0': self.manifest['profile']},
                'datasets': {'task': {'identity': 'data'}}}
            self.exporter.dump(matrix / 'matrix-manifest.json', plan)
            self.exporter.dump(matrix / 'official-prepared-identity.json', {'revision': 'fixture'})
            ledger = root / 'fixture.db'
            with sqlite3.connect(ledger) as db: db.execute('create table events (seq integer, payload text)')
            output = root / 'export'
            self.exporter.main(['--matrix', str(matrix), '--ledger', str(ledger), '--output', str(output)])
            recalculator = load('recalculate')
            verified = recalculator.verify(output)
            self.assertEqual(verified['runs'][0]['gate_selected_id'], 'a')
            summary = self.exporter.read(output / 'task/seed-0/summary.json')
            summary['gate_selected_id'] = 'b'
            self.exporter.dump(output / 'task/seed-0/summary.json', summary)
            with self.assertRaises(ValueError): recalculator.verify(output)


    def test_synthesis_must_reference_original_development_and_retain_sources(self):
        dev = next(r['payload']['evidence']['eval_result'] for r in self.rows if r['kind'] == 'composed_evidence')
        binding = {'role': 'dev', 'context': {'run_id': 'run'}, 'candidate_id': 'a', 'cycle': 0,
            'evaluation_context': 'dev-context', 'status': 'ok'}
        ref = self.exporter.digest(binding)
        next(r['payload'] for r in self.rows if r['kind'] == 'composed_evidence')['evidence_ref'] = ref
        request = {'candidate_id': 'a', 'cycle': 0, 'target_id': 'global', 'source_refs': [ref],
            'previous_ref': None, 'previous_summary': None,
            'new_evidence': {'candidate_id': 'a', 'eval_result': dev}}
        event = {'request': request, 'response': {'summary': 'Prior evidence.'}}
        event['synthesis_ref'] = self.exporter.digest(event)
        rows = self.rows + [{'kind': 'memory_receipt_binding', 'payload': dict(binding, receipt_ref=ref)},
                            {'kind': 'arbor_synthesis', 'payload': event}]
        self.reduce(rows)
        for change in ('source', 'score'):
            forged = copy.deepcopy(rows); entry = forged[-1]['payload']
            if change == 'source': entry['request']['source_refs'] = ['final-score']
            else: entry['request']['new_evidence']['eval_result']['metrics']['dev/score'] = -.01
            entry['synthesis_ref'] = self.exporter.digest({k:entry[k] for k in ('request', 'response')})
            with self.assertRaises(ValueError): self.reduce(forged)


    def test_interrupted_synthesis_keeps_actual_training_but_no_completed_candidate(self):
        evidence = next(r['payload']['evidence'] for r in self.rows if r['kind'] == 'composed_evidence')
        encoded = {'schema_version': 1, 'evidence': evidence}
        ref = self.exporter.digest({'logical_run_id': 'run', 'evidence': encoded})
        rows = [self.rows[0],
            {'kind': 'arbor_selected', 'payload': {'candidate_id': 'a', 'cycle': 0}},
            {'kind': 'materialization_completed', 'payload': {'identity': {'operation': {'lane': 'main', 'cycle': 0}},
                'construction_result': {'artifact': 'a'}}},
            {'kind': 'composed_physical_evidence', 'payload': {'request': {'split_id': 'dev'}, 'evidence': encoded}},
            {'kind': 'memory_receipt_binding', 'payload': {'receipt_ref': ref, 'candidate_id': 'a', 'cycle': 0,
                'role': 'dev', 'context': {'run_id': 'run'}, 'evaluation_context': 'dev-context', 'status': 'ok'}}]
        summary = self.reduce(rows)
        self.assertEqual(summary['search']['incomplete'], 1)
        self.assertEqual(summary['search']['successful'], 0)
        self.assertIsNone(summary['gate_selected_id'])
        self.assertEqual(summary['uncommitted_development_ids'], ['a'])


    def test_gate_calls_over_budget_and_unknown_currency_cannot_pass(self):
        self.manifest['profile']['admission']['options']['call_budget'] = 1
        with self.assertRaises(ValueError): self.reduce()
        receipt = {'reservation': {'call_id': 'c', 'run_id': 'r', 'lane': 'main', 'reserved_micro_cny': 100}, 'settlement': None}
        cost = self.exporter.currency([receipt], {'r'})
        self.assertIsNone(cost['cost_upper_micro_cny'])
        self.assertEqual(cost['pending_reserved_micro_cny'], 100)
        receipt['settlement'] = {'call_id': 'c', 'bound_violation': False, 'upper_bound_micro_cny': 99,
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}
        with self.assertRaises(ValueError): self.exporter.currency([receipt], {'r'})

    def test_official_score_is_bound_to_original_raw_grader_report(self):
        manifest=self.manifest
        recalculate=load('recalculate')
        sha=self.exporter.sha
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
        audit=[{'kind':'arbor_grading_started','payload':result['binding']},
            {'kind':'official_grading_report','payload':{'official_revision':'pinned','competition_id':'task',
                'report_sha256':sha(json.dumps(raw,sort_keys=True,default=str).encode()),'report':raw}},
            {'kind':'arbor_grading_completed','payload':result}]
        recalculate.verify_official(result,audit,manifest,prepared,frozen)
        # Altering the result AND its terminal copy must not alter the raw grader score.
        bad=copy.deepcopy(result);bad['official_score']=.1;bad['report']['audit/score']=.1
        altered=copy.deepcopy(audit);altered[-1]['payload']=bad
        with self.assertRaises(ValueError):recalculate.verify_official(bad,altered,manifest,prepared,frozen)
        altered=copy.deepcopy(audit);altered[1]['payload']['report']['score']=.1
        with self.assertRaises(ValueError):recalculate.verify_official(result,altered,manifest,prepared,frozen)
        changed=copy.deepcopy(prepared);changed['revision']='different'
        with self.assertRaises(ValueError):recalculate.verify_official(result,audit,manifest,changed,frozen)


if __name__ == '__main__': unittest.main()
