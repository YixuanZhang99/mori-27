"""v73 additive transition guards; simulated commands never produce real evidence."""
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
V73 = ROOT / 'm0/verifier/v73'


def command_groups(version):
    tree = ast.parse((ROOT / f'm0/verifier/{version}/verify.py').read_text())
    return {node.args[0].value: node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'run_command' and node.args and isinstance(node.args[0], ast.Constant)}


class VerifierV73ContractTests(unittest.TestCase):
    def test_v73_preserves_all_v72_commands_and_timeouts(self):
        old, new = command_groups('v72'), command_groups('v73')
        self.assertEqual(len(old), 37)
        self.assertEqual(len(new), 41)
        self.assertLessEqual(old.keys(), new.keys())
        for name, call in old.items():
            self.assertEqual(ast.dump(call), ast.dump(new[name]), name)

    def test_new_groups_run_all_declared_files_without_filters(self):
        expected = {
            'external_governance_contract_runtime_state_integrity': [
                'test_governed_external_contract.py', 'test_governed_external_runtime.py',
                'test_governed_external_state.py', 'test_governed_external_integrity.py'],
            'governed_cny_transport_authority_recovery_refusals': [
                'test_governed_cny_provider.py', 'test_governed_cny_bridge.py',
                'test_governed_cny_audit.py', 'test_governed_cny_recovery.py', 'test_governed_cny_refusals.py'],
            'public_native_worktree_cny_framework_end_to_end': ['test_governed_cny_framework.py'],
        }
        current = command_groups('v73')
        for name, files in expected.items():
            call = current[name]
            literals = [node.value for node in call.args[1].elts if isinstance(node, ast.Constant)]
            self.assertEqual([x for x in literals if x.startswith('tests/')], ['tests/' + file for file in files])
            self.assertNotIn('-k', literals)
            self.assertEqual(literals.count('-m'), 1)
            self.assertEqual(next(item.value.value for item in call.keywords if item.arg == 'timeout'), 480)

        example = current['governed_cny_offline_example']
        command = ast.literal_eval(example.args[1].elts[-1])
        self.assertIn('examples/governed_cny_offline.py', command)
        self.assertIn('TemporaryDirectory', command)
        self.assertIn('--workdir', command)
        self.assertIn('check=True', command)
        self.assertEqual(next(item.value.value for item in example.keywords if item.arg == 'timeout'), 120)

    def test_historical_files_and_exact_test_sources_remain_unchanged(self):
        baseline = json.loads((V73 / 'transition-baseline.json').read_text())
        self.assertEqual(baseline['source_commit'], 'ff5c4417879f29cc39c7c5886a793f500bdbcbad')
        for filename, digest in baseline['historical_files_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest, filename)
        for filename, methods in baseline['historical_test_method_source_sha256'].items():
            source = (ROOT / filename).read_text()
            tree = ast.parse(source)
            actual = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
                      for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}
            self.assertEqual(actual, methods, filename)
            if filename.endswith('test_verifier_v72_contract.py'):
                cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                           and node.name == 'VerifierV72ContractTests')
                setups = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'setUp']
                self.assertEqual(len(setups), 1)
                start, end = setups[0].lineno - 1, setups[0].end_lineno + 1
                lines = source.splitlines(keepends=True)
                self.assertEqual(lines[end - 1], '\n')
                self.assertEqual(hashlib.sha256(''.join(lines[start:end]).encode()).hexdigest(),
                                 baseline['approved_v72_setup_source_sha256'])
                source = ''.join(lines[:start] + lines[end:])
            # The complete old v71 test file, including its existing setup, stays exact.
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),
                             baseline['historical_test_files_sha256'][filename])
        for filename, digest in baseline['v72_control_context_sha256'].items():
            self.assertEqual(hashlib.sha256((V73 / 'v72-control-context' / filename).read_bytes()).hexdigest(), digest)

    def test_authentic_v72_archive_is_exact_local_evidence(self):
        provenance = json.loads((V73 / 'v72-provenance.json').read_text())
        self.assertEqual(provenance['source_commit'], 'ff5c4417879f29cc39c7c5886a793f500bdbcbad')
        self.assertTrue(provenance['source_clean_before'])
        self.assertTrue(provenance['source_clean_after'])
        self.assertEqual(provenance['origin'], 'local_linux_acceptance')
        self.assertFalse(provenance['same_sha_remote_ci'])
        self.assertEqual(provenance['external_provider_requests_during_acceptance'], 0)
        self.assertEqual(provenance['elapsed_seconds'], 739.397)
        certificate = json.loads((ROOT / 'm0/verifier/v72/LAST_RUN.json').read_text())
        journal = [json.loads(line) for line in (ROOT / 'm0/verifier/runs/v72.jsonl').read_text().splitlines()]
        self.assertEqual(certificate['version'], 'v72')
        self.assertTrue(certificate['passed'])
        self.assertEqual(len(certificate['checks']), 46)
        self.assertTrue(all(check['passed'] for check in certificate['checks']))
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0]['command'], 'python3 verifier/v72/verify.py')
        self.assertEqual(journal[0]['exit_code'], 0)
        self.assertEqual(journal[0]['checks'], certificate['checks'])
        for name, path in [('LAST_RUN.json', 'm0/verifier/v72/LAST_RUN.json'),
                           ('new-runs.jsonl', 'm0/verifier/runs/v72.jsonl')]:
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), provenance['files'][name])

    def test_history_audit_extends_through_v72_with_no_other_change(self):
        def history(version):
            return next(node for node in ast.parse((ROOT / f'm0/verifier/{version}/verify.py').read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'verify_historical_acceptance')
        old, new = history('v72'), history('v73')
        ranges = [node for node in ast.walk(new) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == 'range']
        self.assertEqual(len(ranges), 1)
        self.assertEqual([ast.literal_eval(x) for x in ranges[0].args], [1, 73])
        ranges[0].args[1].value = 72
        self.assertEqual(ast.dump(old), ast.dump(new))

    def test_current_v73_scope_requires_all_groups_and_whole_run_success(self):
        scenarios = (None, 'external_governance_contract_runtime_state_integrity',
                     'governed_cny_transport_authority_recovery_refusals',
                     'public_native_worktree_cny_framework_end_to_end', 'governed_cny_offline_example', 'static_axioms')
        for failure in scenarios:
            with self.subTest(failure=failure):
                spec = importlib.util.spec_from_file_location('v73_scope_fixture', V73 / 'verify.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                captured = {}
                def command(name, _args, timeout=300):
                    module.check(name, name != failure, 'controlled command result')
                def write(path, data, *args, **kwargs):
                    captured[str(path)] = data
                    return len(data)
                original_open = Path.open
                def open_file(path, mode='r', *args, **kwargs):
                    if mode == 'a' and path == module.ROOT / 'verifier/runs/v73.jsonl':
                        return io.StringIO()
                    return original_open(path, mode, *args, **kwargs)
                # Current actual wrapper, Makefile, workflow, source and history are read.
                with patch.object(module, 'run_command', command), patch.object(Path, 'write_text', write), \
                     patch.object(Path, 'open', open_file), contextlib.redirect_stdout(io.StringIO()):
                    status = module.main()
                report = json.loads(captured[str(module.ROOT / 'verifier/v73/LAST_RUN.json')])
                self.assertEqual(status, 0 if failure is None else 1)
                self.assertEqual(len(report['checks']), 50)
                external = report['external_governance_bridge_evidence']
                self.assertEqual(external['certified'], failure is None)
                for section in ('external_governance_bridge_evidence', 'resident_governance_evidence',
                                'protected_currency_authority_evidence'):
                    self.assertEqual(report[section]['external_provider_bridge_implemented'], failure is None)
                for key in ('external_provider_api_executed', 'iid_statistically_verified',
                            'immutable_hosted_model_snapshot_verified', 'supplier_invoice_verified',
                            'live_campaign_ledger_read_or_migrated', 'power_loss_durability_certified',
                            'cross_authority_atomic_commit_claimed', 'superiority_established',
                            'formal_paid_run_certified', 'formal_release_certified', 'rubric_abc_complete'):
                    self.assertFalse(external[key], key)


if __name__ == '__main__':
    unittest.main()
