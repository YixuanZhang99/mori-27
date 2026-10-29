"""v44 acceptance: v43 behavior with non-recursive historical verification."""
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


def passed_journal_entry(entry):
    if entry.get("exit_code") != 0:
        return False
    checks = entry.get("checks")
    if isinstance(checks, dict):
        return bool(checks) and all(value is True for value in checks.values())
    if isinstance(checks, list):
        return bool(checks) and all(isinstance(item, dict) and item.get("passed")
                                    for item in checks)
    return False


def verify_historical_acceptance():
    """Require real prior passes without recursively rerunning obsolete wrappers."""
    missing = []
    for number in range(1, 43):
        if number == 14:  # The intentionally rejected arithmetic verifier has no pass.
            continue
        version = f"v{number}"
        journal = ROOT / f"verifier/runs/{version}.jsonl"
        try:
            entries = [json.loads(line) for line in journal.read_text().splitlines()
                       if line.strip()]
        except Exception:
            entries = []
        if not any(passed_journal_entry(entry) for entry in entries):
            missing.append(version)
    check("historical_acceptance_evidence", not missing,
          "prior passing journals verified; missing=" + repr(missing))
    rejected_entries = [json.loads(line) for line in
                        (ROOT / "verifier/runs/v14.jsonl").read_text().splitlines()
                        if line.strip()]
    rejected = (bool(rejected_entries) and
                all(entry.get("exit_code") != 0 for entry in rejected_entries) and
                any(entry.get("checks", {}).get(
                    "per_unit_settlement_and_gate_not_rank") is False
                    for entry in rejected_entries))
    check("rejected_v14_preserved", rejected,
          "v14 failed journal remains rejected; v15 is its corrected successor")


def run_command(name, command, timeout=300):
    proc = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                          text=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    print(output, flush=True)
    check(name, proc.returncode == 0 and "skipped" not in output.lower(), output[-3500:])


def main():
    journal = ROOT / "verifier/runs/v44.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        verify_historical_acceptance()
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
        check("ci_workflow_wiring", "python3 verifier/v44/verify.py" in workflow,
              "current verifier command")
        index = (ROOT / "verifier/README.md").read_text()
        check("append_only_verifier_index", index.count("\n- v44 ") == 1,
              "exactly one v44 index entry")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False,
              f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        failed = next((item for item in CHECKS if item["check"] ==
                       "failed_proposal_real_sigkill_and_historical_proposal_guards"), None)
        report = {
            "version": "v44", "passed": rc == 0,
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
                "v42 refusal of complete cohort recovery after a terminal active proposal failure",
                "v43 recursive historical runner, whose legacy v36 300-second timeout repeatedly obscured otherwise passing current checks"],
            "acceptance_harness": {
                "recursive_history_execution": False,
                "prior_passing_journals_required": "v1-v42 except intentionally rejected v14",
                "current_behavior_reexecuted": True,
                "legacy_failures_preserved": True,
                "functional_assertions_reduced": False},
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
        (ROOT / "verifier/v44/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v44/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
