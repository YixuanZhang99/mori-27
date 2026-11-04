"""Guard the acceptance version transition without executing Linux workloads."""
from __future__ import annotations

import ast
import hashlib
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def verifier_tree(version: str) -> ast.Module:
    return ast.parse((ROOT / f"m0/verifier/{version}/verify.py").read_text())


def command_groups(tree: ast.Module) -> dict[str, ast.Call]:
    return {
        call.args[0].value: call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name) and call.func.id == "run_command"
        and call.args and isinstance(call.args[0], ast.Constant)
    }


class VerifierTransitionTests(unittest.TestCase):
    def test_v71_scope_requires_group_and_whole_run_success(self):
        path = ROOT / 'm0/verifier/v71/verify.py'
        self.assertTrue(path.is_file())
        for failed_group in (None, 'provider_input_admission_refusal_and_durable_replay', 'static_axioms'):
            with self.subTest(failed=failed_group):
                spec = importlib.util.spec_from_file_location('v71_fixture', path)
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
                    if mode == 'a' and path == module.ROOT / 'verifier/runs/v71.jsonl':
                        return io.StringIO()
                    return original_open(path, mode, *args, **kwargs)
                with patch.object(module, 'run_command', command), \
                     patch.object(Path, 'write_text', write), patch.object(Path, 'open', open_file), \
                     contextlib.redirect_stdout(io.StringIO()):
                    result = module.main()
                report = json.loads(captured[str(module.ROOT / 'verifier/v71/LAST_RUN.json')])
                self.assertEqual(result, 0 if failed_group is None else 1)
                scope = report['provider_admission_evidence']
                self.assertEqual(scope['certified'], failed_group is None)
                self.assertFalse(scope['estimated_input_is_hard_bound'])
                self.assertFalse(scope['external_provider_api_executed'])
                self.assertFalse(scope['supplier_invoice_verified'])
                self.assertFalse(scope['arbitrary_native_crash_recovery_certified'])

    def test_v71_preserves_every_v70_command_and_timeout(self):
        self.assertTrue((ROOT / 'm0/verifier/v71/verify.py').is_file())
        previous, current = command_groups(verifier_tree('v70')), command_groups(verifier_tree('v71'))
        self.assertEqual(len(previous), 32)
        self.assertEqual(len(current), 33)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v71_executes_provider_admission_and_stop_boundaries_unfiltered(self):
        self.assertTrue((ROOT / 'm0/verifier/v71/verify.py').is_file())
        group = command_groups(verifier_tree('v71'))['provider_input_admission_refusal_and_durable_replay']
        arguments = [node.value for node in group.args[1].elts if isinstance(node, ast.Constant)]
        for name in ('tests/test_mle_provider.py', 'tests/test_mle_currency_integration.py',
                     'tests/test_composed_budget.py', 'tests/test_composed_recovery.py'):
            self.assertIn(name, arguments)
        self.assertNotIn('-k', arguments)
        self.assertNotIn('-m', arguments[1:])
        self.assertEqual(next(k.value.value for k in group.keywords if k.arg == 'timeout'), 480)

    def test_archived_v70_is_exact_verified_local_linux_evidence(self):
        expected = {
            'm0/verifier/v70/LAST_RUN.json': '750a0ab259f0ba3648fe67a17b87d8e0ca4231c6cad80498445b95ae24d8a2d4',
            'm0/verifier/runs/v70.jsonl': 'fd411c00b85d866bc9e3254cd564f8ddd7275736676c36364b49820edaf9737a',
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertTrue((ROOT / filename).is_file())
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / 'm0/verifier/v70/LAST_RUN.json').read_text())
        entries = [json.loads(line) for line in (ROOT / 'm0/verifier/runs/v70.jsonl').read_text().splitlines()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['command'], 'python3 verifier/v70/verify.py')
        self.assertEqual(entries[0]['exit_code'], 0)
        self.assertEqual(entries[0]['checks'], certificate['checks'])
        self.assertTrue(certificate['passed'])
        self.assertEqual(len(certificate['checks']), 41)
        self.assertTrue(all(row['passed'] for row in certificate['checks']))
        provenance = json.loads((ROOT / 'm0/verifier/v71/v70-provenance.json').read_text())
        self.assertEqual(provenance['source_commit'], 'aedede3c2b78a5c2b57074c70d510af710f5af4e')
        self.assertEqual(provenance['origin'], 'local_linux_acceptance')
        self.assertFalse(provenance['same_sha_remote_ci'])

    def test_v70_executes_cooperating_process_journal_snapshot_boundaries(self):
        self.assertTrue((ROOT / 'm0/verifier/v70/verify.py').is_file(), 'v70 journal group is missing')
        group = command_groups(verifier_tree('v70'))['cooperating_process_journal_snapshot_consistency']
        arguments = [node.value for node in group.args[1].elts if isinstance(node, ast.Constant)]
        self.assertIn('tests/test_x1_store_concurrency.py', arguments)
        self.assertIn('tests/test_external_batch_partial_start_recovery.py', arguments)
        self.assertNotIn('-k', arguments)
        self.assertNotIn('-m', arguments[1:])
        self.assertEqual(next(k.value.value for k in group.keywords if k.arg == 'timeout'), 120)

    def test_archived_v69_is_exact_verified_local_linux_evidence(self):
        expected = {
            "m0/verifier/v69/LAST_RUN.json": "1b4ab41c4cdb631bb85b3884d7b99bea4f7085ae9a3a3048239f9665dc7d0e1e",
            "m0/verifier/runs/v69.jsonl": "19f70b2b97fe3e83ac9798aeef636ca97d82eb4edf8fb989a7a140e0dcfc10d6",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertTrue((ROOT / filename).is_file(), "authentic v69 evidence must be archived")
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / 'm0/verifier/v69/LAST_RUN.json').read_text())
        entries = [json.loads(line) for line in (ROOT / 'm0/verifier/runs/v69.jsonl').read_text().splitlines()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['checks'], certificate['checks'])
        self.assertEqual(entries[0]['command'], 'python3 verifier/v69/verify.py')
        self.assertEqual(entries[0]['exit_code'], 0)
        self.assertTrue(certificate['passed'])
        self.assertEqual(len(certificate['checks']), 39)
        self.assertTrue(all(item['passed'] for item in certificate['checks']))
        provenance = json.loads((ROOT / 'm0/verifier/v70/v69-provenance.json').read_text())
        self.assertEqual(provenance['source_commit'], '5fa85d3ab7c4f643550ecaa2223a65231d7f7a86')
        self.assertEqual(provenance['origin'], 'local_linux_acceptance')
        self.assertFalse(provenance['same_sha_remote_ci'])

    def test_v70_keeps_every_v69_command_group_and_timeout(self):
        self.assertTrue((ROOT / 'm0/verifier/v70/verify.py').is_file(), 'v70 must preserve prior coverage')
        previous, current = command_groups(verifier_tree('v69')), command_groups(verifier_tree('v70'))
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v70_executes_remaining_reservation_and_recovery_without_filters(self):
        self.assertTrue((ROOT / 'm0/verifier/v70/verify.py').is_file(), 'v70 remaining-reservation group is missing')
        group = command_groups(verifier_tree('v70'))['remaining_physical_reservation_and_mle_usage_end_to_end']
        arguments = [node.value for node in group.args[1].elts if isinstance(node, ast.Constant)]
        for name in ('tests/test_hierarchical_budget.py', 'tests/test_composed_budget.py',
                     'tests/test_composed_recovery.py', 'tests/test_mle_currency_integration.py'):
            self.assertIn(name, arguments)
        self.assertNotIn('-k', arguments)
        self.assertNotIn('-m', arguments[1:])
        self.assertEqual(next(k.value.value for k in group.keywords if k.arg == 'timeout'), 480)

    def test_archived_v68_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v68/LAST_RUN.json":
                "33f864e1c7e36ad7b19ffa461004176b32d9bbe210f90af5aaec4ce52cec457b",
            "m0/verifier/runs/v68.jsonl":
                "f603892915439fc04873a517fce67a7ca1ec92a5bd5932c8e7a3aeb8e8edeea7",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertTrue((ROOT / filename).is_file(), 'verified v68 evidence must be archived')
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / 'm0/verifier/v68/LAST_RUN.json').read_text())
        entries = [json.loads(line) for line in (ROOT / 'm0/verifier/runs/v68.jsonl').read_text().splitlines()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['command'], 'python3 verifier/v68/verify.py')
        self.assertEqual(entries[0]['exit_code'], 0)
        self.assertEqual(entries[0]['checks'], certificate['checks'])
        self.assertTrue(certificate['passed'])
        self.assertEqual(len(certificate['checks']), 38)
        self.assertTrue(all(item['passed'] for item in certificate['checks']))
        self.assertFalse(certificate['mle_composed_stage_evidence']['external_provider_api_executed'])

    def test_v69_keeps_every_v68_command_group_and_timeout(self):
        self.assertTrue((ROOT / 'm0/verifier/v69/verify.py').is_file(), 'v69 verifier must preserve prior coverage')
        previous, current = command_groups(verifier_tree('v68')), command_groups(verifier_tree('v69'))
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v69_executes_isolation_and_currency_boundaries_without_filters(self):
        self.assertTrue((ROOT / 'm0/verifier/v69/verify.py').is_file(), 'v69 budget/isolation group is missing')
        groups = command_groups(verifier_tree('v69'))
        command = groups['mle_private_order_and_shared_currency_campaign_end_to_end'].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ['-m', 'pytest'])
        self.assertTrue({'tests/test_mle_isolation.py', 'tests/test_mle_cny_budget.py',
                         'tests/test_mle_currency_integration.py', 'tests/test_mle_provider.py'} <= set(arguments))
        self.assertNotIn('-m', arguments[2:])
        self.assertNotIn('--markexpr', arguments)

    def test_archived_v67_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v67/LAST_RUN.json":
                "7c3586bca97082fce0ca25f027a5f26b7cd8f4977c3f4bcbd972a4ef0165c37f",
            "m0/verifier/runs/v67.jsonl":
                "f4d8a6d1de90b84c40d57399e5c6597bdb5f927385c5609980ae55562ee79da4",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v67/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v67.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v67/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 37)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        population = certificate["population_stage_evidence"]
        self.assertEqual(population["stage"], "S8")
        self.assertIs(population["certified"], True)
        self.assertIs(population["external_benchmark_campaign_executed"], False)

    def test_v68_keeps_every_v67_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v67"))
        current = command_groups(verifier_tree("v68"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v68_explicitly_executes_mle_composition_and_pilot_without_filters(self):
        groups = command_groups(verifier_tree("v68"))
        command = groups["configured_mle_anchor_feedback_population_and_pilot_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_mle_composed.py", "tests/test_mle_provider.py",
                         "tests/test_mle_pilot.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_archived_v66_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v66/LAST_RUN.json":
                "bd5db5f0038dc326b33f5ff6fef9a70142b76580a5ceb9569344164a647d35e6",
            "m0/verifier/runs/v66.jsonl":
                "cdcbc1a420d1899b23c8d4d1b0f8843747de76da925515e9e47ae7e5f90f778d",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v66/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v66.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v66/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 36)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        worktree = certificate["worktree_recovery_stage_evidence"]
        self.assertEqual(worktree["stage"], "S7")
        self.assertIs(worktree["certified"], True)
        self.assertIs(worktree["mac_linux_security_equivalence_claimed"], False)

    def test_v67_keeps_every_v66_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v66"))
        current = command_groups(verifier_tree("v67"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v67_explicitly_executes_population_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v67"))
        command = groups["configured_population_selection_crossover_and_recovery_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_population_frontier.py",
                         "tests/test_population_components.py",
                         "tests/test_composed_population.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_v66_keeps_every_v65_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v65"))
        current = command_groups(verifier_tree("v66"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v66_explicitly_executes_configured_worktree_recovery_without_filters(self):
        groups = command_groups(verifier_tree("v66"))
        command = groups["configured_worktree_process_identity_and_framework_recovery_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_composed_worktree_executor.py",
                         "tests/test_process_identity_writer.py",
                         "tests/test_composed_worktree_framework.py",
                         "tests/test_composed_recovery.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_archived_v65_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v65/LAST_RUN.json":
                "b4f2c5a9c41213039a4ed7f94059edccef7d22ac5da83d0662bb613fdce6bba2",
            "m0/verifier/runs/v65.jsonl":
                "e6dcca23ad745518490b114b5b1249c81cf211d995d7dd366446821078273943",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v65/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v65.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v65/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 35)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        proxy = certificate["proxy_validity_stage_evidence"]
        self.assertEqual(proxy["stage"], "S6")
        self.assertIs(proxy["certified"], True)
        self.assertIs(proxy["statistical_guarantee_claimed"], False)

    def test_v65_keeps_every_v64_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v64"))
        current = command_groups(verifier_tree("v65"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v65_explicitly_executes_proxy_validity_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v65"))
        command = groups["periodic_anchor_proxy_validity_and_memory_feedback_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_proxy_validity.py",
                         "tests/test_composed_proxy.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_v64_keeps_every_v63_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v63"))
        current = command_groups(verifier_tree("v64"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v64_explicitly_executes_hierarchical_budget_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v64"))
        command = groups["hierarchical_physical_budget_and_fidelity_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_hierarchical_budget.py",
                         "tests/test_composed_budget.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_v64_executes_offline_research_example_and_mac_examples_target(self):
        groups = command_groups(verifier_tree("v64"))
        command = groups["composed_research_offline_example"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments, ["examples/composed_research_offline.py"])
        makefile = (ROOT / "Makefile").read_text()
        examples = makefile.split("\nexamples:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("python examples/composed_research_offline.py", examples)

    def test_v63_keeps_every_v62_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v62"))
        current = command_groups(verifier_tree("v63"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v63_explicitly_executes_layered_admission_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v63"))
        command = groups["layered_admission_and_isolated_final_audit_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_layered_admission.py",
                         "tests/test_composed_admission.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_v62_keeps_every_v61_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v61"))
        current = command_groups(verifier_tree("v62"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v62_explicitly_executes_context_and_knowledge_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v62"))
        command = groups["scoped_context_and_local_knowledge_feedback_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_composed_context.py",
                         "tests/test_composition_context.py",
                         "tests/test_composition_knowledge.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_archived_v64_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v64/LAST_RUN.json":
                "981959d2dc3b24d5c0a70e70739c18fb7422bc7fc779963538fb66f5c4681c39",
            "m0/verifier/runs/v64.jsonl":
                "8758830c77ec2392140ae7ddb0205d8687e2fbbbc0862c760c179b677dbdef6a",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v64/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v64.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v64/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 34)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        budget = certificate["hierarchical_budget_stage_evidence"]
        self.assertEqual(budget["stage"], "S5")
        self.assertIs(budget["certified"], True)
        self.assertIs(budget["external_gpu_execution_certified"], False)

    def test_archived_v63_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v63/LAST_RUN.json":
                "04dbad2a62b140e9596a8df9a34c3e58153a446a47a749565046c0a68fa530c2",
            "m0/verifier/runs/v63.jsonl":
                "ba91d5b210d2e9ee2b09e85be5ea4413573150caf0168f69ea92d02340c383d1",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v63/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v63.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v63/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 32)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        admission = certificate["layered_admission_stage_evidence"]
        self.assertEqual(admission["stage"], "S4")
        self.assertIs(admission["certified"], True)
        self.assertIs(admission["hierarchical_budget_complete"], False)

    def test_archived_v62_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v62/LAST_RUN.json":
                "6cdf8f58a833a814c17a15d7c05619fb82c3ef72f2026e9a9fadf1479786a154",
            "m0/verifier/runs/v62.jsonl":
                "17efa48878f855facf04ed25c4ef6e46499ef9e1e9407f1977ee3376e1adefb8",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v62/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v62.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v62/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 31)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        context = certificate["context_feedback_stage_evidence"]
        self.assertEqual(context["stage"], "S3")
        self.assertIs(context["certified"], True)
        self.assertIs(context["three_layer_admission_complete"], False)

    def test_archived_v61_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v61/LAST_RUN.json":
                "57b70a0cffcfd8962c11bb03d124fb0176fe0628f7771a7f9b57e82ecddccc5b",
            "m0/verifier/runs/v61.jsonl":
                "dea8ac41d8b5c3721aae17ba624183cd979acb82c3ece5509e90f57a11fd8244",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v61/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v61.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v61/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 30)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        evaluation = certificate["evaluation_contract_stage_evidence"]
        self.assertEqual(evaluation["stage"], "S2")
        self.assertIs(evaluation["certified"], True)
        self.assertIs(evaluation["three_layer_admission_complete"], False)

    def test_v61_keeps_every_v60_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v60"))
        current = command_groups(verifier_tree("v61"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v61_explicitly_executes_canonical_evaluation_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v61"))
        command = groups["canonical_evaluation_contract_and_composed_execution_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_evaluation_contract.py",
                         "tests/test_composed_evaluation.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_archived_v60_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v60/LAST_RUN.json":
                "23bab6054fe40f3823946dba1dfcd70b48b144d1f8326b19beb11881a9f8cf03",
            "m0/verifier/runs/v60.jsonl":
                "578d795426ec5bfa0aaca90aca1533747da4cf1b7cb16960488538090182dc64",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v60/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v60.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v60/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertEqual(len(certificate["checks"]), 29)
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))
        composition = certificate["composition_stage_evidence"]
        self.assertEqual(composition["stage"], "S1")
        self.assertIs(composition["certified"], True)
        self.assertIs(composition["unified_evaluation_contract_complete"], False)

    def test_v60_keeps_every_v59_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v59"))
        current = command_groups(verifier_tree("v60"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v60_explicitly_executes_composition_end_to_end_without_filters(self):
        groups = command_groups(verifier_tree("v60"))
        command = groups["composition_registry_defaults_and_runtime_end_to_end"].args[1]
        self.assertIsInstance(command, ast.List)
        arguments = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        self.assertEqual(arguments[:2], ["-m", "pytest"])
        self.assertTrue({"tests/test_composition_registry.py",
                         "tests/test_composition_defaults.py",
                         "tests/test_composed_runtime.py"} <= set(arguments))
        self.assertNotIn("-m", arguments[2:])
        self.assertNotIn("--markexpr", arguments)

    def test_archived_v59_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v59/LAST_RUN.json":
                "7796343856f3706e8f50d8320f89856b98711fd57999d4cb6ffa5e74a94f679c",
            "m0/verifier/runs/v59.jsonl":
                "24e18504243a1e3c2c7f7fbadd6c45f17a38de22b92fe2422203e6044197a275",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v59/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v59.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v59/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))

    def test_v59_keeps_every_v58_command_group_and_timeout(self):
        previous = command_groups(verifier_tree("v58"))
        current = command_groups(verifier_tree("v59"))
        self.assertTrue(previous)
        self.assertTrue(previous.keys() <= current.keys())
        for name, command in previous.items():
            with self.subTest(group=name):
                self.assertEqual(ast.dump(command), ast.dump(current[name]))

    def test_v59_explicitly_executes_each_new_boundary_regression(self):
        groups = command_groups(verifier_tree("v59"))
        expected = {
            "dataset_content_binding_and_evaluation_context_regressions": {
                "tests/test_evaluation_context.py"},
            "process_identity_writer_reader_and_real_recovery_regressions": {
                "tests/test_process_identity_writer.py"},
            "upfront_config_validation_and_isolated_replay_regressions": {
                "tests/test_loop_config_validation.py", "tests/test_replay_isolation.py"},
            "decision_receipt_identity_context_and_audit_regressions": {
                "tests/test_receipt_identity.py"},
        }
        for name, files in expected.items():
            with self.subTest(group=name):
                strings = {node.value for node in ast.walk(groups[name])
                           if isinstance(node, ast.Constant) and isinstance(node.value, str)}
                self.assertTrue(files <= strings)
                command = groups[name].args[1]
                self.assertIsInstance(command, ast.List)
                arguments = [node.value for node in command.elts
                             if isinstance(node, ast.Constant)]
                self.assertEqual(arguments[:2], ["-m", "pytest"])
                self.assertNotIn("-m", arguments[2:])
                self.assertNotIn("--markexpr", arguments)

    def test_archived_v58_is_exact_verified_linux_evidence(self):
        expected = {
            "m0/verifier/v58/LAST_RUN.json":
                "e11b840bd3ddae8af47e54c90cf14e9673d189800189100c03930edfc6a57794",
            "m0/verifier/runs/v58.jsonl":
                "8a19b059ca9a8ae5d86b943eaf8bf9ebd3529ce05b8268558d725d74d00ec552",
        }
        for filename, digest in expected.items():
            with self.subTest(file=filename):
                self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        certificate = json.loads((ROOT / "m0/verifier/v58/LAST_RUN.json").read_text())
        entries = [json.loads(line) for line in
                   (ROOT / "m0/verifier/runs/v58.jsonl").read_text().splitlines()]
        self.assertIs(certificate["passed"], True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["command"], "python3 verifier/v58/verify.py")
        self.assertEqual(entries[0]["exit_code"], 0)
        self.assertEqual(entries[0]["checks"], certificate["checks"])
        self.assertTrue(all(item["passed"] is True for item in certificate["checks"]))


if __name__ == "__main__":
    unittest.main()
