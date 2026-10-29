"""Offline contract tests for the acceptance wrapper, using temporary fake verifiers."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "run_acceptance.py"
SPEC = importlib.util.spec_from_file_location("acceptance_runner_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

HEADER = """import json, os, sys, time
from pathlib import Path
checks = [{'check': 'synthetic_check', 'passed': True, 'detail': 'fixture'}]
certificate = {'version': 'v62', 'passed': True, 'checks': checks}
entry = {'command': 'python3 verifier/v62/verify.py', 'exit_code': 0, 'checks': checks}
"""
WRITE_CERTIFICATE = "Path('verifier/v62/LAST_RUN.json').write_text(json.dumps(certificate))\n"
APPEND_JOURNAL = "with Path('verifier/runs/v62.jsonl').open('a') as f: f.write(json.dumps(entry) + '\\n')\n"


class AcceptanceRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="mori27-runner-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "m0/verifier/v62").mkdir(parents=True)
        (self.root / "m0/verifier/runs").mkdir()
        self.original = {
            "verifier/v62/LAST_RUN.json": '{"version":"v62","passed":true,"checks":[{"check":"old","passed":true}]}\n',
            "verifier/runs/v62.jsonl": '{"exit_code":0,"checks":[{"check":"old","passed":true}]}\n',
            "verifier/v61/LAST_RUN.json": '{"version":"v61","passed":true}\n',
            "verifier/runs/v61.jsonl": '{"exit_code":0,"checks":{"historical":true}}\n',
        }
        for name, text in self.original.items():
            (self.root / "m0" / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / "m0" / name).write_text(text)

    def run_fixture(self, body: str, *, timeout: float = 3, max_log_bytes: int | None = None):
        (self.root / "m0/verifier/v62/verify.py").write_text(HEADER + body)
        with patch.object(runner, "ROOT", self.root), \
             patch.object(runner, "MAX_LOG_BYTES", max_log_bytes or runner.MAX_LOG_BYTES), \
             contextlib.redirect_stdout(io.StringIO()):
            status = runner.main(["--output", str(self.root / "artifacts"), "--timeout", str(timeout)])
        outputs = sorted((self.root / "artifacts").glob("*/summary.json"))
        summary_path = outputs[-1]
        summary = json.loads(summary_path.read_text())
        for name, text in self.original.items():
            if text is None:
                self.assertFalse((self.root / "m0" / name).exists())
            else:
                self.assertEqual((self.root / "m0" / name).read_text(), text)
        return status, summary, summary_path.parent

    def without_current_history(self):
        for name in runner.HISTORY:
            (self.root / "m0" / name).unlink()
            self.original[name] = None

    def test_success_requires_matching_fresh_certificate_and_journal(self):
        status, summary, output = self.run_fixture(WRITE_CERTIFICATE + APPEND_JOURNAL)
        self.assertEqual(status, 0)
        self.assertTrue(summary["passed"])
        self.assertTrue(summary["new_journal_passed"])
        self.assertEqual(len((output / "new-runs.jsonl").read_text().splitlines()), 1)

    def test_first_run_needs_no_fabricated_source_certificate_or_journal(self):
        self.without_current_history()
        status, summary, output = self.run_fixture(WRITE_CERTIFICATE + APPEND_JOURNAL)
        self.assertEqual(status, 0)
        self.assertEqual(summary["verifier_version"], "v62")
        self.assertTrue(summary["source_history_unchanged"])
        self.assertTrue((output / "LAST_RUN.json").is_file())
        self.assertTrue((output / "v62.jsonl").is_file())
        self.assertEqual((output / "v62.jsonl").read_bytes(),
                         (output / "new-runs.jsonl").read_bytes())

    def test_first_run_still_rejects_missing_fresh_evidence(self):
        self.without_current_history()
        status, summary, _ = self.run_fixture("pass\n")
        self.assertEqual(status, 1)
        self.assertTrue(summary["source_history_unchanged"])
        self.assertFalse(summary["certificate_passed"])
        self.assertFalse(summary["new_journal_passed"])

    def test_previous_version_outputs_cannot_certify_current_version(self):
        status, summary, _ = self.run_fixture(
            "certificate['version'] = 'v61'\n"
            "entry['command'] = 'python3 verifier/v61/verify.py'\n"
            + WRITE_CERTIFICATE + APPEND_JOURNAL)
        self.assertEqual(status, 1)
        self.assertFalse(summary["certificate_passed"])
        self.assertFalse(summary["new_journal_passed"])

    def test_active_workflow_context_is_copied_beside_isolated_m0(self):
        for name in runner.CONTROL_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture control: " + name)
        body = "\n".join(
            f"assert Path('../{name}').read_text() == {'fixture control: ' + name!r}"
            for name in runner.CONTROL_FILES) + "\n"
        status, summary, _ = self.run_fixture(body + WRITE_CERTIFICATE + APPEND_JOURNAL)
        self.assertEqual(status, 0)
        self.assertTrue(summary["passed"])

    def test_historical_success_is_not_reused(self):
        status, summary, output = self.run_fixture("pass\n")
        self.assertEqual(status, 1)
        self.assertFalse(summary["certificate_passed"])
        self.assertFalse((output / "LAST_RUN.json").exists())

    def test_fresh_certificate_without_new_journal_is_rejected(self):
        status, summary, _ = self.run_fixture(WRITE_CERTIFICATE)
        self.assertEqual(status, 1)
        self.assertTrue(summary["certificate_passed"])
        self.assertFalse(summary["new_journal_passed"])

    def test_malformed_certificate_produces_failure_summary(self):
        status, summary, _ = self.run_fixture(
            "Path('verifier/v62/LAST_RUN.json').write_text('{broken')\n" + APPEND_JOURNAL)
        self.assertEqual(status, 1)
        self.assertFalse(summary["certificate_passed"])
        self.assertTrue(any("malformed" in error for error in summary["errors"]))

    def test_failed_or_empty_checks_cannot_certify_success(self):
        for checks in ([], [{"check": "bad", "passed": False}]):
            with self.subTest(checks=checks):
                status, summary, _ = self.run_fixture(
                    f"certificate['checks'] = entry['checks'] = {checks!r}\n"
                    + WRITE_CERTIFICATE + APPEND_JOURNAL)
                self.assertEqual(status, 1)
                self.assertFalse(summary["passed"])

    def test_different_certificate_and_journal_checks_are_rejected(self):
        status, summary, _ = self.run_fixture(WRITE_CERTIFICATE
            + "entry['checks'] = [{'check': 'different', 'passed': True}]\n" + APPEND_JOURNAL)
        self.assertEqual(status, 1)
        self.assertFalse(summary["new_journal_passed"])

    def test_multiple_new_journal_entries_are_rejected(self):
        status, summary, _ = self.run_fixture(WRITE_CERTIFICATE + APPEND_JOURNAL + APPEND_JOURNAL)
        self.assertEqual(status, 1)
        self.assertFalse(summary["new_journal_passed"])

    def test_rewritten_historical_journal_is_rejected(self):
        status, summary, _ = self.run_fixture(WRITE_CERTIFICATE
            + "Path('verifier/runs/v62.jsonl').write_text(json.dumps(entry) + '\\n')\n")
        self.assertEqual(status, 1)
        self.assertTrue(any("rewrote" in error for error in summary["errors"]))

    def test_nonzero_exit_is_rejected_even_with_passing_outputs(self):
        status, summary, _ = self.run_fixture(WRITE_CERTIFICATE + APPEND_JOURNAL + "sys.exit(7)\n")
        self.assertEqual(status, 1)
        self.assertEqual(summary["verifier_exit_code"], 7)

    @unittest.skipUnless(os.name == "posix", "process-group cleanup uses POSIX signals")
    def test_timeout_without_newline_is_bounded_and_reaps_verifier(self):
        started = time.monotonic()
        status, summary, output = self.run_fixture(
            "sys.stdout.write(str(os.getpid())); sys.stdout.flush(); time.sleep(10)\n", timeout=0.3)
        self.assertEqual(status, 1)
        self.assertTrue(summary["timed_out"])
        self.assertLess(time.monotonic() - started, 4)
        pid = int((output / "console.log").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_output_limit_rejects_unbounded_stream(self):
        status, summary, output = self.run_fixture(
            "sys.stdout.write('x' * 100000); sys.stdout.flush(); time.sleep(10)\n", max_log_bytes=1024)
        self.assertEqual(status, 1)
        self.assertTrue(any("output exceeded" in error for error in summary["errors"]))
        self.assertEqual((output / "console.log").stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
