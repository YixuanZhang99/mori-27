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
certificate = {'version': 'v57', 'passed': True, 'checks': checks}
entry = {'command': 'python3 verifier/v57/verify.py', 'exit_code': 0, 'checks': checks}
"""
WRITE_CERTIFICATE = "Path('verifier/v57/LAST_RUN.json').write_text(json.dumps(certificate))\n"
APPEND_JOURNAL = "with Path('verifier/runs/v57.jsonl').open('a') as f: f.write(json.dumps(entry) + '\\n')\n"


class AcceptanceRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="mori27-runner-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "m0/verifier/v57").mkdir(parents=True)
        (self.root / "m0/verifier/runs").mkdir()
        self.original = {
            "verifier/v57/LAST_RUN.json": '{"version":"v57","passed":true,"checks":[{"check":"old","passed":true}]}\n',
            "verifier/runs/v57.jsonl": '{"exit_code":0,"checks":[{"check":"old","passed":true}]}\n',
        }
        for name, text in self.original.items():
            (self.root / "m0" / name).write_text(text)

    def run_fixture(self, body: str, *, timeout: float = 3, max_log_bytes: int | None = None):
        (self.root / "m0/verifier/v57/verify.py").write_text(HEADER + body)
        with patch.object(runner, "ROOT", self.root), \
             patch.object(runner, "MAX_LOG_BYTES", max_log_bytes or runner.MAX_LOG_BYTES), \
             contextlib.redirect_stdout(io.StringIO()):
            status = runner.main(["--output", str(self.root / "artifacts"), "--timeout", str(timeout)])
        outputs = sorted((self.root / "artifacts").glob("*/summary.json"))
        summary_path = outputs[-1]
        summary = json.loads(summary_path.read_text())
        for name, text in self.original.items():
            self.assertEqual((self.root / "m0" / name).read_text(), text)
        return status, summary, summary_path.parent

    def test_success_requires_matching_fresh_certificate_and_journal(self):
        status, summary, output = self.run_fixture(WRITE_CERTIFICATE + APPEND_JOURNAL)
        self.assertEqual(status, 0)
        self.assertTrue(summary["passed"])
        self.assertTrue(summary["new_journal_passed"])
        self.assertEqual(len((output / "new-runs.jsonl").read_text().splitlines()), 1)

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
            "Path('verifier/v57/LAST_RUN.json').write_text('{broken')\n" + APPEND_JOURNAL)
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
            + "Path('verifier/runs/v57.jsonl').write_text(json.dumps(entry) + '\\n')\n")
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
