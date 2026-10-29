"""v36 acceptance: completed external M0 batch plus same-cycle control recovery."""
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
    journal = ROOT / "verifier/runs/v36.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v35_complete", [sys.executable, "verifier/v35/verify.py"])
        run_command("real_completed_batch_control_sigkill_and_lineage_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_batch_control_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
                     "tests/test_external_genesis_recovery.py",
                     "tests/test_external_control_recovery.py",
                     "tests/test_external_batch_recovery.py",
                     "tests/test_external_batch_post_settlement_recovery.py",
                     "tests/test_external_batch_control_recovery.py",
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
        check("ci_workflow_wiring", "python3 verifier/v36/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_completed_batch_control_sigkill_and_lineage_guards"), None)
        report = {
            "version": "v36", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("one external M0 cohort after completed finalization and required "
                           "Framework admission Receipts but before checkpoint, together with "
                           "its started same-cycle IID-RS control from process start through "
                           "baseline or failure evidence")},
            "previously_certified_windows": [
                "sequential external genesis before the first checkpoint",
                "sequential external improve from process start through admission",
                "same-cycle sequential external improve and IID-RS control",
                "fully started external M0 cohorts from process start through finalization"],
            "uncertified_crash_windows": [
                "partially proposed or partially started cohorts",
                "control started before batch finalization or required Receipts are complete",
                "machine power loss", "non-external in-process evaluator crashes"],
            "scope": [
                "batch recovery remains the v35 exact mutation-cursor suffix path",
                "same-cycle control is accepted only after unique batch completion and complete gates/Receipts",
                "control uses the locked control account, deterministic control:generation lineage and no parent",
                "native proposer plus evaluator costs and settle/delta gaps are reconciled exactly once",
                "successful control writes exactly one baseline and baseline evidence",
                "failed control writes structured executor evidence and no baseline",
                "control never enters M9, frontier, memory, admission Receipts or accepted pool",
                "four process starts and ForbiddenLLM prove no reproposal or replacement execution",
                "batch and control each persist exactly one recovery adoption",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after pre-settlement and baseline crashes",
                "baseline mismatch and wrong lineage fail before control adoption",
                "completed resume neither readopts nor re-executes"],
            "checks": CHECKS}
        (ROOT / "verifier/v36/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v36/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
