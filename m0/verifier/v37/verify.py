"""v37 acceptance: prepared external cohort recovery with zero/partial process starts."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHECKS = []


def check(name, passed, detail):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": str(detail)})
    print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}", flush=True)


def environment():
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
    return env


def run_command(name, command, timeout=300):
    proc = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                          text=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "skipped" not in output.lower(), output[-3500:])


def main():
    journal = ROOT / "verifier/runs/v37.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v36_complete", [sys.executable, "verifier/v36/verify.py"], timeout=900)
        run_command("real_prepared_partial_start_sigkill_and_fail_closed_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_batch_partial_start_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
                     "tests/test_external_genesis_recovery.py",
                     "tests/test_external_control_recovery.py",
                     "tests/test_external_batch_recovery.py",
                     "tests/test_external_batch_post_settlement_recovery.py",
                     "tests/test_external_batch_control_recovery.py",
                     "tests/test_external_batch_partial_start_recovery.py",
                     "tests/test_external_evaluator.py", "tests/test_loop_checkpoint.py",
                     "tests/test_loop_batch.py", "tests/test_loop_governed_state.py",
                     "tests/test_governance_audit.py", "tests/test_formal_governance.py",
                     "tests/test_real_load.py"])
        run_command("detached_settlement_process_and_sandbox_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_settlement_crash_recovery.py",
                     "tests/test_batch_execution_recovery.py",
                     "tests/test_executor_recovery.py", "tests/test_sandbox_executor.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v37/verify.py" in workflow,
              "current verifier command; v36 partial-start refusal is superseded")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_prepared_partial_start_sigkill_and_fail_closed_guards"), None)
        report = {
            "version": "v37", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "supersedes": [
                "v34-v36 refusal of every partially started external M0 cohort",
                "incomplete proposal journals and settlement/finalization gaps remain fail-closed"],
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("one reserved external M0 cohort with every proposal durably "
                           "journaled before execution, zero or more candidate processes "
                           "started, and no settlement or finalization")},
            "previously_certified_windows": [
                "sequential external genesis, improve and same-cycle control",
                "fully started external cohorts through finalization",
                "completed external batch plus same-cycle control before checkpoint"],
            "uncertified_crash_windows": [
                "incomplete proposal journals",
                "missing processes combined with settlement or finalization evidence",
                "machine power loss", "non-external in-process evaluator crashes"],
            "scope": [
                "external cohort proposals are persisted after atomic reservation and before any process launch",
                "recovery requires exactly one valid durable proposal and intent per frozen candidate",
                "existing processes must form a unique subset with exact evaluation contexts",
                "started candidates adopt only their original native outcomes",
                "never-started candidates continue once from their original proposals without reproposal",
                "partial starts with settlement evidence fail before any new process",
                "executor evidence, settlement, serial M9 and Receipts remain exactly once",
                "adoption records distinguish adopted and continued processes without calling continuation reexecution",
                "three total process starts and ForbiddenLLM prove no reproposal or replacement execution",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after one-started recovery",
                "completed resume neither readopts nor re-executes"],
            "checks": CHECKS}
        (ROOT / "verifier/v37/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v37/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
