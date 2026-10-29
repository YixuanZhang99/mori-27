"""v34 acceptance: fully started pre-settlement external M0 cohort recovery."""
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
    journal = ROOT / "verifier/runs/v34.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v33_complete", [sys.executable, "verifier/v33/verify.py"])
        run_command("real_fully_started_cohort_sigkill_and_fail_closed_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_batch_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
                     "tests/test_external_genesis_recovery.py",
                     "tests/test_external_control_recovery.py",
                     "tests/test_external_batch_recovery.py",
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
        check("ci_workflow_wiring", "python3 verifier/v34/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_fully_started_cohort_sigkill_and_fail_closed_guards"), None)
        report = {
            "version": "v34", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("one frozen external M0 cohort whose every candidate was proposed "
                           "and started before owner SIGKILL, with zero batch settlement, "
                           "through recovered settlement and serial admission")},
            "previously_certified_windows": [
                "sequential external genesis before the first checkpoint",
                "sequential external improve from process start through admission",
                "same-cycle sequential external improve and IID-RS control"],
            "uncertified_crash_windows": [
                "partially proposed or partially started cohorts",
                "batch post-settlement, post-absorb and post-admission windows",
                "batch plus same-cycle control interruption",
                "machine power loss", "non-external in-process evaluator crashes"],
            "scope": [
                "checkpoint restoration accepts only the current generation's native-bound intents",
                "every frozen candidate has a deterministic improve:generation:slot identity",
                "cohort, candidate, parent, intent, proposal, head and proposer cost bindings are exact",
                "process_kind identifies the external evaluator and execution_ref identifies its cohort",
                "all candidate reserves remain open and no batch finalization evidence already exists",
                "M0PromptExecutor rebuilds native M0 outcomes and canonical M7 evidence without a workspace",
                "BatchScheduler.resume continues original settlement and serial M9 finalization",
                "one m0_batch_recovery_adopted record is appended only after recovered finalization",
                "ForbiddenLLM and three total process starts prove no reproposal or replacement execution",
                "two recovered settlements, fifteen mutations and three gates/admission Receipts are exact",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after the fully started pre-settlement crash",
                "partially started and already settling cohorts fail closed without adoption"],
            "checks": CHECKS}
        (ROOT / "verifier/v34/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v34/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
