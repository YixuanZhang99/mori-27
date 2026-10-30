"""Guard the acceptance version transition without executing Linux workloads."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import unittest


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
