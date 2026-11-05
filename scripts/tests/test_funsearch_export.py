"""Evidence export must retain failed and unsettled attempts without scoring them."""
import copy
import importlib.util
from pathlib import Path

import unittest


def exporter():
    path = Path(__file__).resolve().parents[2] / 'research/experiments/2026-11-05-funsearch-or3/export_runs.py'
    spec = importlib.util.spec_from_file_location('funsearch_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FunSearchExportTests(unittest.TestCase):
    def test_score_recomputes_bins_and_rejects_missing_case_or_false_mean(self):
        mod = exporter()
        result = {'status': 'ok', 'metrics': {'dev/score': -2.5}, 'contract': {
            'binding': {'split_id': 'dev', 'evaluation_context': 'sha256:dev'},
            'items': [{'item_id': 'a', 'metrics': {'score': -2}},
                      {'item_id': 'b', 'metrics': {'score': -3}}]}}
        assert mod.score(result, ['a', 'b'], 'dev', 'sha256:dev')['mean_bins'] == 2.5
        for mutate in ('missing', 'mean', 'context'):
            bad = copy.deepcopy(result)
            if mutate == 'missing':
                bad['contract']['items'].pop()
            elif mutate == 'mean':
                bad['metrics']['dev/score'] = -2
            else:
                bad['contract']['binding']['evaluation_context'] = 'sha256:held-out'
            with self.assertRaises(ValueError):
                mod.score(bad, ['a', 'b'], 'dev', 'sha256:dev')


    def test_failed_score_does_not_promote_partial_items(self):
        result = {'status': 'timeout', 'metrics': {}, 'contract': {'items': None}}
        assert exporter().score(result, ['a'], 'final_audit', 'sha256:held')['mean_bins'] is None


    def test_pending_currency_is_unknown_and_retains_reservation(self):
        receipts = [{'reservation': {'call_id': 'c', 'run_id': 'r', 'lane': 'main',
                     'reserved_micro_cny': 2000000}, 'settlement': None}]
        cost = exporter().currency(receipts, {'r'})
        assert cost['cost_upper_micro_cny'] is None
        assert cost['settled_upper_micro_cny'] == 0
        assert cost['pending_reserved_micro_cny'] == 2000000
        assert cost['pending_calls'] == 1


    def test_settled_currency_recomputed_and_wrong_receipt_rejected(self):
        receipts = [{'reservation': {'call_id': 'c', 'run_id': 'r', 'lane': 'main',
                     'reserved_micro_cny': 2000000}, 'settlement': {
            'call_id': 'c', 'upper_bound_micro_cny': 100, 'bound_violation': False,
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}}]
        mod = exporter()
        assert mod.currency(receipts, {'r'})['cost_upper_micro_cny'] == 100
        receipts[0]['settlement']['upper_bound_micro_cny'] = 0
        with self.assertRaises(ValueError):
            mod.currency(receipts, {'r'})


    def test_incomplete_attempt_is_in_failure_denominator(self):
        assert exporter().search_counts(3, [{'state': 'ok'}, {'state': 'failed'}]) == {
            'attempted': 3, 'successful': 1, 'failed': 1, 'incomplete': 1,
            'failure_rate': 2 / 3}


    def test_skipped_final_without_winner_is_retained(self):
        import hashlib
        import json
        mod = exporter()
        baseline = json.dumps({'dataset_identity': 'data', 'splits': {
            'dev': {'case_scores': {'a': -2}}, 'held_out': {'case_scores': {'b': -3}}}}).encode()
        manifest = {'mode': 'fixture', 'source_commit': None, 'dataset_identity': 'data',
            'split_hashes': {'dev': 'sha256:dev', 'held_out': 'sha256:held'},
            'baseline_sha256': hashlib.sha256(baseline).hexdigest(), 'provider': {},
            'profile': {'policy': {'options': {'seed': 0, 'case_ids': ['a']}}}}
        rows = [{'kind': 'composed_cycle_started', 'payload': {}},
            {'kind': 'metric_final_frozen', 'payload': {'candidate_id': None, 'binding': None}},
            {'kind': 'metric_final_completed', 'payload': {'candidate_id': None, 'state': 'skipped'}}]
        summary, programs = mod.summarize(manifest, baseline,
            ('\n'.join(json.dumps(r) for r in rows)).encode(), [], None)
        assert summary['held_out'] == {'state': 'skipped', 'mean_bins': None}
        assert summary['search']['incomplete'] == 1
        assert summary['run_state'] == 'report_missing'
        assert programs == {}
