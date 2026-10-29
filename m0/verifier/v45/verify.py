"""v45 acceptance: terminal proposal failure through batch/control recovery."""
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
    for number in range(1, 45):
        # v14 is intentionally rejected; v43's recursive harness has only preserved
        # timeout/failure records and its functionality is accepted by v44 and here.
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
    journal = ROOT / "verifier/runs/v45.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        verify_historical_acceptance()
        run_command("failed_proposal_post_settlement_real_sigkill_and_adversarial_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
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
        check("ci_workflow_wiring", "python3 verifier/v45/verify.py" in workflow,
              "current verifier command")
        index = (ROOT / "verifier/README.md").read_text()
        check("append_only_verifier_index", index.count("\n- v45 ") == 1,
              "exactly one v45 index entry")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False,
              f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        failed = next((item for item in CHECKS if item["check"] ==
                       "failed_proposal_post_settlement_real_sigkill_and_adversarial_guards"),
                      None)
        report = {
            "version": "v45", "passed": rc == 0,
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
                "v44 refusal to recover a terminal proposal failure once any batch settlement exists"],
            "acceptance_harness": {
                "recursive_history_execution": False,
                "prior_passing_journals_required": "v1-v44 except rejected v14 and superseded v43 recursive harness",
                "current_behavior_reexecuted": True,
                "legacy_failures_preserved": True,
                "functional_assertions_reduced": False},
            "proposal_recovery": {
                "executed": failed is not None,
                "certified": rc == 0 and bool(failed and failed["passed"]),
                "scope": "terminal ExternalCommandLLM failure from proposal through batch finalization and same-cycle control",
                "pre_settlement_crash_windows": ["proposer process started", "failure outcome persisted"],
                "post_settlement_crash_windows": [
                    "ledger settle", "settled evidence", "failed absorb", "successful gate",
                    "failed decision", "failed admission mutation", "failed admission",
                    "successful absorb", "batch completed", "successful admission receipt",
                    "control settle", "control baseline"],
                "provider_request_retried": False,
                "failed_candidate_evaluator_process_created": False,
                "failure_evidence_uses_original_proposer_execution_id": True,
                "settled_failure_evidence_field_comparison": True,
                "original_proposer_request_hash_revalidated": True,
                "ledger_cost_and_reconcile_delta_revalidated": True,
                "non_ok_candidate_pruned_without_m9_receipt": True,
                "post_settlement_failure_gap_certified": bool(failed and failed["passed"]),
                "ordinary_in_process_failure_certified": False,
                "legacy_incomplete_journal_certified": False},
            "uncertified_boundaries": [
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign",
                "ordinary in-process LLM proposal failures",
                "legacy incomplete proposals without operation-boundary evidence",
                "machine power loss and whole-machine worker survival",
                "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "treat durable non-OK proposer outcomes as native settled-intent evidence",
                "do not mistake the failed candidate's absent evaluator process for a missing execution",
                "bind every recovered failure to its original proposer process and request hash",
                "compare reconstructed non-OK evidence and token cost with settled evidence",
                "revalidate settlement account, actual cost and reserve-minus-actual delta",
                "resume the exact checkpoint mutation and admission suffix without provider retry",
                "continue into same-cycle control settlement and baseline recovery",
                "refuse evidence, ledger, mutation, process and missing-outcome forks",
                "match uninterrupted results, ledger, governed state and certified snapshot",
                "completed resume is a no-op and fresh certified replay passes",
                "no external benchmark score, parity, USD efficiency or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v45/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v45/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
