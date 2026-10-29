"""v27 acceptance: one run per evidence history and repeatable honest tracers."""
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


def run_command(name, command, timeout=240):
    proc = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                          text=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "skipped" not in output.lower(), output[-3500:])


def run_example(name, module):
    proc = subprocess.run([sys.executable, "-m", module], cwd=ROOT, env=environment(),
                          capture_output=True, text=True, timeout=120)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "C1/C2 audit = True" in output,
          output[-3500:])


def main():
    journal = ROOT / "verifier/runs/v27.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v26_complete", [sys.executable, "verifier/v26/verify.py"])
        run_command("mixed_run_history_fails_before_spending",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_run_evidence_isolation.py"])
        run_example("toy_gepa_repeatable_first", "examples.toy_gepa")
        run_example("toy_gepa_repeatable_second", "examples.toy_gepa")
        run_example("gsm8k_repeatable_governance", "examples.gsm8k_offline")
        run_example("funsearch_repeatable_governance", "examples.funsearch_offline")
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v27/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        report = {
            "version": "v27", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "scope": ["non-resume runs require a fresh evidence history",
                      "same-instance and fresh-instance reuse fail before new ledger entries",
                      "offline CLI tracers allocate independent evidence directories",
                      "repeated toy, GSM8K and FunSearch tracers report live C1/C2 pass"],
            "checks": CHECKS}
        (ROOT / "verifier/v27/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v27/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
