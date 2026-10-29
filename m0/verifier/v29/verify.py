"""v29 acceptance: explicit external M0 evaluator process and protocol boundary."""
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
    journal = ROOT / "verifier/runs/v29.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v28_complete", [sys.executable, "verifier/v28/verify.py"])
        run_command("external_process_protocol_and_real_sandbox",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_evaluator.py"])
        run_command("sequential_batch_checkpoint_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_loop_batch.py", "tests/test_loop_checkpoint.py",
                     "tests/test_real_load.py", "tests/test_formal_governance.py"])
        run_command("detached_process_and_existing_sandbox_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_executor_recovery.py", "tests/test_sandbox_executor.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v29/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        report = {
            "version": "v29", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "m0_owner_crash_recovery": {"executed": False, "certified": False},
            "scope": ["versioned external request/result/token-usage JSON protocol",
                      "one real journaled subprocess per candidate evaluation",
                      "strict candidate/head/item/result/usage validation",
                      "atomic persistent native outcome plus append-only outcome evidence",
                      "timeout, nonzero exit and malformed response map to structured failure",
                      "sequential evaluator exceptions become settled EvidenceRecord, not loop escapes",
                      "batch external failures remain settled/pruned and outside M9",
                      "real Bubblewrap environment/file/network/private-write probes are non-skipped",
                      "replay forks external evidence into an independent run history",
                      "no Framework owner-crash exactly-once recovery is claimed in v29"],
            "checks": CHECKS}
        (ROOT / "verifier/v29/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v29/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
