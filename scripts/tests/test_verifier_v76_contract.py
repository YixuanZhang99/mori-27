"""V76 extends hosted Linux time without dropping acceptance coverage."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def commands(version):
    source = (ROOT / f'm0/verifier/{version}/verify.py').read_text()
    return {node.args[0].value: node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'run_command' and node.args and isinstance(node.args[0], ast.Constant)}


class V76ContractTests(unittest.TestCase):
    def test_all_v75_commands_are_retained_and_only_full_timeout_changes(self):
        old, new = commands('v75'), commands('v76')
        self.assertEqual(set(old), set(new))
        for name, previous in old.items():
            current = new[name]
            if name == 'complete_local_regression':
                self.assertEqual(previous.keywords[0].value.value, 900)
                self.assertEqual(current.keywords[0].value.value, 1500)
                current.keywords[0].value.value = 900
            self.assertEqual(ast.dump(previous), ast.dump(current), name)

    def test_v75_source_is_pinned_and_expected_checks_are_additive(self):
        manifest = json.loads((ROOT / 'm0/verifier/v76/v75-frozen.json').read_text())
        self.assertIn('m0/verifier/v75/verify.py', manifest)
        self.assertIn('scripts/run_acceptance_v75.py', manifest)
        for name, expected in manifest.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name)
        old = json.loads((ROOT / 'm0/verifier/v75/expected-checks.json').read_text())
        new = json.loads((ROOT / 'm0/verifier/v76/expected-checks.json').read_text())
        self.assertEqual(set(new), set(old) | {'v75_historical_source_preserved'})
        self.assertEqual(len(new), 57)

    def test_active_ci_has_outer_headroom_and_retains_v75_entrypoint(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn('full v76', workflow)
        self.assertIn('timeout-minutes: 60', workflow)
        self.assertIn('scripts/run_acceptance_v76.py --timeout 3000', makefile)
        self.assertIn('scripts/run_acceptance_v75.py --timeout 2100', makefile)

    def test_v75_verification_rejects_modified_or_omitted_sources(self):
        spec = importlib.util.spec_from_file_location('v76_source_fixture', ROOT / 'm0/verifier/v76/verify.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = json.loads((ROOT / 'm0/verifier/v76/v75-frozen.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name in manifest:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            path = repo / 'm0/verifier/v76/v75-frozen.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(manifest))
            module.ROOT = repo / 'm0'
            with contextlib.redirect_stdout(io.StringIO()):
                module.verify_v75_sources()
                self.assertTrue(module.CHECKS[-1]['passed'])
                (repo / 'm0/verifier/v75/verify.py').write_text('changed')
                module.verify_v75_sources()
                self.assertFalse(module.CHECKS[-1]['passed'])
                del manifest['m0/verifier/v75/verify.py']
                path.write_text(json.dumps(manifest))
                module.verify_v75_sources()
                self.assertFalse(module.CHECKS[-1]['passed'])

    def test_certificate_requires_both_historical_checks_and_all_57_results(self):
        for previous_ok in (True, False):
            spec = importlib.util.spec_from_file_location('v76_certificate_fixture', ROOT / 'm0/verifier/v76/verify.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            captured = {}
            def command(name, args, timeout=300):
                module.check(name, True, 'controlled fixture')
            def old74():
                module.check('v74_historical_source_preserved', True, 'controlled fixture')
            def old75():
                module.check('v75_historical_source_preserved', previous_ok, 'controlled fixture')
            def write(path, data, *args, **kwargs):
                captured[str(path)] = data
                return len(data)
            original_open = Path.open
            def open_file(path, mode='r', *args, **kwargs):
                if mode == 'a' and path == module.ROOT / 'verifier/runs/v76.jsonl':
                    return io.StringIO()
                return original_open(path, mode, *args, **kwargs)
            with patch.object(module, 'run_command', command), patch.object(module, 'verify_v74_sources', old74), \
                    patch.object(module, 'verify_v75_sources', old75), patch.object(Path, 'write_text', write), \
                    patch.object(Path, 'open', open_file), contextlib.redirect_stdout(io.StringIO()):
                status = module.main()
            report = json.loads(captured[str(module.ROOT / 'verifier/v76/LAST_RUN.json')])
            self.assertEqual(status, 0 if previous_ok else 1)
            self.assertEqual(len(report['checks']), 57)
            self.assertEqual(report['passed'], previous_ok)

    def test_independent_verifier_covers_every_runner_control_file(self):
        output = subprocess.check_output([sys.executable, '-c',
            "import json,sys;sys.path.insert(0,'scripts');import run_acceptance_v76 as v;"
            "print(json.dumps(list(v.runner.CONTROL_FILES)))"], cwd=ROOT, text=True)
        controls = set(json.loads(output))
        tree = ast.parse((ROOT / 'scripts/verify_acceptance_v76.py').read_text())
        verifier_controls = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'controls'
                                                    for target in node.targets):
                verifier_controls.update(ast.literal_eval(node.value))
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == 'controls':
                verifier_controls.update(ast.literal_eval(node.value))
        self.assertEqual(controls, verifier_controls)

    def test_certificate_rejects_a_missing_required_check(self):
        spec = importlib.util.spec_from_file_location('v76_missing_fixture', ROOT / 'm0/verifier/v76/verify.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        captured = {}
        def command(name, args, timeout=300):
            if name != 'complete_local_regression':
                module.check(name, True, 'controlled fixture')
        def write(path, data, *args, **kwargs):
            captured[str(path)] = data
            return len(data)
        original_open = Path.open
        def open_file(path, mode='r', *args, **kwargs):
            if mode == 'a' and path == module.ROOT / 'verifier/runs/v76.jsonl':
                return io.StringIO()
            return original_open(path, mode, *args, **kwargs)
        with patch.object(module, 'run_command', command), patch.object(Path, 'write_text', write), \
                patch.object(Path, 'open', open_file), contextlib.redirect_stdout(io.StringIO()):
            status = module.main()
        report = json.loads(captured[str(module.ROOT / 'verifier/v76/LAST_RUN.json')])
        self.assertNotEqual(status, 0)
        self.assertFalse(report['passed'])


if __name__ == '__main__':
    unittest.main()
