"""v22 acceptance: real MLE-Bench campaign mechanics, not benchmark performance."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CHECKS = []


def check(name, passed, detail):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": str(detail)})
    print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}", flush=True)


def run_tests(name, nodes):
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "-rs", *nodes], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=90)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "skipped" not in output.lower(), output[-3500:])


def main():
    journal = ROOT / "verifier/runs/v22.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        history_path = ROOT / "verifier/runs/v21.jsonl"
        history = history_path.read_text().strip().splitlines() if history_path.exists() else []
        prior = json.loads(history[-1]) if history else {}
        check("v21_complete", prior.get("exit_code") == 0, prior.get("exit_code"))
        run_tests("campaign_process_and_evidence_contracts", ["tests/test_benchmark_runner.py"])
        run_tests("adapter_and_comparison_regression", ["tests/test_benchmark_adapters.py"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
            proc = subprocess.run([sys.executable, "-m", "zoo.mle_bench_lite.runner",
                "--official-root", str(root / "missing-official"),
                "--data-root", str(root / "missing-data"), "--preflight-only"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = {}
            check("real_cli_preflight_fails_closed", proc.returncode == 2
                  and payload.get("comparison_complete") is False
                  and not (root / "campaign.json").exists(),
                  {"exit_code": proc.returncode, "stdout": proc.stdout[-1000:]})
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v22/verify.py" in workflow,
              "current verifier command")
        passed = all(item["passed"] for item in CHECKS)
        report = {"version": "v22", "passed": passed,
                  "external_benchmark_execution": {"executed": False, "scores_produced": False,
                      "reason": "official package, prepared data and model runs are unavailable"},
                  "scope": ["production paired-arm CLI", "all-task preflight",
                            "real process-group timeout", "official-report-only measured records",
                            "strict 22-task/3-seed comparison"],
                  "checks": CHECKS}
        (ROOT / "verifier/v22/LAST_RUN.json").write_text(json.dumps(report, indent=2))
        rc = 0 if passed else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        journal.open("a").write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v22/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
