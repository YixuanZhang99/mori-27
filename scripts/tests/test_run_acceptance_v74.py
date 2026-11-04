"""V74 must certify the exact committed and executed source, not only a green child."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class V74RunnerTests(unittest.TestCase):
    def run_fixture(self, mutation=None, *, dirty=False):
        with tempfile.TemporaryDirectory(prefix='mori-v74-runner-') as d:
            root = Path(d)
            for name in ('scripts/run_acceptance.py', 'scripts/run_acceptance_v74.py'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            (root / 'm0/verifier/v74').mkdir(parents=True)
            (root / 'm0/verifier/runs').mkdir()
            (root / 'm0/core').mkdir()
            (root / 'm0/core/fixture.py').write_text('VALUE = 1\n')
            before = {'version': 'v73', 'passed': True, 'checks': [{'passed': True}]}
            (root / 'm0/verifier/runs/v73.jsonl').write_text(json.dumps(before) + '\n')
            body = """import json
from pathlib import Path
checks = [{'check': 'fixture', 'passed': True}]
Path('verifier/v74/LAST_RUN.json').write_text(json.dumps({'version':'v74','passed':True,'checks':checks}))
with Path('verifier/runs/v74.jsonl').open('a') as f:
    f.write(json.dumps({'command':'python3 verifier/v74/verify.py','exit_code':0,'checks':checks})+'\\n')
"""
            if mutation == 'execution':
                body += "Path('core/fixture.py').write_text('VALUE = 2\\n')\n"
            if mutation == 'source':
                body += f"Path({str(root / 'm0/core/fixture.py')!r}).write_text('VALUE = 2\\n')\n"
            (root / 'm0/verifier/v74/verify.py').write_text(body)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                            'commit', '-qm', 'fixture'], check=True)
            sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            if dirty:
                (root / 'm0/core/fixture.py').write_text('VALUE = 3\n')
            child = subprocess.run([sys.executable, str(root / 'scripts/run_acceptance_v74.py'),
                '--output', str(root / 'artifacts'), '--timeout', '10'], text=True, capture_output=True, timeout=20)
            reports = list((root / 'artifacts').glob('*/summary.json'))
            self.assertEqual(len(reports), 1, child.stdout + child.stderr)
            summary = json.loads(reports[0].read_text())
            self.assertEqual(summary['source_binding']['commit'], sha)
            self.assertEqual(summary['verifier_version'], 'v74')
            self.assertTrue(summary['certificate_passed'])
            self.assertTrue(summary['new_journal_passed'])
            self.assertEqual(json.loads((root / 'm0/verifier/runs/v73.jsonl').read_text()), before)
            return child.returncode, summary

    def test_clean_committed_and_executed_source_is_bound_to_result(self):
        code, report = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'])
        self.assertTrue(report['source_binding']['matches_commit'])
        self.assertTrue(report['source_binding']['unchanged'])
        self.assertTrue(report['execution_source_unchanged'])
        self.assertEqual(report['source_binding']['source_manifest_sha256'], report['execution_source_manifest_sha256'])

    def test_dirty_source_cannot_claim_same_commit_acceptance(self):
        code, report = self.run_fixture(dirty=True)
        self.assertEqual(code, 1)
        self.assertFalse(report['passed'])
        self.assertFalse(report['source_binding']['matches_commit'])

    def test_mutated_original_source_cannot_publish_success(self):
        code, report = self.run_fixture('source')
        self.assertEqual(code, 1)
        self.assertFalse(report['source_binding']['unchanged'])
        self.assertFalse(report['passed'])

    def test_mutated_execution_copy_cannot_publish_success(self):
        code, report = self.run_fixture('execution')
        self.assertEqual(code, 1)
        self.assertFalse(report['execution_source_unchanged'])
        self.assertFalse(report['passed'])
