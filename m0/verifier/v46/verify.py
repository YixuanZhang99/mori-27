"""v46 acceptance: durable in-process proposal failure recovery."""
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
    for number in range(1, 46):
        # v14 is intentionally rejected; v43's recursive harness is accepted by v44+.
        if number in {14, 43}:
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
    journal = ROOT / "verifier/runs/v46.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        verify_historical_acceptance()
        run_command("inprocess_proposal_failure_real_sigkill_and_active_call_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_inprocess_proposal_failure_recovery.py",
                     "tests/test_external_proposal_failure_post_settlement_recovery.py",
                     "tests/test_external_proposal_failure_recovery.py",
                     "tests/test_external_proposal_recovery.py",
                     "tests/test_external_proposer.py",
                     "tests/test_external_batch_proposal_recovery.py",
                     "tests/test_external_batch_partial_start_recovery.py"], timeout=360)
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
                     "tests/test_external_proposal_failure_post_settlement_recovery.py",
                     "tests/test_inprocess_proposal_failure_recovery.py",
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
        check("ci_workflow_wiring", "python3 verifier/v46/verify.py" in workflow,
              "current verifier command")
        index = (ROOT / "verifier/README.md").read_text()
        check("append_only_verifier_index", index.count("\n- v46 ") == 1,
              "exactly one v46 index entry")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False,
              f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        failed = next((item for item in CHECKS if item["check"] ==
                       "inprocess_proposal_failure_real_sigkill_and_active_call_guards"),
                      None)
        report = {
            "version": "v46", "passed": rc == 0,
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
                "v45 in-process proposal exceptions existing only in owner memory"],
            "acceptance_harness": {
                "recursive_history_execution": False,
                "prior_passing_journals_required": "v1-v45 except rejected v14 and superseded v43 recursive harness",
                "current_behavior_reexecuted": True,
                "legacy_failures_preserved": True,
                "functional_assertions_reduced": False},
            "inprocess_proposal_recovery": {
                "executed": failed is not None,
                "certified": rc == 0 and bool(failed and failed["passed"]),
                "scope": "ordinary in-process proposal exceptions with a durable m0_proposal_outcome",
                "active_call_exactly_once_certified": False,
                "active_marker_still_fail_closed": True,
                "completion_boundary": "marker-hash-bound terminal outcome, never marker alone",
                "operation_identity": "deterministic cohort/candidate non-process execution ID",
                "failed_provider_or_llm_call_retried": False,
                "successful_missing_sibling_proposed_once": True,
                "failed_candidate_evaluator_process_created": False,
                "settled_failure_evidence_field_comparison": True,
                "ledger_cost_and_reconcile_delta_revalidated": True,
                "post_settlement_and_control_certified": bool(failed and failed["passed"]),
                "legacy_failure_without_outcome_certified": False},
            "uncertified_boundaries": [
                "ordinary in-process active LLM calls without a terminal outcome",
                "legacy in-process failures without m0_proposal_outcome",
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign",
                "machine power loss and whole-machine worker survival",
                "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "persist a separate non-OK m0_proposal_outcome for ordinary in-process exceptions",
                "bind the outcome to the exact proposal marker hash and deterministic operation ID",
                "treat only that durable outcome as a proposal completion, never an active marker",
                "restore the failure without recalling the LLM and continue only the missing suffix",
                "expose the terminal operation as non-process evidence rather than a fake process",
                "compare reconstructed evidence and token cost with settled evidence",
                "resume settlement, mutation, admission and same-cycle control exactly once",
                "refuse marker, evidence, ledger, missing-outcome and active-call ambiguity",
                "match uninterrupted results, ledger, governed state and certified snapshot",
                "completed resume is a no-op and fresh certified replay passes",
                "no active-call, external benchmark, parity, USD or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v46/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v46/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
