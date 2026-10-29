"""v23 acceptance: real local dual-arm agent smoke, not external benchmark performance."""
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


def run_command(name, command, timeout=120):
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
    journal = ROOT / "verifier/runs/v23.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v22_complete", [sys.executable, "verifier/v22/verify.py"])
        check("bubblewrap_installed", shutil.which("bwrap") is not None,
              shutil.which("bwrap"))
        run_tests("real_local_openai_dual_arm_smoke", ["tests/test_benchmark_agents.py"])
        run_tests("public_data_and_campaign_regression",
                  ["tests/test_benchmark_adapters.py", "tests/test_benchmark_runner.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v23/verify.py" in workflow,
              "current verifier command")
        passed = all(item["passed"] for item in CHECKS)
        report = {
            "version": "v23", "passed": passed,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "reason": "local HTTP and grading fixtures validate agent mechanics only; official 22-task data/model campaign has not run"},
            "scope": ["shared generator and official dev validity evaluation",
                      "real OpenEvolve host and governed Framework CLIs",
                      "real local OpenAI-compatible HTTP calls",
                      "Bubblewrap solution execution without inherited credentials",
                      "public train/test visibility and private grading isolation"],
            "checks": CHECKS}
        (ROOT / "verifier/v23/LAST_RUN.json").write_text(json.dumps(report, indent=2) + "\n")
        rc = 0 if passed else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v23/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
