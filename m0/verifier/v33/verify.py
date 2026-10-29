"""v33 acceptance: same-cycle external improve/IID-RS control crash recovery."""
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
    journal = ROOT / "verifier/runs/v33.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v32_complete", [sys.executable, "verifier/v32/verify.py"])
        run_command("real_control_sigkill_pre_post_settlement_failure_and_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_control_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
                     "tests/test_external_genesis_recovery.py",
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
        check("ci_workflow_wiring", "python3 verifier/v33/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_control_sigkill_pre_post_settlement_failure_and_guards"), None)
        report = {
            "version": "v33", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("sequential external improve and IID-RS control in one unfinished "
                           "cycle from control process start through baseline/failure evidence "
                           "and the cycle checkpoint")},
            "previously_certified_windows": [
                "sequential external genesis before the first checkpoint",
                "sequential external improve from process start through admission"],
            "uncertified_crash_windows": [
                "batch cohorts", "machine power loss",
                "non-external in-process evaluator crashes"],
            "scope": [
                "control shares the unfinished generation with its preceding improve candidate",
                "checkpoint restore admits only native-bound improve/control settlements or one open reserve",
                "open reserves bind a journaled process even before its native outcome exists",
                "settled intents require completed native outcomes and exact account/token costs",
                "the same-cycle improve suffix resumes before control finalization",
                "control uses its deterministic control:generation lineage and locked control account",
                "successful control appends one baseline score and generation/main-score-bound evidence",
                "failed control reuses or appends one executor failure and never creates baseline evidence",
                "control never enters M9, frontier, memory or admission Receipt state",
                "real SIGKILL drills cover pre-settlement, settle/delta, baseline and failure evidence",
                "baseline mismatch and wrong control lineage fail before control adoption",
                "three process starts and ForbiddenLLM prove no replacement execution or reproposal",
                "completed resume does not readopt control or launch another process",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after pre-settlement and baseline crash drills"],
            "checks": CHECKS}
        (ROOT / "verifier/v33/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v33/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
