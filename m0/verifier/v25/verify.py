"""v25 acceptance: honest B1 terminal self-attestation, not external GEPA certification."""
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


def run_command(name, command, timeout=240):
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "skipped" not in output.lower(), output[-3500:])


def run_tests(name, nodes):
    run_command(name, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                       "-rs", *nodes])


def main():
    journal = ROOT / "verifier/runs/v25.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v24_complete", [sys.executable, "verifier/v24/verify.py"])
        run_tests("b1_threshold_tie_failure_and_missing_baseline",
                  ["tests/test_self_attestation.py"])
        run_tests("gate_loop_checkpoint_and_replay_regression",
                  ["tests/test_axioms.py", "tests/test_real_load.py",
                   "tests/test_loop_batch.py", "tests/test_loop_checkpoint.py",
                   "tests/test_loop_governed_state.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v25/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        report = {
            "version": "v25", "passed": rc == 0,
            "b1_external_gepa_attestation": {
                "executed": False, "passed": None,
                "reason": "controlled offline fixtures verify the terminal decision rule only; no external GEPA campaign or measured noise-floor claim is produced"},
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False},
            "scope": ["best score minus IID-RS mean compared strictly with declared noise floor",
                      "PASS, INADJUDICABLE, FAIL and INSUFFICIENT_EVIDENCE terminal verdicts",
                      "append-only self-attestation evidence",
                      "finite non-negative noise-floor validation",
                      "M9 remains per-item flip-only and unchanged"],
            "checks": CHECKS}
        (ROOT / "verifier/v25/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v25/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
