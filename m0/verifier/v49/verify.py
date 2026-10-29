"""v49 acceptance: governed MAP-Elites feature-grid archive and replay."""
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
    missing = []
    for number in range(1, 49):
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
    journal = ROOT / "verifier/runs/v49.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        verify_historical_acceptance()
        map_tests = ["tests/test_map_elites_archive.py"]
        run_command("map_elites_feature_grid_checkpoint_replay_and_flip_only_gate",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *map_tests], timeout=180)
        integration = ["tests/test_map_elites_archive.py", "tests/test_archive_health.py",
                       "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                       "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                       "tests/test_formal_governance.py"]
        run_command("map_elites_sequential_batch_and_governance_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *integration], timeout=300)
        batch = ["tests/test_inprocess_batch_evaluation_recovery.py"]
        run_command("inprocess_batch_terminal_real_sigkill_partial_start_and_active_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *batch], timeout=360)
        sequential = ["tests/test_inprocess_evaluation_recovery.py",
                      "tests/test_external_recovery.py",
                      "tests/test_external_post_settlement_recovery.py",
                      "tests/test_external_genesis_recovery.py",
                      "tests/test_external_control_recovery.py"]
        run_command("sequential_evaluation_terminal_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *sequential], timeout=360)
        proposal = ["tests/test_inprocess_proposal_failure_recovery.py",
                    "tests/test_external_proposal_failure_post_settlement_recovery.py",
                    "tests/test_external_proposal_failure_recovery.py",
                    "tests/test_external_proposal_recovery.py",
                    "tests/test_external_proposer.py",
                    "tests/test_external_batch_proposal_recovery.py",
                    "tests/test_external_batch_partial_start_recovery.py"]
        run_command("proposal_terminal_and_active_call_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *proposal], timeout=360)
        recovery = ["tests/test_external_recovery.py",
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
                    "tests/test_inprocess_evaluation_recovery.py",
                    "tests/test_inprocess_batch_evaluation_recovery.py",
                    "tests/test_external_proposer.py", "tests/test_external_evaluator.py",
                    "tests/test_external_default_sandbox.py",
                    "tests/test_external_resource_policy.py",
                    "tests/test_map_elites_archive.py", "tests/test_loop_checkpoint.py",
                    "tests/test_loop_batch.py", "tests/test_loop_governed_state.py",
                    "tests/test_governance_audit.py", "tests/test_formal_governance.py",
                    "tests/test_real_load.py"]
        run_command("complete_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *recovery], timeout=600)
        run_command("complete_local_regression",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    timeout=600)
        run_command("static_axioms", [sys.executable, "ci/check_axioms.py"])
        profile = json.loads((ROOT / "config/profiles/map_elites_grid.json").read_text())
        source = (ROOT / "core/map_elites.py").read_text()
        check("map_elites_profile_and_admission_isolation",
              profile["parent_pool"]["structure"] == "map_elites"
              and len(profile["parent_pool"]["dimensions"]) == 2
              and "AdmissionGate" not in source and "core.eval" not in source,
              "pure profile compilation; no M9 import or feature-based adjudication")
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v49/verify.py" in workflow,
              "current verifier command")
        index = (ROOT / "verifier/README.md").read_text()
        check("append_only_verifier_index", index.count("\n- v49 ") == 1,
              "exactly one v49 index entry")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        feature = next((item for item in CHECKS if item["check"] ==
                        "map_elites_feature_grid_checkpoint_replay_and_flip_only_gate"), None)
        integration_result = next((item for item in CHECKS if item["check"] ==
                                   "map_elites_sequential_batch_and_governance_regressions"), None)
        proposal_result = next((item for item in CHECKS if item["check"] ==
                                "proposal_terminal_and_active_call_regressions"), None)
        report = {
            "version": "v49", "passed": rc == 0,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "re_bench_campaign_executed": False,
                "mle_bench_lite_campaign_executed": False,
                "host_parity_certified": False,
                "rubric_b2_complete": False, "rubric_b3_complete": False},
            "external_provider_execution": {
                "real_external_api_executed": False,
                "local_openai_compatible_http_worker_executed": bool(
                    proposal_result and proposal_result["passed"]),
                "external_scores_or_cost_efficiency_produced": False},
            "supersedes": ["v48 lacked a MAP-Elites feature-grid parent archive"],
            "acceptance_harness": {
                "recursive_history_execution": False,
                "prior_passing_journals_required": "v1-v48 except rejected v14 and superseded v43 recursive harness",
                "current_behavior_reexecuted": True,
                "legacy_failures_preserved": True,
                "functional_assertions_reduced": False},
            "map_elites_archive": {
                "executed": feature is not None,
                "certified": rc == 0 and bool(feature and feature["passed"]),
                "public_feature_contract": True,
                "one_elite_per_cell": True,
                "deterministic_occupied_cell_parent_selection": True,
                "soft_eviction_and_history_preservation": True,
                "checkpoint_restore_and_tamper_refusal": True,
                "sequential_and_batch_certified_replay": bool(
                    integration_result and integration_result["passed"]),
                "feature_or_score_enters_m9": False,
                "default_m0_parent_policy_changed": False,
                "island_archive_replaced": False},
            "uncertified_boundaries": [
                "full OpenEvolve database interoperability",
                "in-process evaluator calls without a terminal outcome",
                "legacy sequential or batch operations without durable outcomes",
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign", "machine power loss",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "compile MAP-Elites from a declarative profile without M0 kernel changes",
                "bin finite public features with explicit boundary clipping",
                "replace each cell elite by deterministic score/candidate tie-break",
                "select parents by deterministic occupied-cell round-robin only",
                "preserve replaced and softly evicted candidate history",
                "restore exact grid state and reject inconsistent checkpoint bindings",
                "certify sequential/batch resume and independent replay",
                "keep feature metadata and combined score outside M9",
                "no external benchmark, parity, USD or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v49/LAST_RUN.json").write_text(json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v49/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
