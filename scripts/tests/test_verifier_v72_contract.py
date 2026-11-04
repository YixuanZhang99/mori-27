"""Additive v72 transition guards; never execute acceptance or create evidence."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
V72 = ROOT / 'm0/verifier/v72'


def groups(version):
    tree = ast.parse((ROOT / f'm0/verifier/{version}/verify.py').read_text())
    return {node.args[0].value: node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'run_command' and node.args
            and isinstance(node.args[0], ast.Constant)}


class VerifierV72ContractTests(unittest.TestCase):
    def setUp(self):
        # Execute this historical scope test with its exact original controls.
        # All old test method bodies remain unchanged; v73 checks actual wiring.
        if self._testMethodName == 'test_certificate_uses_current_controls_and_requires_whole_run_success':
            original_read = Path.read_text
            frozen = ROOT / 'm0/verifier/v73/v72-control-context'
            controls = {ROOT / name: frozen / name for name in
                        ('scripts/run_acceptance.py', 'Makefile', '.github/workflows/ci.yml')}
            def historical_read(path, *args, **kwargs):
                return original_read(controls.get(path, path), *args, **kwargs)
            context = patch.object(Path, 'read_text', historical_read)
            context.start()
            self.addCleanup(context.stop)

    def test_every_v71_command_and_timeout_is_retained_exactly(self):
        previous, current = groups('v71'), groups('v72')
        self.assertEqual(len(previous), 33)
        self.assertEqual(len(current), 37)
        self.assertLessEqual(previous.keys(), current.keys())
        for name, call in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(call), ast.dump(current[name]))

    def test_governance_groups_execute_complete_test_files(self):
        expected = {
            'governed_input_isolation_and_protected_physical_accounts': (
                'test_governed_config.py', 'test_governed_budget.py', 'test_governed_sessions.py'),
            'resident_native_worktree_recovery_and_recorded_replay': (
                'test_governed_runtime.py', 'test_governed_native_recovery.py',
                'test_governed_worktree.py', 'test_governed_review.py',
                'test_governed_final_review.py', 'test_composed_worktree_durable_flush.py'),
            'protected_currency_migration_and_semantic_audit': (
                'test_governed_currency.py', 'test_governed_currency_review.py',
                'test_mle_cny_budget.py'),
        }
        current = groups('v72')
        for name, files in expected.items():
            with self.subTest(group=name):
                call = current[name]
                literals = [node.value for node in call.args[1].elts if isinstance(node, ast.Constant)]
                self.assertEqual([value for value in literals if value.startswith('tests/')],
                                 ['tests/' + file for file in files])
                self.assertNotIn('-k', literals)
                self.assertEqual(literals.count('-m'), 1)  # Python's module switch only.
                self.assertEqual(next(item.value.value for item in call.keywords if item.arg == 'timeout'), 480)
        example = current['governed_controls_offline_example']
        command = ast.literal_eval(example.args[1].elts[-1])
        self.assertIn('examples.governed_controls', command)
        self.assertIn('--pause-after', command)
        self.assertIn('--resume', command)
        self.assertIn('--replay', command)
        self.assertEqual(next(item.value.value for item in example.keywords if item.arg == 'timeout'), 120)

    def test_historical_verifiers_archives_and_test_methods_are_unchanged(self):
        baseline = json.loads((V72 / 'transition-baseline.json').read_text())
        for filename, digest in baseline['historical_files_sha256'].items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        source = (ROOT / 'scripts/tests/test_verifier_contract.py').read_text()
        tree = ast.parse(source)
        # ast.dump formatting differs between Python 3.12 and 3.13. Preserve
        # the original AST hashes as provenance; exact method-source hashes
        # enforce a stronger, interpreter-independent unchanged-body check.
        methods = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
                   for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name.startswith('test_')}
        self.assertEqual(baseline['historical_test_method_source_sha256'].keys(),
                         baseline['historical_test_method_ast_sha256'].keys())
        self.assertEqual(baseline['historical_test_method_source_commit'],
                         'bedc5b31fe737dfd207fa8466f68fecb58c5c294')
        for name, digest in baseline['historical_test_method_source_sha256'].items():
            self.assertEqual(methods[name], digest, name)
        # All helpers, decorators and class-level code remain exact too. The
        # only approved insertion supplies v71's frozen controls to its test.
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == 'VerifierTransitionTests')
        setup = [node for node in cls.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'setUp']
        self.assertEqual(len(setup), 1)
        start, end = setup[0].lineno - 1, setup[0].end_lineno + 1
        lines = source.splitlines(keepends=True)
        self.assertEqual(lines[end - 1], '\n')
        self.assertEqual(hashlib.sha256(''.join(lines[start:end]).encode()).hexdigest(),
                         baseline['approved_v71_context_setup_sha256'])
        self.assertEqual(hashlib.sha256(''.join(lines[:start] + lines[end:]).encode()).hexdigest(),
                         baseline['historical_test_method_source_file_sha256'])
        context = baseline['v71_control_context']
        for filename, digest in context['files_sha256'].items():
            data = (V72 / 'v71-control-context' / filename).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
        self.assertEqual(context['source_commit'], '53d2ba14dcc9b1575510a08333bfa08abac5dff7')
        self.assertEqual(hashlib.sha256((ROOT / context['path']).read_bytes()).hexdigest(),
                         '54f5c94007751ed606a08fc3100c3aadcae9d0ab348a3f7671b45c8814bab52a')

    def test_authentic_v71_archive_and_provenance(self):
        # This file intentionally does not exist until a full real v71 run passes.
        provenance = json.loads((V72 / 'v71-provenance.json').read_text())
        self.assertEqual(provenance['version'], 'v71')
        self.assertTrue(provenance['passed'])
        self.assertEqual(provenance['checks'], 42)
        self.assertEqual(provenance['origin'], 'local_linux_acceptance')
        self.assertFalse(provenance['same_sha_remote_ci'])
        self.assertTrue(provenance['source_clean_before'])
        self.assertTrue(provenance['source_clean_after'])
        self.assertEqual(len(provenance['source_commit']), 40)
        self.assertNotEqual(provenance['source_commit'], '53d2ba14dcc9b1575510a08333bfa08abac5dff7')
        self.assertTrue(provenance['run_id'])
        self.assertEqual(provenance['external_provider_requests_during_acceptance'], 0)
        for name, destination in [('LAST_RUN.json', 'm0/verifier/v71/LAST_RUN.json'),
                                  ('new-runs.jsonl', 'm0/verifier/runs/v71.jsonl')]:
            self.assertEqual(hashlib.sha256((ROOT / destination).read_bytes()).hexdigest(),
                             provenance['files'][name])
        certificate = json.loads((ROOT / 'm0/verifier/v71/LAST_RUN.json').read_text())
        journal = [json.loads(line) for line in (ROOT / 'm0/verifier/runs/v71.jsonl').read_text().splitlines()]
        self.assertEqual(certificate['version'], 'v71')
        self.assertTrue(certificate['passed'])
        self.assertEqual(len(certificate['checks']), 42)
        self.assertTrue(all(item['passed'] for item in certificate['checks']))
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0]['command'], 'python3 verifier/v71/verify.py')
        self.assertEqual(journal[0]['exit_code'], 0)
        self.assertEqual(journal[0]['checks'], certificate['checks'])

    def test_historical_requirement_extends_through_v71_and_preserves_rejection(self):
        tree = ast.parse((V72 / 'verify.py').read_text())
        history = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == 'verify_historical_acceptance')
        ranges = [node for node in ast.walk(history) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == 'range']
        self.assertEqual(len(ranges), 1)
        self.assertEqual([ast.literal_eval(arg) for arg in ranges[0].args], [1, 72])
        previous = ast.parse((ROOT / 'm0/verifier/v71/verify.py').read_text())
        old_history = next(node for node in previous.body if isinstance(node, ast.FunctionDef)
                           and node.name == 'verify_historical_acceptance')
        # The range endpoint is the only historical-audit implementation change.
        ranges[0].args[1].value = 71
        self.assertEqual(ast.dump(history), ast.dump(old_history))

    def test_certificate_uses_current_controls_and_requires_whole_run_success(self):
        scenarios = (None, 'governed_input_isolation_and_protected_physical_accounts',
                     'resident_native_worktree_recovery_and_recorded_replay',
                     'governed_controls_offline_example',
                     'protected_currency_migration_and_semantic_audit', 'static_axioms')
        for failed_group in scenarios:
            with self.subTest(failed=failed_group):
                spec = importlib.util.spec_from_file_location('v72_contract_fixture', V72 / 'verify.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                captured = {}
                def command(name, _args, timeout=300):
                    module.check(name, name != failed_group, 'controlled command result')
                def write(path, data, *args, **kwargs):
                    captured[str(path)] = data
                    return len(data)
                original_open = Path.open
                def open_file(path, mode='r', *args, **kwargs):
                    if mode == 'a' and path == module.ROOT / 'verifier/runs/v72.jsonl':
                        return io.StringIO()
                    return original_open(path, mode, *args, **kwargs)
                # Source, index, history and active wrapper reads stay real.
                with patch.object(module, 'run_command', command), \
                     patch.object(Path, 'write_text', write), patch.object(Path, 'open', open_file), \
                     contextlib.redirect_stdout(io.StringIO()):
                    result = module.main()
                report = json.loads(captured[str(module.ROOT / 'verifier/v72/LAST_RUN.json')])
                self.assertEqual(result, 0 if failed_group is None else 1)
                self.assertEqual(len(report['checks']), 46)
                for key in ('resident_governance_evidence', 'protected_currency_authority_evidence'):
                    self.assertEqual(report[key]['certified'], failed_group is None)
                    self.assertFalse(report[key]['external_provider_bridge_implemented'])
                    self.assertFalse(report[key]['supplier_invoice_verified'])
                resident = report['resident_governance_evidence']
                for key in ('iid_statistically_verified', 'external_provider_api_executed',
                            'superiority_established', 'power_loss_durability_certified',
                            'formal_release_certified', 'rubric_abc_complete'):
                    self.assertFalse(resident[key])
                self.assertEqual(report['provider_admission_evidence']['executed_group'],
                                 'provider_input_admission_refusal_and_durable_replay')
                self.assertNotEqual(report['layered_admission_stage_evidence']['executed_group'],
                                    report['provider_admission_evidence']['executed_group'])


if __name__ == '__main__':
    unittest.main()
