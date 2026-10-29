"""v51 acceptance: native OpenEvolve database and artifact-content migration."""
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
    for number in range(1, 51):
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
    journal = ROOT / "verifier/runs/v51.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        verify_historical_acceptance()
        interop = ["tests/test_openevolve_interop.py", "tests/test_openevolve_artifacts.py"]
        run_command("native_artifact_content_migration_strict_paths_and_flip_isolation",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *interop], timeout=180)
        integration = ["tests/test_openevolve_interop.py", "tests/test_openevolve_artifacts.py",
                       "tests/test_research_frontier.py", "tests/test_map_elites_archive.py",
                       "tests/test_eval_governance.py", "tests/test_archive_health.py",
                       "tests/test_state_mutation.py"]
        run_command("interop_frontier_map_elites_and_governance_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *integration], timeout=300)
        map_integration = ["tests/test_map_elites_archive.py", "tests/test_archive_health.py",
                           "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                           "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                           "tests/test_formal_governance.py"]
        run_command("map_elites_sequential_batch_and_governance_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *map_integration], timeout=300)
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
                    "tests/test_openevolve_interop.py", "tests/test_openevolve_artifacts.py",
                    "tests/test_map_elites_archive.py",
                    "tests/test_loop_checkpoint.py", "tests/test_loop_batch.py",
                    "tests/test_loop_governed_state.py", "tests/test_governance_audit.py",
                    "tests/test_formal_governance.py", "tests/test_real_load.py"]
        run_command("complete_recovery_checkpoint_batch_governance_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *recovery], timeout=600)
        run_command("complete_local_regression",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    timeout=600)
        run_command("static_axioms", [sys.executable, "ci/check_axioms.py"])
        source = (ROOT / "core/openevolve_interop.py").read_text()
        check("real_vendored_database_and_admission_isolation",
              "from openevolve.database import Program, ProgramDatabase" in source
              and "class OpenEvolveArtifactBundle" in source
              and "def write_openevolve_database_with_artifacts" in source
              and "def read_openevolve_database_with_artifacts" in source
              and "AdmissionGate" not in source and "core.eval" not in source
              and "AdmissionDecision" not in source,
              "real host classes and artifact migration; no M9 import or host-metric adjudication")
        workflow = (ROOT / ".github/workflows/axioms.yml").read_text()
        check("ci_workflow_wiring", "python3 verifier/v51/verify.py" in workflow,
              "current verifier command")
        index = (ROOT / "verifier/README.md").read_text()
        check("append_only_verifier_index", index.count("\n- v51 ") == 1,
              "exactly one v51 index entry")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        feature = next((item for item in CHECKS if item["check"] ==
                        "native_artifact_content_migration_strict_paths_and_flip_isolation"), None)
        integration_result = next((item for item in CHECKS if item["check"] ==
                                   "interop_frontier_map_elites_and_governance_regressions"), None)
        proposal_result = next((item for item in CHECKS if item["check"] ==
                                "proposal_terminal_and_active_call_regressions"), None)
        report = {
            "version": "v51", "passed": rc == 0,
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
            "supersedes": ["v50 lacked OpenEvolve external artifact-content migration"],
            "acceptance_harness": {
                "recursive_history_execution": False,
                "prior_passing_journals_required": "v1-v50 except rejected v14 and superseded v43 recursive harness",
                "current_behavior_reexecuted": True,
                "legacy_failures_preserved": True,
                "functional_assertions_reduced": False},
            "openevolve_database_interoperability": {
                "executed": feature is not None,
                "certified": rc == 0 and bool(feature and feature["passed"]),
                "real_vendored_program_and_database": True,
                "program_lineage_metrics_metadata_roundtrip": True,
                "islands_grids_elites_and_feature_stats_roundtrip": True,
                "native_save_load_and_sampling": True,
                "canonical_integrity_envelope": True,
                "strict_disk_preflight_before_native_cleanup": True,
                "single_parent_frontier_export": True,
                "frontier_and_governance_regressions": bool(
                    integration_result and integration_result["passed"]),
                "host_metrics_enter_m9": False,
                "external_artifact_payload_migration": True,
                "artifact_text_binary_empty_and_small_roundtrip": True,
                "artifact_snapshot_hash_and_per_file_sha256": True,
                "artifact_atomic_relocation_and_native_get_artifacts": True,
                "artifact_path_symlink_nested_and_tamper_refusal": True,
                "unreferenced_artifact_directories_migrated": False,
                "multi_parent_exported": False,
                "novelty_llm_or_embedding_state_portable": False},
            "uncertified_boundaries": [
                "multi-parent Frontier export to single-parent OpenEvolve",
                "unreferenced or orphaned OpenEvolve artifact directory migration",
                "novelty LLM and embedding-client portability",
                "in-process evaluator calls without a terminal outcome",
                "legacy sequential or batch operations without durable outcomes",
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign", "machine power loss",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "use the real vendored Program and ProgramDatabase implementations",
                "roundtrip code, single-parent lineage, generation, metrics and metadata",
                "preserve islands, feature grids, archive/best ids and feature scaling state",
                "exercise native save/load and host parent/inspiration sampling",
                "use a canonical schema-versioned SHA256 integrity envelope",
                "reject malformed, duplicate, dangling, inconsistent or unsupported state",
                "validate native disk before OpenEvolve can skip files or clean references",
                "export only complete eligible single-parent Frontier nodes without silent loss",
                "bind every referenced external artifact to the exact database snapshot hash",
                "roundtrip raw text/binary bytes with size and per-file SHA256 validation",
                "atomically migrate database and artifacts while rewriting final directory references",
                "reject symlink, nested, unsafe-path, duplicate, missing-directory and content forks",
                "exercise native get_artifacts after removing the source directories",
                "keep host metrics, feature metadata and artifacts outside M9",
                "no orphan-artifact migration, external benchmark, parity, USD or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v51/LAST_RUN.json").write_text(json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v51/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
