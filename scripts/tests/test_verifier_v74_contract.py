"""M7 acceptance transition: historical commands and actual certificate gating."""
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
V74 = ROOT / 'm0/verifier/v74'
GROUPS = {
    'm7_construction_materialization_and_invocation': ['test_construction.py', 'test_materialization_recovery.py', 'test_invocation_lifecycle.py'],
    'm7_public_native_and_control_construction': ['test_configured_construction.py', 'test_construction_controls.py'],
    'm7_git_publication_command_and_process_recovery': ['test_construction_worktree.py', 'test_construction_worktree_framework.py'],
    'm7_external_currency_construction_and_recovery': ['test_construction_currency.py'],
    'm7_installed_artifact_examples': [],
}


def groups(version):
    tree = ast.parse((ROOT / f'm0/verifier/{version}/verify.py').read_text())
    return {n.args[0].value: n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == 'run_command'
            and n.args and isinstance(n.args[0], ast.Constant)}


class VerifierV74ContractTests(unittest.TestCase):
    def test_all_v73_commands_and_timeouts_are_preserved(self):
        old, new = groups('v73'), groups('v74')
        self.assertEqual(len(old), 41)
        self.assertEqual(set(new) - set(old), set(GROUPS))
        for name, call in old.items():
            self.assertEqual(ast.dump(call), ast.dump(new[name]), name)

    def test_historical_sources_and_authenticated_v73_archive_are_unchanged(self):
        baseline = json.loads((V74 / 'transition-baseline.json').read_text())
        for name, digest in baseline['historical_files_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)
        provenance = json.loads((V74 / 'v73-provenance.json').read_text())
        self.assertEqual(provenance['source_commit'], '4351a0298e5d97ffada7ea0770ae0cac7a2d1bac')
        self.assertEqual(provenance['run_id'], 41840205319)
        self.assertEqual(provenance['origin'], 'GitHub Actions push')
        certificate = json.loads((ROOT / 'm0/verifier/v73/LAST_RUN.json').read_text())
        journal = [json.loads(x) for x in (ROOT / 'm0/verifier/runs/v73.jsonl').read_text().splitlines()]
        self.assertTrue(certificate['passed'])
        self.assertEqual(certificate['version'], 'v73')
        self.assertEqual(len(certificate['checks']), 50)
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0]['checks'], certificate['checks'])
        for name, rel in [('LAST_RUN.json', 'm0/verifier/v73/LAST_RUN.json'),
                          ('new-runs.jsonl', 'm0/verifier/runs/v73.jsonl')]:
            self.assertEqual(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), provenance['files'][name])

    def test_m7_certificate_requires_every_new_group_and_whole_run(self):
        for failure in [None, *GROUPS, 'static_axioms']:
            with self.subTest(failure=failure):
                spec = importlib.util.spec_from_file_location('v74_scope_fixture', V74 / 'verify.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                captured, executed = {}, {}
                def command(name, args, timeout=300):
                    executed[name] = (args, timeout)
                    module.check(name, name != failure, 'controlled result; not actual execution evidence')
                def write(path, data, *args, **kwargs):
                    captured[str(path)] = data
                    return len(data)
                original_open = Path.open
                def open_file(path, mode='r', *args, **kwargs):
                    if mode == 'a' and path == module.ROOT / 'verifier/runs/v74.jsonl':
                        return io.StringIO()
                    return original_open(path, mode, *args, **kwargs)
                with patch.object(module, 'run_command', command), patch.object(Path, 'write_text', write), \
                        patch.object(Path, 'open', open_file), contextlib.redirect_stdout(io.StringIO()):
                    status = module.main()
                report = json.loads(captured[str(module.ROOT / 'verifier/v74/LAST_RUN.json')])
                self.assertEqual(status, 0 if failure is None else 1)
                self.assertEqual(len(report['checks']), 55)
                self.assertEqual(report['m7_configured_execution_evidence']['certified'], failure is None)
                self.assertEqual(set(report['m7_configured_execution_evidence']['executed_groups']), set(GROUPS))
                for key in ('configured_concurrency_certified', 'external_model_requests', 'rubric_abc_complete',
                            'formal_release_certified', 'power_loss_durability_certified', 'superiority_established'):
                    self.assertFalse(report['m7_configured_execution_evidence'][key], key)
                for name, files in GROUPS.items():
                    command, timeout = executed[name]
                    if files:
                        self.assertEqual([p for p in command if p.startswith('tests/')], ['tests/' + p for p in files])
                        self.assertNotIn('-k', command)
                        self.assertEqual(command.count('-m'), 1)
                        self.assertEqual(timeout, 480)
                    else:
                        self.assertEqual(command[1:], ['ci/check_installed_construction.py'])
                        self.assertEqual(timeout, 180)

    def test_history_audit_extends_through_v73(self):
        def history(version):
            return next(n for n in ast.parse((ROOT / f'm0/verifier/{version}/verify.py').read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'verify_historical_acceptance')
        old, new = history('v73'), history('v74')
        ranges = [n for n in ast.walk(new) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'range']
        self.assertEqual(len(ranges), 1)
        self.assertEqual([ast.literal_eval(v) for v in ranges[0].args], [1, 74])
        ranges[0].args[1].value = 73
        self.assertEqual(ast.dump(old), ast.dump(new))
