"""V75 extends the full-regression deadline without dropping checks."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

def groups(version):
    tree = ast.parse((ROOT / f'm0/verifier/{version}/verify.py').read_text())
    return {node.args[0].value: node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'run_command' and node.args and isinstance(node.args[0], ast.Constant)}

class V75ContractTests(unittest.TestCase):
    def test_retains_all_commands_and_extends_only_full_regression_timeout(self):
        self.assertTrue((ROOT / 'm0/verifier/v75/verify.py').is_file(), 'v75 verifier must exist')
        old, new = groups('v74'), groups('v75')
        self.assertEqual(set(old), set(new))
        for name in old:
            previous, current = old[name], new[name]
            if name == 'complete_local_regression':
                self.assertEqual(previous.keywords[0].value.value, 600)
                self.assertEqual(current.keywords[0].value.value, 900)
                current.keywords[0].value.value = 600
            self.assertEqual(ast.dump(previous), ast.dump(current), name)

    def test_v75_legacy_entrypoint_retains_its_outer_deadline(self):
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn('accept-linux-v75:', makefile)
        self.assertIn('scripts/run_acceptance_v75.py --timeout 2100', makefile)

    def test_v74_source_manifest_detects_historical_mutation(self):
        spec = importlib.util.spec_from_file_location('v75_fixture', ROOT / 'm0/verifier/v75/verify.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, 'verify_v74_sources', None)
        self.assertTrue(callable(function), 'v75 must independently verify frozen v74 sources')
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            path = repo / 'm0/verifier/v74/verify.py'
            path.parent.mkdir(parents=True)
            path.write_text('original')
            frozen = repo / 'm0/verifier/v75/v74-frozen.json'
            frozen.parent.mkdir(parents=True)
            frozen.write_text(json.dumps({'m0/verifier/v74/verify.py': hashlib.sha256(path.read_bytes()).hexdigest()}))
            module.ROOT = repo / 'm0'
            with contextlib.redirect_stdout(io.StringIO()):
                function()
                self.assertTrue(module.CHECKS[-1]['passed'])
                path.write_text('changed')
                function()
                self.assertFalse(module.CHECKS[-1]['passed'])

    def test_certificate_requires_unchanged_v74_sources_and_all_checks(self):
        for source_ok in (True, False):
            with self.subTest(source_ok=source_ok):
                spec = importlib.util.spec_from_file_location('v75_certificate_fixture', ROOT / 'm0/verifier/v75/verify.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                captured = {}
                def command(name, args, timeout=300):
                    module.check(name, True, 'controlled fixture')
                def source():
                    module.check('v74_historical_source_preserved', source_ok, 'controlled fixture')
                def write(path, data, *args, **kwargs):
                    captured[str(path)] = data
                    return len(data)
                original_open = Path.open
                def open_file(path, mode='r', *args, **kwargs):
                    if mode == 'a' and path == module.ROOT / 'verifier/runs/v75.jsonl':
                        return io.StringIO()
                    return original_open(path, mode, *args, **kwargs)
                with patch.object(module, 'run_command', command), patch.object(module, 'verify_v74_sources', source), \
                        patch.object(Path, 'write_text', write), patch.object(Path, 'open', open_file), \
                        contextlib.redirect_stdout(io.StringIO()):
                    status = module.main()
                report = json.loads(captured[str(module.ROOT / 'verifier/v75/LAST_RUN.json')])
                self.assertEqual(status, 0 if source_ok else 1)
                self.assertEqual(len(report['checks']), 56)
                self.assertEqual(report['passed'], source_ok)

    def test_verifier_rejects_missing_required_check(self):
        spec = importlib.util.spec_from_file_location('v75_missing_fixture', ROOT / 'm0/verifier/v75/verify.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        captured = {}
        def command(name, args, timeout=300):
            if name != 'complete_local_regression':
                module.check(name, True, 'controlled fixture')
        def write(path, data, *args, **kwargs):
            captured[str(path)] = data
            return len(data)
        original_open = Path.open
        def open_file(path, mode='r', *args, **kwargs):
            if mode == 'a' and path == module.ROOT / 'verifier/runs/v75.jsonl': return io.StringIO()
            return original_open(path, mode, *args, **kwargs)
        with patch.object(module, 'run_command', command), patch.object(Path, 'write_text', write), \
                patch.object(Path, 'open', open_file), contextlib.redirect_stdout(io.StringIO()):
            status = module.main()
        report = json.loads(captured[str(module.ROOT / 'verifier/v75/LAST_RUN.json')])
        self.assertNotEqual(status, 0)
        self.assertFalse(report['passed'])

if __name__ == '__main__': unittest.main()
