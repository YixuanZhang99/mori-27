"""V76 must certify the exact committed and executed source, not only a green child."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class V76RunnerTests(unittest.TestCase):
    def run_fixture(self, mutation=None, *, dirty=False):
        with tempfile.TemporaryDirectory(prefix='mori-v76-runner-') as d:
            root = Path(d)
            for name in ('scripts/run_acceptance_v75.py', 'scripts/verify_acceptance_v75.py',
                         'scripts/tests/test_verifier_v75_contract.py', 'scripts/tests/test_run_acceptance_v75.py',
                         'scripts/tests/test_verify_acceptance_v75.py', 'scripts/run_acceptance.py', 'scripts/run_acceptance_v74.py', 'scripts/run_acceptance_v76.py',
                         'scripts/setup_ci_tmpdir.sh', 'scripts/setup_linux_ci.sh', 'scripts/verify_acceptance_v76.py',
                         'scripts/tests/test_verifier_v74_contract.py', 'scripts/tests/test_run_acceptance_v74.py',
                         'scripts/tests/test_verifier_v76_contract.py', 'scripts/tests/test_run_acceptance_v76.py',
                         'scripts/tests/test_verify_acceptance_v76.py'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            (root / 'm0/verifier/v76').mkdir(parents=True)
            shutil.copyfile(ROOT / 'm0/verifier/v76/expected-checks.json', root / 'm0/verifier/v76/expected-checks.json')
            (root / 'm0/verifier/runs').mkdir()
            (root / 'm0/core').mkdir()
            (root / 'm0/core/fixture.py').write_text('VALUE = 1\n')
            before = {'version': 'v73', 'passed': True, 'checks': [{'passed': True}]}
            (root / 'm0/verifier/runs/v73.jsonl').write_text(json.dumps(before) + '\n')
            body = """import json
from pathlib import Path
checks = [{'check': name, 'passed': True} for name in json.loads(Path('verifier/v76/expected-checks.json').read_text())]
if __MISSING__: checks.pop()
Path('verifier/v76/LAST_RUN.json').write_text(json.dumps({'version':'v76','passed':True,'checks':checks}))
with Path('verifier/runs/v76.jsonl').open('a') as f:
    f.write(json.dumps({'command':'python3 verifier/v76/verify.py','exit_code':0,'checks':checks})+'\\n')
"""
            body = body.replace('__MISSING__', str(mutation == 'missing_check'))
            if mutation == 'execution':
                body += "Path('core/fixture.py').write_text('VALUE = 2\\n')\n"
            if mutation == 'source':
                body += f"Path({str(root / 'm0/core/fixture.py')!r}).write_text('VALUE = 2\\n')\n"
            if mutation == 'ci_control':
                body += f"Path({str(root / 'scripts/setup_ci_tmpdir.sh')!r}).write_text('changed\\n')\n"
            if mutation == 'new_control':
                body += f"Path({str(root / 'scripts/verify_acceptance_v76.py')!r}).write_text('changed\\n')\n"
            (root / 'm0/verifier/v76/verify.py').write_text(body)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                            'commit', '-qm', 'fixture'], check=True)
            sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            if dirty:
                (root / 'm0/core/fixture.py').write_text('VALUE = 3\n')
            child = subprocess.run([sys.executable, str(root / 'scripts/run_acceptance_v76.py'),
                '--output', str(root / 'artifacts'), '--timeout', '10'], text=True, capture_output=True, timeout=20)
            reports = list((root / 'artifacts').glob('*/summary.json'))
            self.assertEqual(len(reports), 1, child.stdout + child.stderr)
            summary = json.loads(reports[0].read_text())
            self.assertEqual(summary['source_binding']['commit'], sha)
            self.assertEqual(summary['verifier_version'], 'v76')
            self.assertEqual(summary['certificate_passed'], mutation != 'missing_check')
            self.assertEqual(summary['new_journal_passed'], mutation != 'missing_check')
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

    def test_missing_required_check_cannot_publish_success(self):
        code, report = self.run_fixture('missing_check')
        self.assertEqual(code, 1)
        self.assertFalse(report['passed'])

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

    def test_mutated_ci_temporary_directory_setup_cannot_publish_success(self):
        code, report = self.run_fixture('ci_control')
        self.assertEqual(code, 1)
        self.assertFalse(report['source_binding']['unchanged'])
        self.assertFalse(report['passed'])

    def test_mutated_independent_verifier_cannot_publish_success(self):
        code, report = self.run_fixture('new_control')
        self.assertEqual(code, 1)
        self.assertFalse(report['source_binding']['unchanged'])
