"""v39 acceptance: real, auditable resource limits for external M0 evaluation."""
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
    journal = ROOT / "verifier/runs/v39.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v38_complete", [sys.executable, "verifier/v38/verify.py"], timeout=1500)
        run_command("real_resource_limits_policy_audit_replay_and_owner_recovery",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_resource_policy.py",
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
                     "tests/test_external_resource_policy.py",
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
        check("ci_workflow_wiring", "python3 verifier/v39/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        resource_check = next((item for item in CHECKS if item["check"] ==
                               "real_resource_limits_policy_audit_replay_and_owner_recovery"), None)
        report = {
            "version": "v39", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "supersedes": ["v38 absence of explicit external evaluator resource limits"],
            "external_resource_policy": {
                "executed": resource_check is not None,
                "certified": rc == 0 and bool(resource_check and resource_check["passed"]),
                "limits": ["RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_NPROC"],
                "default": {}, "recovery": "original native outcome adopted exactly once"},
            "previously_certified_windows": [
                "default Bubblewrap with explicit audited disable",
                "sequential external genesis, improve and same-cycle control",
                "prepared external cohorts from zero/partial starts through finalization",
                "completed external batch plus same-cycle control before checkpoint"],
            "uncertified_boundaries": [
                "incomplete proposal journals",
                "missing processes combined with settlement or finalization evidence",
                "machine power loss", "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas"],
            "scope": [
                "ResourcePolicy validates optional positive memory/file/process limits",
                "detached wrapper applies hard limits before executing bwrap or a disabled-sandbox command",
                "real probes prove excess allocation, file writes and candidate forks are refused",
                "UID-wide RLIMIT_NPROC tests account for existing threads and bwrap startup",
                "an unstartable process limit produces structured failed_to_run evidence",
                "process spec and start evidence record only configured numeric limits",
                "unconfigured policy remains an explicit empty object",
                "fork/replay inherits policy with independent process/outcome histories",
                "resource-policy owner SIGKILL adopts one original outcome without reexecution",
                "no cgroup, complete-resource, seccomp or machine-power-loss claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v39/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v39/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
