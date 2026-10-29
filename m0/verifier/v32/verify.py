"""v32 acceptance: external genesis owner-crash recovery before first checkpoint."""
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
    journal = ROOT / "verifier/runs/v32.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v31_complete", [sys.executable, "verifier/v31/verify.py"])
        run_command("real_genesis_sigkill_pre_post_settlement_and_anchor_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_genesis_recovery.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
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
        check("ci_workflow_wiring", "python3 verifier/v32/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        crash_check = next((item for item in CHECKS if item["check"] ==
                            "real_genesis_sigkill_pre_post_settlement_and_anchor_guards"), None)
        report = {
            "version": "v32", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {
                "executed": crash_check is not None,
                "certified": rc == 0 and bool(crash_check and crash_check["passed"]),
                "window": ("sequential single-candidate external genesis from process start "
                           "through settlement and admission before the first checkpoint")},
            "previously_certified_windows": [
                "sequential external improve before settlement",
                "sequential external improve after settlement through admission before checkpoint"],
            "uncertified_crash_windows": [
                "baseline/control", "batch cohorts", "machine power loss",
                "non-external in-process evaluator crashes"],
            "scope": [
                "genesis recovery requires no checkpoint and exactly one compatible run_start",
                "the unique generation-zero draft evaluation anchor binds deterministic lineage",
                "journal-first ledger restore rejects unrelated reserves or settlements",
                "one matching external process and native outcome are adopted without reproposal",
                "open reserves settle once; existing settlements are reconciled without duplication",
                "the five canonical genesis mutations resume by exact durable suffix",
                "existing gate, Receipt, admission and adoption payloads must match exactly",
                "real SIGKILL drills cover pre-settlement, settle/delta, absorb, gate and admission",
                "missing or duplicate run anchors, wrong lineage and mutation forks fail closed",
                "ForbiddenLLM and one process start prove no reproposal or replacement execution",
                "recovered results, ledger, health, governed state and snapshots match controls",
                "fresh certified replay passes after pre-settlement and final admission crashes"],
            "checks": CHECKS}
        (ROOT / "verifier/v32/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v32/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
