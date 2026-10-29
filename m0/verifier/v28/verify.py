"""v28 acceptance: C3 formal residence and C4 certified replay."""
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
    journal = ROOT / "verifier/runs/v28.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v27_complete", [sys.executable, "verifier/v27/verify.py"])
        run_command("formal_residence_and_certified_replay",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_formal_governance.py"])
        run_command("governance_checkpoint_batch_and_public_api_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_governance_audit.py", "tests/test_loop_checkpoint.py",
                     "tests/test_loop_batch.py", "tests/test_real_load.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v28/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        report = {
            "version": "v28", "passed": rc == 0,
            "external_benchmark_execution": {"executed": False, "scores_produced": False},
            "external_formal_run_certification": {"executed": False, "certified": False},
            "scope": ["formal_pass separately requires resident baseline and actual control spend",
                      "baseline candidates cannot enter the research frontier",
                      "short protocol runs retain independent C1/C2/stop governance status",
                      "certified replay compares normalized snapshot refs and Receipt chain hashes",
                      "stable results and current governance state must match on both arms",
                      "snapshot normalization excludes only resume controls and diagnostic node wall time",
                      "replay mismatch appends a failed certificate and raises",
                      "certified replay refuses runs without integrity-checked checkpoints"],
            "checks": CHECKS}
        (ROOT / "verifier/v28/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v28/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
