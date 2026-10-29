"""v31 acceptance: sequential external improve post-settlement crash recovery."""
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
    journal = ROOT / "verifier/runs/v31.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v30_complete", [sys.executable, "verifier/v30/verify.py"])
        run_command("real_post_settlement_sigkill_success_failure_and_fork_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_post_settlement_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py", "tests/test_external_evaluator.py",
                     "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                     "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                     "tests/test_formal_governance.py", "tests/test_real_load.py"])
        run_command("detached_settlement_process_and_sandbox_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_settlement_crash_recovery.py",
                     "tests/test_batch_execution_recovery.py",
                     "tests/test_executor_recovery.py", "tests/test_sandbox_executor.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v31/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_post_settlement_sigkill_success_failure_and_fork_guards"), None)
        report = {
            "version": "v31", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("sequential single-candidate external improve after native outcome "
                           "and settlement through admission before cycle checkpoint")},
            "uncertified_crash_windows": [
                "genesis", "baseline/control", "batch cohorts",
                "machine power loss", "non-external in-process evaluator crashes"],
            "scope": [
                "journal-first ledger restore admits only one native-outcome-bound extra settlement",
                "settlement amount and account must exactly match proposer plus native token cost",
                "missing reserve-minus-actual delta is restored once without another settlement",
                "checkpoint state_mutation_count binds the exact durable recovery suffix",
                "existing canonical mutations replay only into frontier/memory without new evidence",
                "missing absorb/admission mutations execute once and divergent suffixes fail closed",
                "pure gate evaluation validates existing gate/Receipt payloads before reuse",
                "admission Receipt and recovery adoption are unique and content-matched",
                "recovery adoption is appended only after failure evidence or admission is durable",
                "real SIGKILL drills cover settle/delta, absorb, gate, admission and failure evidence",
                "ForbiddenLLM and two process starts prove no reproposal or replacement execution",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after the final admission-receipt crash drill"],
            "checks": CHECKS}
        (ROOT / "verifier/v31/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v31/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
