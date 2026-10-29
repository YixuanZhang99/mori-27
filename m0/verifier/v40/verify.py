"""v40 acceptance: pinned RE-Bench numeric-score adapter and paired campaign mechanics."""
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
    journal = ROOT / "verifier/runs/v40.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v39_complete", [sys.executable, "verifier/v39/verify.py"], timeout=1500)
        run_command("re_bench_protocol_real_processes_and_numeric_comparison",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_re_bench.py", "tests/test_benchmark_adapters.py",
                     "tests/test_benchmark_runner.py", "tests/test_benchmark_agents.py"])
        run_command("external_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_recovery.py",
                     "tests/test_external_post_settlement_recovery.py",
                     "tests/test_external_genesis_recovery.py",
                     "tests/test_external_control_recovery.py",
                     "tests/test_external_batch_recovery.py",
                     "tests/test_external_batch_post_settlement_recovery.py",
                     "tests/test_external_batch_control_recovery.py",
                     "tests/test_external_batch_partial_start_recovery.py",
                     "tests/test_external_evaluator.py",
                     "tests/test_external_default_sandbox.py",
                     "tests/test_external_resource_policy.py",
                     "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                     "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                     "tests/test_formal_governance.py", "tests/test_real_load.py"], timeout=600)
        run_command("detached_settlement_process_and_sandbox_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_settlement_crash_recovery.py",
                     "tests/test_batch_execution_recovery.py",
                     "tests/test_executor_recovery.py", "tests/test_sandbox_executor.py"])
        run_command("complete_local_regression",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    timeout=600)
        run_command("static_axioms", [sys.executable, "ci/check_axioms.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v40/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, repr(error))
        rc = 2
    finally:
        mechanism = next((item for item in CHECKS if item["check"] ==
                          "re_bench_protocol_real_processes_and_numeric_comparison"), None)
        report = {
            "version": "v40", "passed": rc == 0,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "re_bench_campaign_executed": False, "host_parity_certified": False,
                "rubric_b3_complete": False},
            "supersedes": ["v39 absence of a numeric-score time-budget benchmark adapter"],
            "re_bench_adapter": {
                "executed": mechanism is not None,
                "certified": rc == 0 and bool(mechanism and mechanism["passed"]),
                "protocol_fixtures_only": True,
                "official_revision": "a0cc6d4a91b20f84ebef505d5c72358f88b3b389",
                "task_list_sha256": "0f6205a46c61a26e7476e498a4199b7d2a3ee4abf53c27dbb7f3640ddcd008ff",
                "task_count": 7, "locked_file_count": 36,
                "minimum_paired_seeds": 3,
                "official_scoring_entry": "TaskFamily.aggregate_scores",
                "timeout_rule": "existing score log plus official score_on_usage_limits=true",
                "comparison_rule": "complete seven-task host/governed matrix only"},
            "previously_certified_windows": [
                "default Bubblewrap and explicit audited disable",
                "optional RLIMIT_AS/RLIMIT_FSIZE/RLIMIT_NPROC policy and replay",
                "sequential external genesis, improve and same-cycle control",
                "prepared external cohorts from zero/partial starts through finalization",
                "completed external batch plus same-cycle control before checkpoint"],
            "uncertified_boundaries": [
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "incomplete proposal journals",
                "missing processes combined with settlement or finalization evidence",
                "machine power loss", "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "pinned deprecated METR RE-Bench suite and 36 protected file hashes",
                "workspace exposes description and provenance only, never solutions or score logs",
                "official TaskFamily.aggregate_scores consumes real Vivaria object-list logs",
                "raw score log and numeric aggregate stay in run-level audit evidence",
                "generic measured ScoreRunRecord supports maximize and minimize directions",
                "strict paired comparison requires identical task and seed sets, backbone and budgets",
                "real agent process groups enforce timeout and kill child processes",
                "timeout scoring requires official per-task usage-limit permission",
                "missing logs, invalid scores and partial matrices produce no comparison",
                "production preflight requires viv and metr.task_protected_scoring",
                "inherited credentials are not serialized",
                "no external RE-Bench score, parity, USD efficiency or B3 completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v40/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v40/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
