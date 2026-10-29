"""v20 acceptance: real Bubblewrap isolation and process recovery.

Not a seccomp, resource-limit, power-loss, or hostile-kernel certification.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHECKS = []


def check(name, value, detail):
    CHECKS.append({"check": name, "passed": bool(value), "detail": str(detail)})
    print(f"{'PASS' if value else 'FAIL'} {name}: {detail}", flush=True)


def run_test(nodeid, timeout=45):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "-rs", nodeid], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=timeout)
    output = (result.stdout + result.stderr).strip()
    print(output, flush=True)
    return result.returncode == 0 and "skipped" not in output.lower(), output[-3000:]


def main():
    journal = ROOT / "verifier/runs/v20.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        available = shutil.which("bwrap") is not None
        check("bubblewrap_installed", available, shutil.which("bwrap"))
        if not available:
            raise RuntimeError("real bwrap is mandatory; skipped tests are not acceptance")
        history = (ROOT / "verifier/runs/v19.jsonl").read_text().strip().splitlines()
        v19 = json.loads(history[-1]) if history else {}
        check("v19_complete", v19.get("exit_code") == 0, v19.get("exit_code"))
        cases = [
            ("real_isolation_probes", "test_real_sandbox_blocks_host_env_files_network_and_writes"),
            ("sandbox_timeout", "test_sandbox_timeout_remains_structured"),
            ("sandbox_owner_crash", "test_real_sandbox_owner_crash_recovers_without_reexecution"),
        ]
        for name, test in cases:
            ok, output = run_test(f"tests/test_sandbox_executor.py::{test}")
            check(name, ok, output)
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        regression = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "tests/test_settlement_crash_recovery.py", "tests/test_batch_execution_recovery.py",
            "tests/test_executor_recovery.py"], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=90)
        output = (regression.stdout + regression.stderr).strip()
        print(output, flush=True)
        check("settlement_batch_process_recovery_regression", regression.returncode == 0, output[-3000:])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "verifier/v20/verify.py" in workflow and
              "bubblewrap" in workflow, "v20 + bubblewrap")
        passed = all(item["passed"] for item in CHECKS)
        report = {"version": "v20", "passed": passed,
                  "scope": ["private filesystem and writable candidate worktree",
                            "read-only system, protected paths and data_dir",
                            "cleared host environment and explicit non-sensitive AR variables",
                            "network namespace isolation", "timeout and owner-crash recovery"],
                  "exclusions": ["seccomp", "complete resource limits", "power-loss certification",
                                 "external benchmark"], "checks": CHECKS}
        (ROOT / "verifier/v20/LAST_RUN.json").write_text(json.dumps(report, indent=2))
        rc = 0 if passed else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        journal.open("a").write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v20/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
