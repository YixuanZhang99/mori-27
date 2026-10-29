"""v38 acceptance: fail-closed default Bubblewrap for external M0 evaluation."""
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
    journal = ROOT / "verifier/runs/v38.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v37_complete", [sys.executable, "verifier/v37/verify.py"], timeout=1200)
        run_command("default_sandbox_isolation_disable_fail_closed_and_fork",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_default_sandbox.py",
                     "tests/test_external_evaluator.py"])
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
                     "tests/test_external_evaluator.py",
                     "tests/test_external_default_sandbox.py",
                     "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                     "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                     "tests/test_formal_governance.py", "tests/test_real_load.py"], timeout=600)
        run_command("detached_settlement_process_and_sandbox_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_settlement_crash_recovery.py",
                     "tests/test_batch_execution_recovery.py",
                     "tests/test_executor_recovery.py", "tests/test_sandbox_executor.py"])
        run_command("complete_local_regression",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    timeout=600)
        run_command("static_axioms", [sys.executable, "ci/check_axioms.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v38/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        sandbox_check = next((item for item in CHECKS if item["check"] ==
                              "default_sandbox_isolation_disable_fail_closed_and_fork"), None)
        report = {
            "version": "v38", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "supersedes": ["v29-v37 opt-in Bubblewrap for ExternalCommandEvaluator"],
            "external_sandbox_policy": {
                "executed": sandbox_check is not None,
                "certified": rc == 0 and bool(sandbox_check and sandbox_check["passed"]),
                "default": "BubblewrapSandbox",
                "explicit_disable": "sandbox=None or sandbox=False",
                "missing_bwrap": "constructor fails closed before process launch"},
            "previously_certified_windows": [
                "sequential external genesis, improve and same-cycle control",
                "prepared external cohorts from zero/partial starts through finalization",
                "completed external batch plus same-cycle control before checkpoint"],
            "uncertified_boundaries": [
                "incomplete proposal journals",
                "missing processes combined with settlement or finalization evidence",
                "machine power loss", "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary"],
            "scope": [
                "omitting sandbox or passing True constructs real BubblewrapSandbox",
                "missing bwrap fails construction without a process or native outcome",
                "only explicit None or False disables isolation and records disabled policy",
                "real default probes clear environment and block host file/network access",
                "private escape writes do not reach the host under the default policy",
                "explicit disable probes prove host environment/file/network/write access",
                "every process start records sandbox_policy without environment values",
                "fork/replay inherits policy and keeps independent process/outcome histories",
                "all v30-v37 owner-crash recovery tests execute with default Bubblewrap",
                "no seccomp, complete resource-limit or machine-power-loss claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v38/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v38/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
