"""v26 acceptance: live C1/C2 reconciliation, not external-run certification."""
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
    journal = ROOT / "verifier/runs/v26.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v25_complete", [sys.executable, "verifier/v25/verify.py"])
        run_tests("c1_c2_reconciliation_and_tamper_refusal",
                  ["tests/test_governance_audit.py"])
        run_tests("governance_checkpoint_replay_and_loop_regression",
                  ["tests/test_axioms.py", "tests/test_real_load.py",
                   "tests/test_loop_batch.py", "tests/test_loop_checkpoint.py",
                   "tests/test_loop_governed_state.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v26/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        report = {
            "version": "v26", "passed": rc == 0,
            "certification_scope": {
                "local_controlled_runs": True, "external_formal_runs": False,
                "reason": "offline runs verify reconciliation and tamper refusal; no hosted CI or external benchmark governance certification is claimed"},
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False},
            "scope": ["every settlement mapped through a matching reserve and intent lifecycle",
                      "seven-account settled totals exactly reconcile with the ledger summary",
                      "reconcile deltas match original reserve minus actual settlement",
                      "every gate decision binds one Receipt and one admission decision",
                      "table-driven stops replay through StopActionTable",
                      "post-run orphan or conflicting evidence makes inspect fail"],
            "checks": CHECKS}
        (ROOT / "verifier/v26/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v26/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
