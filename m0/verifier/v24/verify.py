"""v24 acceptance: complete physical token-cost evidence, not benchmark performance."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHECKS = []


def check(name, passed, detail):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": str(detail)})
    print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}", flush=True)


def run_command(name, command, timeout=180):
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
    journal = ROOT / "verifier/runs/v24.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v23_complete", [sys.executable, "verifier/v23/verify.py"])
        check("bubblewrap_installed", shutil.which("bwrap") is not None,
              shutil.which("bwrap"))
        run_tests("per_call_metering_and_real_dual_arm_smoke",
                  ["tests/test_benchmark_agents.py"])
        run_tests("campaign_cost_evidence_and_adversarial_regression",
                  ["tests/test_benchmark_runner.py", "tests/test_benchmark_adapters.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v24/verify.py" in workflow,
              "current verifier command")
        passed = all(item["passed"] for item in CHECKS)
        rc = 0 if passed else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        report = {
            "version": "v24", "passed": rc == 0,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "reason": "local HTTP and grading fixtures validate complete token accounting and agent mechanics only; the official 22-task data/model campaign has not run"},
            "scope": ["one immutable receipt per real LLM call",
                      "cumulative governed proposer plus solution metering between resets",
                      "metered OpenEvolve host-evolution calls",
                      "independent campaign receipt recomputation and actual backbone evidence",
                      "missing, inconsistent, tampered and over-budget usage fail closed",
                      "token costs never enter M9 and no USD conversion is invented"],
            "checks": CHECKS}
        (ROOT / "verifier/v24/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v24/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
