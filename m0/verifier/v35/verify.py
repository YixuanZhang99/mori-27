"""v35 acceptance: external M0 cohort recovery through finalization."""
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
    journal = ROOT / "verifier/runs/v35.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v33_complete", [sys.executable, "verifier/v33/verify.py"])
        run_command("v34_surviving_pre_settlement_and_partial_start_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_batch_recovery.py"])
        run_command("real_post_settlement_batch_sigkill_suffix_and_fork_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_batch_post_settlement_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
                     "tests/test_external_genesis_recovery.py",
                     "tests/test_external_control_recovery.py",
                     "tests/test_external_batch_recovery.py",
                     "tests/test_external_batch_post_settlement_recovery.py",
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
        check("ci_workflow_wiring", "python3 verifier/v35/verify.py" in workflow,
              "current verifier command; historical v34 negative guard is superseded")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_post_settlement_batch_sigkill_suffix_and_fork_guards"), None)
        report = {
            "version": "v35", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "supersedes": [
                "v34 refusal of every post-settlement external M0 cohort",
                "generic BatchScheduler decision-without-admission recovery remains unchanged"],
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("one fully started external M0 cohort from its first settlement "
                           "through absorb, M9, admission, batch completion and Framework "
                           "admission Receipts before the cycle checkpoint")},
            "previously_certified_windows": [
                "sequential external genesis before the first checkpoint",
                "sequential external improve from process start through admission",
                "same-cycle sequential external improve and IID-RS control",
                "fully started pre-settlement external M0 cohorts"],
            "uncertified_crash_windows": [
                "partially proposed or partially started cohorts",
                "batch plus same-cycle control interruption",
                "machine power loss", "non-external in-process evaluator crashes"],
            "scope": [
                "recovery reconstructs candidates and intents from the original frozen cohort",
                "remaining budget never shrinks or replaces a recovered cohort",
                "every settled intent matches original native proposer plus evaluator token cost",
                "settle/delta gaps append only the missing reserve-minus-actual delta",
                "a checkpoint mutation cursor drives exact apply-or-replay suffix recovery",
                "durable mutations replay only into frontier and memory without duplicate evidence",
                "absorb, decision, admission and completion markers must agree with mutation boundaries",
                "existing gates and Receipts are regenerated deterministically and compared exactly",
                "decision-without-admission is recoverable only with the Framework checkpoint cursor",
                "generic BatchScheduler resume retains its v16 ambiguous-status refusal",
                "batch completion and Framework admission Receipts are idempotent on recovery",
                "three process starts and ForbiddenLLM prove no reproposal or replacement execution",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after the final admission-Receipt crash",
                "mutation forks and premature admission markers fail before recovery adoption"],
            "checks": CHECKS}
        (ROOT / "verifier/v35/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v35/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
