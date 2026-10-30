"""Cloud trial limits and artifact disclosure boundaries, without paid calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('run_mle_cloud', ROOT / 'scripts/run_mle_cloud.py')
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class CloudPilotTests(unittest.TestCase):
    def test_explicit_budget_defaults_to_no_model_execution(self):
        plan = cloud.request_from_environment({'PILOT_MODEL': 'model', 'PILOT_TOKEN_BUDGET': '10000'})
        self.assertEqual(plan['mode'], 'preflight')
        self.assertEqual(plan['planned_runs'], 6)
        self.assertEqual(plan['total_declared_tokens'], 60000)
        self.assertFalse(plan['usd_cap_enforced'])

    def test_missing_or_invalid_model_budget_seed_or_wall_limit_is_refused(self):
        for changes in ({'PILOT_MODEL': ''}, {'PILOT_TOKEN_BUDGET': ''},
                        {'PILOT_TOKEN_BUDGET': '100001'}, {'PILOT_SEEDS': '1 1'},
                        {'PILOT_SEEDS': '1 2 3 4'}, {'PILOT_SEEDS': '-1'},
                        {'PILOT_SEEDS': '1 2 3', 'PILOT_TIME_LIMIT': '1800'},
                        {'PILOT_TIME_LIMIT': 'NaN'}, {'PILOT_ITERATIONS': '2'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                cloud.request_from_environment({'PILOT_MODEL': 'model', 'PILOT_TOKEN_BUDGET': '10000', **changes})

    def test_prepare_requires_credentials_and_never_skips_official_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(cloud.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    cloud.prepare_data(root / 'data', root / 'logs', {})
                run.assert_not_called()
                run.return_value.returncode = 0
                cloud.prepare_data(root / 'data', root / 'logs', {'KAGGLE_USERNAME': 'fixture', 'KAGGLE_KEY': 'secret'})
                self.assertEqual(run.call_count, 3)
                for call in run.call_args_list:
                    argv = call.args[0]
                    self.assertNotIn('--skip-verification', argv)
                    self.assertNotIn('--overwrite-checksums', argv)
                    self.assertNotIn('secret', argv)

    def test_export_excludes_dataset_logs_private_evidence_and_untrusted_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pilot.json').write_text(json.dumps({
                'pilot_complete': True, 'private': 'PRIVATE_LABEL_CANARY',
                'spec': {'model': 'fixture', 'dataset_manifest': 'PRIVATE_LABEL_CANARY'},
                'runs': [{'task_id': 'fixture', 'status': 'graded',
                          'error': 'SECRET_LOG_CANARY', 'dataset_manifest': 'PRIVATE_LABEL_CANARY',
                          'official_result': {'score': .5, 'raw_answers': 'PRIVATE_LABEL_CANARY'}}]}))
            (root / 'train.csv').write_text('PRIVATE_LABEL_CANARY')
            target = root / 'public'
            cloud.export_summary(root, target)
            files = list(target.iterdir())
            self.assertEqual([p.name for p in files], ['summary.json'])
            text = files[0].read_text()
            self.assertNotIn('CANARY', text)
            self.assertEqual(json.loads(text)['runs'][0]['official_result']['score'], .5)
            with self.assertRaises(FileExistsError):
                cloud.export_summary(root, target)

    def test_absent_report_does_not_invent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = cloud.export_summary(root, root / 'public')
            self.assertFalse(value['external_model_result_available'])
            self.assertFalse(value['pilot_complete'])

    def test_workflow_only_manual_and_only_uploads_public_summary(self):
        import yaml
        doc = yaml.safe_load((ROOT / '.github/workflows/mle-pilot.yml').read_text())
        events = doc.get('on', doc.get(True))
        self.assertEqual(set(events), {'workflow_dispatch'})
        steps = doc['jobs']['cpu-pilot']['steps']
        uploads = [step for step in steps if str(step.get('uses', '')).startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]['with']['path'], 'artifacts/public-pilot/*.json')
        for step in steps:
            self.assertNotIn('${{ inputs.', step.get('run', ''))


if __name__ == '__main__':
    unittest.main()
