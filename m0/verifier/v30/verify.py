"""v30 acceptance: sequential external improve owner-crash exactly-once adoption."""
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
    journal = ROOT / "verifier/runs/v30.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v29_complete", [sys.executable, "verifier/v29/verify.py"])
        run_command("real_owner_sigkill_sequential_improve_recovery",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py"])
        run_command("external_protocol_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_evaluator.py", "tests/test_loop_checkpoint.py",
                     "tests/test_loop_batch.py", "tests/test_governance_audit.py",
                     "tests/test_formal_governance.py", "tests/test_real_load.py"])
        run_command("detached_process_settlement_and_sandbox_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_executor_recovery.py", "tests/test_batch_execution_recovery.py",
                     "tests/test_settlement_crash_recovery.py",
                     "tests/test_sandbox_executor.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v30/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS
                            if item["check"] ==
                            "real_owner_sigkill_sequential_improve_recovery"), None)
        report = {
            "version": "v30", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": "sequential single-candidate external improve before settlement"},
            "uncertified_crash_windows": [
                "genesis", "baseline/control", "batch cohorts", "post-settlement",
                "post-absorb", "post-admission", "other post-evaluation windows",
                "machine power loss"],
            "scope": [
                "journal-first ledger restoration reconciles checkpoint spending and open reserves",
                "m0_evaluation_started binds proposal, intent, head, operator and proposer cost",
                "process evaluation_context exactly matches the persisted start evidence",
                "real owner SIGKILL recovery waits for and adopts the original native outcome",
                "ForbiddenLLM proves no reproposal and two process starts prove no re-execution",
                "exactly one recovery adoption, improve gate and candidate Receipt chain entry",
                "recovered result, ledger, health and governed state equal the uninterrupted control",
                "original/recovered certified snapshot refs match and fresh certified replay passes",
                "post-checkpoint settlement ambiguity fails closed without duplicate settlement",
                "only sequential pre-settlement improve recovery is certified in v30"],
            "checks": CHECKS}
        (ROOT / "verifier/v30/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v30/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
