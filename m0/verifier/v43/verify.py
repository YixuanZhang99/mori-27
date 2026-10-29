"""v43 acceptance: pre-settlement cohort recovery with terminal proposal failures."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import traceback

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
    journal = ROOT / "verifier/runs/v43.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v42_complete", [sys.executable, "verifier/v42/verify.py"], timeout=3600)
        run_command("failed_proposal_real_sigkill_and_historical_proposal_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_proposal_failure_recovery.py",
                     "tests/test_external_proposal_recovery.py",
                     "tests/test_external_proposer.py",
                     "tests/test_external_batch_proposal_recovery.py",
                     "tests/test_external_batch_partial_start_recovery.py"], timeout=300)
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
                     "tests/test_external_batch_proposal_recovery.py",
                     "tests/test_external_proposal_recovery.py",
                     "tests/test_external_proposal_failure_recovery.py",
                     "tests/test_external_proposer.py", "tests/test_external_evaluator.py",
                     "tests/test_external_default_sandbox.py",
                     "tests/test_external_resource_policy.py",
                     "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                     "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                     "tests/test_formal_governance.py", "tests/test_real_load.py"], timeout=600)
        run_command("complete_local_regression",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    timeout=600)
        run_command("static_axioms", [sys.executable, "ci/check_axioms.py"])
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v43/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False,
              f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        failed = next((item for item in CHECKS if item["check"] ==
                       "failed_proposal_real_sigkill_and_historical_proposal_guards"), None)
        report = {
            "version": "v43", "passed": rc == 0,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "re_bench_campaign_executed": False,
                "mle_bench_lite_campaign_executed": False,
                "host_parity_certified": False,
                "rubric_b2_complete": False, "rubric_b3_complete": False},
            "external_provider_execution": {
                "real_external_api_executed": False,
                "local_openai_compatible_http_worker_executed": bool(failed and failed["passed"]),
                "external_scores_or_cost_efficiency_produced": False},
            "supersedes": [
                "v42 refusal of complete cohort recovery after a terminal active proposal failure"],
            "proposal_recovery": {
                "executed": failed is not None,
                "certified": rc == 0 and bool(failed and failed["passed"]),
                "scope": "terminal ExternalCommandLLM failure before any cohort settlement",
                "crash_windows": ["proposer process started", "failure outcome persisted"],
                "completion_rule": "ordered prefix of evaluation starts or non-OK proposer outcomes",
                "provider_request_retried": False,
                "failure_outcome_restored_without_llm": True,
                "successful_sibling_proposed_once": True,
                "failed_candidate_evaluator_process_created": False,
                "failure_evidence_uses_original_proposer_execution_id": True,
                "nonprocess_execution_records_are_not_process_journal_entries": True,
                "non_ok_candidate_pruned": True,
                "post_settlement_failure_gap_certified": False,
                "ordinary_in_process_failure_certified": False,
                "legacy_incomplete_journal_certified": False},
            "uncertified_boundaries": [
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign",
                "proposal-failure gaps combined with batch settlement or finalization",
                "ordinary in-process LLM proposal failures",
                "legacy incomplete proposals without operation-boundary evidence",
                "machine power loss and whole-machine worker survival",
                "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "treat successful starts and durable non-OK proposer outcomes as ordered completions",
                "restore an already persisted failure without recalling the LLM",
                "adopt an active failed worker without retry and continue only the missing suffix",
                "bind failure evidence to the original proposer execution and request hash",
                "expose terminal non-process executions explicitly instead of forging process records",
                "require exactly one evaluator process or terminal proposal failure per candidate",
                "settle the mixed failed/successful cohort and prune non-OK evidence",
                "keep process, adoption, new-proposal and failure counts independent",
                "match uninterrupted results, ledger, governed state and certified snapshot",
                "completed resume is a no-op and fresh certified replay passes",
                "no external benchmark score, parity, USD efficiency or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v43/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v43/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
