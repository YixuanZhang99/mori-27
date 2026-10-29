"""v21 acceptance: opt-in M0 frozen cohorts through canonical BatchScheduler.

This is same-process cycle-boundary recovery, not detached M0 crash recovery or
parallel execution of the legacy process-global token meter.
"""
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


def run_tests(name, nodes, timeout=90):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "-rs", *nodes], cwd=ROOT, env=env, text=True,
                          capture_output=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "skipped" not in output.lower(), output[-3500:])


def main():
    journal = ROOT / "verifier/runs/v21.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        history_path = ROOT / "verifier/runs/v20.jsonl"
        history = history_path.read_text().strip().splitlines() if history_path.exists() else []
        prior = json.loads(history[-1]) if history else {}
        check("v20_complete", prior.get("exit_code") == 0, prior.get("exit_code"))
        run_tests("m0_frozen_cohorts", ["tests/test_loop_batch.py"])
        run_tests("legacy_loop_and_checkpoint_regression",
                  ["tests/test_loop_checkpoint.py", "tests/test_loop_governed_state.py",
                   "tests/test_real_load.py"])
        run_tests("canonical_scheduler_regression",
                  ["tests/test_batch_scheduler.py", "tests/test_batch_recovery.py",
                   "tests/test_batch_multicurrency.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v21/verify.py" in workflow,
              "current verifier command")
        passed = all(item["passed"] for item in CHECKS)
        report = {"version": "v21", "passed": passed,
                  "scope": ["opt-in M0 batch_size",
                            "frozen parent and incumbent per cohort",
                            "settle-before-serial-admission", "exact serialized token metering",
                            "cycle checkpoint resume and replay"],
                  "exclusions": ["detached M0 crash recovery", "parallel global token metering",
                                 "external benchmark", "hosted CI execution"],
                  "checks": CHECKS}
        (ROOT / "verifier/v21/LAST_RUN.json").write_text(json.dumps(report, indent=2))
        rc = 0 if passed else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        journal.open("a").write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v21/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
