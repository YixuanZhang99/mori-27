"""v65 acceptance: S6 periodic anchor and proxy-validity feedback with preserved S1-S5/M0 regressions."""
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
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT),
               PYTEST_ADDOPTS="--strict-markers --fail-on-skip")
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
    for number in range(1, 65):
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
    journal = ROOT / "verifier/runs/v65.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        verify_historical_acceptance()
        run_command("periodic_anchor_proxy_validity_and_memory_feedback_end_to_end",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_proxy_validity.py",
                     "tests/test_composed_proxy.py"], timeout=240)
        run_command("hierarchical_physical_budget_and_fidelity_end_to_end",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_hierarchical_budget.py",
                     "tests/test_composed_budget.py"], timeout=240)
        run_command("composed_research_offline_example",
                    [sys.executable, "examples/composed_research_offline.py"], timeout=240)
        run_command("layered_admission_and_isolated_final_audit_end_to_end",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_layered_admission.py",
                     "tests/test_composed_admission.py"], timeout=240)
        run_command("scoped_context_and_local_knowledge_feedback_end_to_end",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_composed_context.py",
                     "tests/test_composition_context.py",
                     "tests/test_composition_knowledge.py"], timeout=240)
        run_command("canonical_evaluation_contract_and_composed_execution_end_to_end",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_evaluation_contract.py",
                     "tests/test_composed_evaluation.py"], timeout=240)
        run_command("composition_registry_defaults_and_runtime_end_to_end",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_composition_registry.py",
                     "tests/test_composition_defaults.py",
                     "tests/test_composed_runtime.py"], timeout=240)
        run_command("dataset_content_binding_and_evaluation_context_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_evaluation_context.py"], timeout=180)
        run_command("process_identity_writer_reader_and_real_recovery_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_process_identity_writer.py"], timeout=180)
        run_command("upfront_config_validation_and_isolated_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_loop_config_validation.py",
                     "tests/test_replay_isolation.py"], timeout=180)
        run_command("decision_receipt_identity_context_and_audit_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_receipt_identity.py"], timeout=180)
        run_command("admission_sample_identity_comparability_and_schema_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_admission_validation.py",
                     "tests/test_admission_boundaries.py"], timeout=180)
        run_command("physical_usage_failure_zero_and_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_cost_integrity.py",
                     "tests/test_governed_usage.py",
                     "tests/test_external_usage_integrity.py"], timeout=180)
        run_command("budget_finite_cost_reserve_identity_and_atomic_replay_regressions",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_budget_integrity.py"], timeout=180)
        seccomp = ["tests/test_seccomp_abi.py", "tests/test_seccomp_policy.py",
                   "tests/test_process_policy_recovery.py", "tests/test_external_default_sandbox.py",
                   "tests/test_external_resource_policy.py", "tests/test_sandbox_executor.py",
                   "tests/test_benchmark_agents.py"]
        run_command("real_seccomp_eperm_memfd_direct_popen_and_both_executors",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *seccomp], timeout=240)
        proposer_seccomp = ["tests/test_proposer_seccomp.py", "tests/test_external_proposer.py",
                            "tests/test_external_proposal_recovery.py"]
        run_command("direct_prctl_proposer_eperm_http_credentials_fork_and_owner_recovery",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *proposer_seccomp], timeout=240)
        benchmark = ["tests/test_benchmark_selection_receipt.py",
                     "tests/test_benchmark_selection_contract.py",
                     "tests/test_benchmark_adapters.py", "tests/test_benchmark_runner.py",
                     "tests/test_benchmark_agents.py", "tests/test_re_bench.py"]
        run_command("selection_contract_cost_coverage_and_campaign_mechanics",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *benchmark], timeout=180)
        interop = ["tests/test_openevolve_embedding_portability.py",
                   "tests/test_openevolve_interop.py", "tests/test_openevolve_artifacts.py",
                   "tests/test_openevolve_frontier_recovery.py"]
        run_command("multi_parent_lineage_native_roundtrip_artifacts_and_flip_isolation",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *interop], timeout=180)
        integration = ["tests/test_openevolve_interop.py", "tests/test_openevolve_artifacts.py",
                       "tests/test_openevolve_frontier_recovery.py",
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
        recovery = ["tests/test_proposer_seccomp.py", "tests/test_seccomp_policy.py",
                    "tests/test_process_policy_recovery.py",
                    "tests/test_sandbox_executor.py",
                    "tests/test_executor_recovery.py", "tests/test_external_recovery.py",
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
                    "tests/test_openevolve_frontier_recovery.py",
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
        benchmark_source = (ROOT / "core/tasks/benchmark.py").read_text()
        re_runner = (ROOT / "zoo/re_bench/runner.py").read_text()
        mle_runner = (ROOT / "zoo/mle_bench_lite/runner.py").read_text()
        check("strict_benchmark_contract_wiring_and_m9_isolation",
              "class SelectionContract" in benchmark_source
              and "class SelectionCandidate" in benchmark_source
              and "class SelectionReceipt" in benchmark_source
              and "def validate_and_replay" in benchmark_source
              and "selection_receipt_sha256" in benchmark_source
              and "def _validate_matrix_contracts" in benchmark_source
              and "actual_costs[unit]" in benchmark_source
              and "required_cost_units" in benchmark_source
              and 'required_cost_units={"wallclock"}' in re_runner
              and "required_cost_units=set(budget)" in mle_runner
              and "AdmissionGate" not in benchmark_source
              and "core.eval" not in benchmark_source
              and "admitted_per_usd" not in benchmark_source,
              "both campaign runners require declared physical costs; comparison has no M9 or USD-efficiency adjudication")
        source = (ROOT / "core/openevolve_interop.py").read_text()
        check("embedding_state_portability_and_live_novelty_llm_isolation",
              '"embedding_model", "embedding_api_base"' in source
              and "live novelty LLM objects are not portable" in source
              and "one consistent dimension" in source
              and "without credentials, query or fragment" in source
              and "AdmissionGate" not in source and "core.eval" not in source,
              "embedding config/vectors roundtrip; live judge objects and M9 remain outside snapshots")
        check("real_vendored_database_and_admission_isolation",
              "from openevolve.database import Program, ProgramDatabase" in source
              and "class OpenEvolveArtifactBundle" in source
              and "def write_openevolve_database_with_artifacts" in source
              and "def read_openevolve_database_with_artifacts" in source
              and "def frontier_from_openevolve" in source
              and '"frontier_additional_parent_ids"' in source
              and '"frontier_checkpoint_sha256"' in source
              and "AdmissionGate" not in source and "core.eval" not in source
              and "AdmissionDecision" not in source,
              "real host classes, lossless DAG recovery and no M9 import/adjudication")
        seccomp_source = (ROOT / "core/executor/seccomp.py").read_text()
        sandbox_source = (ROOT / "core/executor/sandbox.py").read_text()
        wrapper_source = (ROOT / "core/executor/process_wrapper.py").read_text()
        agent_source = (ROOT / "zoo/mle_bench_lite/agent_common.py").read_text()
        check("versioned_seccomp_policy_and_shared_memfd_wiring",
              "SECCOMP_POLICY_VERSION = 2" in seccomp_source
              and '"ptrace": 101' in seccomp_source
              and "_SECCOMP_RET_ERRNO_EPERM" in seccomp_source
              and "_SECCOMP_RET_KILL_PROCESS" in seccomp_source
              and "_X32_SYSCALL_BIT = 0x40000000" in seccomp_source
              and "_X32_LEGACY_SYSCALL_RANGE = (512, 547)" in seccomp_source
              and "_BPF_JMP_JSET_K" in seccomp_source
              and "_BPF_JMP_JGE_K" in seccomp_source
              and "def materialize_seccomp" in seccomp_source
              and "def seccomp_arguments" in seccomp_source
              and "payload != expected" in seccomp_source
              and "SECCOMP_FD_PLACEHOLDER" in sandbox_source
              and "pass_fds" in wrapper_source and "pass_fds" in agent_source
              and "seccomp_arguments" in agent_source
              and "AdmissionGate" not in seccomp_source
              and "core.eval" not in seccomp_source,
              "canonical arch/x32-guarded v2 EPERM denylist; detached and direct Popen share memfd lifecycle; no M9 coupling")
        process_source = (ROOT / "core/executor/process.py").read_text()
        proposal_source = (ROOT / "core/executor/proposal.py").read_text()
        check("direct_prctl_proposer_policy_wiring_and_m9_isolation",
              "SECCOMP_DIRECT_PRCTL = \"direct_prctl\"" in seccomp_source
              and "def direct_seccomp_preexec" in seccomp_source
              and "def validate_seccomp_delivery" in seccomp_source
              and "38, 1" in seccomp_source and "22, 2" in seccomp_source
              and '"seccomp_delivery": seccomp_delivery' in process_source
              and "validate_seccomp_delivery(seccomp_policy, seccomp_delivery)" in process_source
              and "def _apply_target_policy" in wrapper_source
              and "seccomp_installer()" in wrapper_source
              and 'delivery == "direct_prctl"' in wrapper_source
              and "seccomp: bool = True" in proposal_source
              and "build_seccomp_policy() if seccomp else None" in proposal_source
              and "seccomp=self.seccomp" in proposal_source
              and "seccomp_delivery=SECCOMP_DIRECT_PRCTL if self.seccomp else None" in proposal_source
              and "dict(os.environ)" in proposal_source
              and "AdmissionGate" not in proposal_source
              and "core.eval" not in proposal_source,
              "direct NO_NEW_PRIVS/SECCOMP installation, durable delivery, default proposer wiring, fork inheritance and no M9 coupling")
        workflow = (ROOT.parent / ".github/workflows/ci.yml").read_text()
        makefile = (ROOT.parent / "Makefile").read_text()
        runner = (ROOT.parent / "scripts/run_acceptance.py").read_text()
        check("ci_workflow_wiring",
              "make accept-linux" in workflow and "make tooling" in workflow
              and "python scripts/run_acceptance.py" in makefile
              and 'VERIFIER_VERSION = "v65"' in runner
              and "--strict-markers --fail-on-skip" in runner,
              "active root CI runs isolated v65 with no skipped tests")
        index = (ROOT / "verifier/README.md").read_text()
        check("append_only_verifier_index", index.count("\n- v65 ") == 1,
              "exactly one v65 index entry")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False, f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        seccomp_feature = next((item for item in CHECKS if item["check"] ==
                                "real_seccomp_eperm_memfd_direct_popen_and_both_executors"), None)
        proposer_feature = next((item for item in CHECKS if item["check"] ==
                                 "direct_prctl_proposer_eperm_http_credentials_fork_and_owner_recovery"), None)
        proposer_wiring = next((item for item in CHECKS if item["check"] ==
                                "direct_prctl_proposer_policy_wiring_and_m9_isolation"), None)
        selection_feature = next((item for item in CHECKS if item["check"] ==
                                  "selection_contract_cost_coverage_and_campaign_mechanics"), None)
        feature = next((item for item in CHECKS if item["check"] ==
                        "multi_parent_lineage_native_roundtrip_artifacts_and_flip_isolation"), None)
        integration_result = next((item for item in CHECKS if item["check"] ==
                                   "interop_frontier_map_elites_and_governance_regressions"), None)
        proposal_result = next((item for item in CHECKS if item["check"] ==
                                "proposal_terminal_and_active_call_regressions"), None)
        repair_checks = [item for item in CHECKS if item["check"] in {
            "admission_sample_identity_comparability_and_schema_regressions",
            "physical_usage_failure_zero_and_replay_regressions",
            "budget_finite_cost_reserve_identity_and_atomic_replay_regressions"}]
        identity_checks = [item for item in CHECKS if item["check"] in {
            "dataset_content_binding_and_evaluation_context_regressions",
            "process_identity_writer_reader_and_real_recovery_regressions",
            "upfront_config_validation_and_isolated_replay_regressions",
            "decision_receipt_identity_context_and_audit_regressions"}]
        composition_feature = next((item for item in CHECKS if item["check"] ==
                                    "composition_registry_defaults_and_runtime_end_to_end"), None)
        evaluation_feature = next((item for item in CHECKS if item["check"] ==
                                   "canonical_evaluation_contract_and_composed_execution_end_to_end"), None)
        context_feature = next((item for item in CHECKS if item["check"] ==
                                "scoped_context_and_local_knowledge_feedback_end_to_end"), None)
        admission_feature = next((item for item in CHECKS if item["check"] ==
                                  "layered_admission_and_isolated_final_audit_end_to_end"), None)
        budget_feature = next((item for item in CHECKS if item["check"] ==
                               "hierarchical_physical_budget_and_fidelity_end_to_end"), None)
        research_example = next((item for item in CHECKS if item["check"] ==
                                 "composed_research_offline_example"), None)
        proxy_feature = next((item for item in CHECKS if item["check"] ==
                              "periodic_anchor_proxy_validity_and_memory_feedback_end_to_end"), None)
        report = {
            "version": "v65", "passed": rc == 0,
            "composition_stage_evidence": {
                "stage": "S1",
                "certified": rc == 0 and bool(composition_feature
                                                and composition_feature["passed"]),
                "executed_group": (composition_feature["check"]
                                   if composition_feature else None),
                "scope": ["registered module composition",
                          "validated default module adapters",
                          "configured Framework runtime end-to-end execution"],
                "unified_evaluation_contract_complete": False,
                "memory_knowledge_feedback_complete": False,
                "three_layer_admission_complete": False,
                "hierarchical_budget_complete": False},
            "evaluation_contract_stage_evidence": {
                "stage": "S2",
                "certified": rc == 0 and bool(evaluation_feature
                                                and evaluation_feature["passed"]),
                "executed_group": (evaluation_feature["check"]
                                   if evaluation_feature else None),
                "scope": ["strict canonical evaluation transport in the configured runtime",
                          "candidate artifact and evaluation-context identity binding",
                          "explicit cost and failure evidence through legacy adapters",
                          "public search projections and restricted admission comparison views",
                          "configured checkpoint and replay preserve evaluation evidence"],
                "legacy_m0_interface_retained": True,
                "memory_knowledge_feedback_complete": False,
                "three_layer_admission_complete": False,
                "hierarchical_budget_complete": False},
            "context_feedback_stage_evidence": {
                "stage": "S3",
                "certified": rc == 0 and bool(context_feature and context_feature["passed"]),
                "executed_group": (context_feature["check"] if context_feature else None),
                "scope": ["scoped memory ContextPack reaches configured candidate generation",
                          "local knowledge opens source content with separate ground and audit lanes",
                          "benchmark rejects knowledge injection before side effects",
                          "logical run identity and context state survive checkpoint and replay"],
                "external_network_knowledge_executed": False,
                "three_layer_admission_complete": False,
                "hierarchical_budget_complete": False},
            "layered_admission_stage_evidence": {
                "stage": "S4",
                "certified": rc == 0 and bool(admission_feature and admission_feature["passed"]),
                "executed_group": (admission_feature["check"] if admission_feature else None),
                "scope": ["explicit native-domain dev admission and final-audit identities",
                          "independent admission call caps and per-evaluation token reservations",
                          "deterministic comparable-evidence receipts and frozen final selection",
                          "final-audit evidence remains outside search and memory feedback"],
                "legacy_dev_only_profile_retained": True,
                "top_k_selection_complete": False,
                "hitl_integration_complete": False,
                "hierarchical_budget_complete": False},
            "hierarchical_budget_stage_evidence": {
                "stage": "S5",
                "certified": rc == 0 and bool(budget_feature and budget_feature["passed"]
                                               and research_example and research_example["passed"]),
                "executed_group": budget_feature["check"] if budget_feature else None,
                "offline_example": research_example["check"] if research_example else None,
                "scope": ["global, direction and candidate physical budget accounting and atomic reservations",
                          "actual evaluation requests and comparable fidelity baselines",
                          "budget views reach configured proposal inputs",
                          "predeclared low-sample stopping rules and recoverable state"],
                "external_gpu_execution_certified": False,
                "external_provider_campaign_executed": False,
                "external_benchmark_campaign_executed": False,
            },
            "proxy_validity_stage_evidence": {
                "stage": "S6",
                "certified": rc == 0 and bool(proxy_feature and proxy_feature["passed"]),
                "executed_group": proxy_feature["check"] if proxy_feature else None,
                "scope": ["periodic paid calibration anchors with explicit comparable evidence identities",
                          "rank-correlation validity rules with minimum-sample reporting",
                          "proxy failure feedback enters source-bound scoped memory",
                          "anchor and validity state participate in restore and replay"],
                "statistical_guarantee_claimed": False,
                "external_benchmark_campaign_executed": False,
                "worktree_composition_complete": False,
                "population_composition_complete": False,
            },
            "identity_and_replay_repair_evidence": {
                "executed_groups": [item["check"] for item in identity_checks],
                "certified": rc == 0 and len(identity_checks) == 4
                             and all(item["passed"] for item in identity_checks),
                "scope": ["dataset content digests bind evaluation contexts",
                          "shared process identity reader and detached target writer",
                          "reject invalid configuration before side effects",
                          "decision receipts bind complete evidence and decision context",
                          "isolated deterministic replay without original run mutation"],
                "linux_process_identity_execution": bool(rc == 0 and any(
                    item["check"] == "process_identity_writer_reader_and_real_recovery_regressions"
                    and item["passed"] for item in identity_checks))},
            "integrity_repair_evidence": {
                "executed_groups": [item["check"] for item in repair_checks],
                "certified": rc == 0 and len(repair_checks) == 3
                             and all(item["passed"] for item in repair_checks),
                "scope": ["typed unique comparable admission samples",
                          "physical usage includes zero and fails closed when malformed",
                          "nonnegative finite budget costs and immutable reservation identity",
                          "atomic ledger restoration and idempotent settlement"]},
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
            "supersedes": [
                "v58 dataset identity did not bind complete task content",
                "v58 detached process writer did not share the robust stat reader",
                "v58 config, receipts and replay needed complete boundary validation",
                "v57 seccomp v1 left x32 and legacy x32 syscall encodings unguarded",
                "v57 admission, usage and budget evidence needed strict boundary validation"],
            "acceptance_harness": {
                "recursive_history_execution": False,
                "prior_passing_journals_required": "v1-v64 except rejected v14 and superseded v43 recursive harness",
                "current_behavior_reexecuted": True,
                "legacy_failures_preserved": True,
                "functional_assertions_reduced": False},
            "seccomp_execution_evidence": {
                "executed": seccomp_feature is not None,
                "certified": rc == 0 and bool(seccomp_feature and seccomp_feature["passed"]),
                "architecture": "x86_64",
                "policy": "explicit-versioned-dangerous-syscall-denylist-v2",
                "x32_bit_and_legacy_range_rejected_on_both_delivery_paths": bool(
                    seccomp_feature and seccomp_feature["passed"]),
                "portable_bpf_boundary_and_audit_architecture_semantics": bool(
                    seccomp_feature and seccomp_feature["passed"]),
                "stale_or_relabelled_v1_specs_rejected_before_new_launch": bool(
                    seccomp_feature and seccomp_feature["passed"]),
                "unfinished_stale_policy_recovery_blocked_without_relaunch": bool(
                    seccomp_feature and seccomp_feature["passed"]),
                "real_ptrace_returned_eperm": bool(seccomp_feature and seccomp_feature["passed"]),
                "ordinary_python_and_mle_host_governed_cli_executed": bool(seccomp_feature and seccomp_feature["passed"]),
                "external_evaluator_and_git_worktree_executor_covered": bool(seccomp_feature and seccomp_feature["passed"]),
                "detached_wrapper_and_direct_popen_share_memfd_lifecycle": bool(seccomp_feature and seccomp_feature["passed"]),
                "canonical_filter_and_sha256_in_durable_spec": bool(seccomp_feature and seccomp_feature["passed"]),
                "journal_contains_public_policy_summary_without_filter_bytes": bool(seccomp_feature and seccomp_feature["passed"]),
                "rehashed_semantic_tamper_rejected_before_target_start": bool(seccomp_feature and seccomp_feature["passed"]),
                "fork_and_owner_crash_recovery_preserve_policy_without_reexecution": bool(seccomp_feature and seccomp_feature["passed"]),
                "explicit_seccomp_disable_remains_audited": bool(seccomp_feature and seccomp_feature["passed"]),
                "complete_syscall_allowlist": False,
                "non_x86_64_seccomp_certified": False,
                "external_command_proposer_seccomp_protected": bool(
                    proposer_feature and proposer_feature["passed"]),
                "external_command_proposer_sandboxed": False,
                "cgroup_or_complete_resource_limits": False,
                "hostile_kernel_boundary": False,
                "environment_or_credentials_persisted": False},
            "proposer_seccomp_execution_evidence": {
                "executed": proposer_feature is not None,
                "certified": rc == 0 and bool(proposer_feature and proposer_feature["passed"])
                             and bool(proposer_wiring and proposer_wiring["passed"]),
                "architecture": "x86_64",
                "delivery": "direct_prctl",
                "default_enabled_for_external_command_llm": bool(proposer_feature and proposer_feature["passed"]),
                "real_ptrace_returned_eperm": bool(proposer_feature and proposer_feature["passed"]),
                "no_new_privs_and_seccomp_filter_status_observed": bool(proposer_feature and proposer_feature["passed"]),
                "local_openai_http_network_and_authorization_inherited": bool(proposer_feature and proposer_feature["passed"]),
                "environment_or_credentials_persisted": False,
                "direct_delivery_in_durable_spec_and_public_journal": bool(proposer_feature and proposer_feature["passed"]),
                "rehashed_semantic_tamper_rejected_before_target_start": bool(proposer_feature and proposer_feature["passed"]),
                "invalid_delivery_rejected_before_process_launch": bool(proposer_feature and proposer_feature["passed"]),
                "fork_and_owner_crash_recovery_preserve_policy_without_provider_retry": bool(proposer_feature and proposer_feature["passed"]),
                "explicit_seccomp_disable_remains_audited": bool(proposer_feature and proposer_feature["passed"]),
                "bubblewrap_filesystem_or_network_isolation": False,
                "credential_isolation": False,
                "fallback_or_arbitrary_inprocess_calls_seccomp_protected": False,
                "complete_syscall_allowlist_or_hostile_kernel_boundary": False},
            "benchmark_evidence_contract": {
                "executed": selection_feature is not None,
                "certified": rc == 0 and bool(selection_feature and selection_feature["passed"]),
                "explicit_selection_object_policy_and_split": True,
                "single_run_archive_best_and_best_single_chain_distinguished": True,
                "identical_selection_contract_required_across_matrix": True,
                "declared_units_require_actual_measurements": True,
                "matrix_declared_and_actual_unit_sets_must_match": True,
                "required_physical_cost_dimensions_enforced": True,
                "missing_cost_treated_as_zero": False,
                "selection_or_cost_fields_enter_m9": False,
                "external_benchmark_scores_produced": False,
                "usd_or_admitted_per_usd_conclusion_produced": False},
            "selection_replay_evidence": {
                "executed": selection_feature is not None,
                "certified": rc == 0 and bool(selection_feature and selection_feature["passed"]),
                "candidate_pool_and_evidence_refs_bound": True,
                "receipt_sha256_binds_contract_pool_and_choice": True,
                "archive_best_validation_max_deterministic_tie_break": True,
                "best_single_chain_exactly_one_terminal_per_chain": True,
                "single_run_exactly_one_candidate": True,
                "official_test_score_enters_selection": False,
                "rehashed_semantic_tamper_accepted": False,
                "comparison_reports_every_receipt_digest": True,
                "external_benchmark_scores_produced": False},
            "embedding_state_portability": {
                "executed": feature is not None,
                "certified": rc == 0 and bool(feature and feature["passed"]),
                "model_and_credential_free_api_base_roundtrip": True,
                "finite_nonempty_consistent_dimension_vectors": True,
                "native_save_load_and_strict_disk_reread": True,
                "restored_vectors_drive_native_cosine_and_novelty_offline": True,
                "live_novelty_llm_object_serialized": False,
                "future_external_embedding_responses_reproduced_offline": False,
                "embedding_or_novelty_enters_m9": False},
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
                "multi_parent_exported": True,
                "first_declared_parent_is_native_primary": True,
                "additional_parents_preserved_in_governance_metadata": True,
                "frontier_checkpoint_exact_reverse_recovery": True,
                "native_save_load_then_frontier_checkpoint_equivalence": True,
                "topology_metadata_and_rehashed_tamper_refusal": True,
                "host_cell_displaced_programs_retained_without_fake_membership": True,
                "native_multi_parent_credit_propagation": False,
                "frontier_and_governance_regressions": bool(
                    integration_result and integration_result["passed"]),
                "host_metrics_enter_m9": False,
                "external_artifact_payload_migration": True,
                "artifact_text_binary_empty_and_small_roundtrip": True,
                "artifact_snapshot_hash_and_per_file_sha256": True,
                "artifact_atomic_relocation_and_native_get_artifacts": True,
                "artifact_path_symlink_nested_and_tamper_refusal": True,
                "unreferenced_artifact_directories_migrated": False,
                "novelty_llm_state_portable": False,
                "embedding_state_portable": True},
            "uncertified_boundaries": [
                "complete evaluation contract migration outside the configured runtime",
                "S1 population, worktree, HITL and event-bus composition gaps",
                "S3 external network knowledge backends and semantic retrieval quality",
                "S4 top-k selection and HITL integration",
                "S5 production resource enforcement, external GPU execution and campaign validation",
                "native OpenEvolve multi-parent credit propagation",
                "unreferenced or orphaned OpenEvolve artifact directory migration",
                "live novelty LLM object portability",
                "offline reproduction of future external embedding responses",
                "in-process evaluator calls without a terminal outcome",
                "legacy sequential or batch operations without durable outcomes",
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign", "machine power loss",
                "complete syscall allowlist", "seccomp on non-x86_64 architectures",
                "ExternalCommandLLM/proposer Bubblewrap, filesystem, network or credential isolation",
                "fallback or arbitrary in-process proposer/evaluator seccomp or sandboxing",
                "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "S6 periodic anchors, proxy validity and explicit negative memory feedback",
                "S5 physical hierarchical budgets, configured fidelity and offline research example",
                "S4 opt-in layered admission, bounded evaluation calls and isolated final audit",
                "S3 scoped ContextPack and local knowledge feedback through configured execution",
                "S2 canonical evaluation codec, binding and adapter contracts in configured execution",
                "S1 module registry, default adapters and configured Framework composition",
                "bind dataset contents and frozen evaluation context before admission",
                "write and recover the same stable process identity for unusual executable names",
                "reject invalid configs before launch or persistent state creation",
                "bind and independently audit canonical decision evidence and context",
                "replay governed state in an isolated workspace with mismatch reporting",
                "retain all v64 regression groups and passing historical evidence",
                "reject malformed or non-comparable admission evidence before testing candidates",
                "measure physical provider usage, including zero, failure and replay paths",
                "bind finite nonnegative budget costs to immutable reserve identities and accounts",
                "deny all x32-tagged syscall numbers and the legacy 512..547 range under v2",
                "block unfinalized stale-policy recovery and stop only identity-verified processes",
                "retain v57 historical evidence without rerunning its superseded policy-version assertion",
                "install the same denylist by direct prctl in every durable ExternalCommandLLM worker by default",
                "observe real EPERM, NoNewPrivs and Seccomp status while retaining local HTTP and Authorization inheritance",
                "persist direct_prctl delivery and policy evidence without environment values or credentials",
                "reject invalid delivery and rehashed semantic tampering before target start",
                "preserve direct policy across fork and owner-crash adoption without another provider request",
                "keep explicit disable separate from Bubblewrap, filesystem, network and credential isolation claims",
                "exclude fallback and arbitrary in-process calls from the external-worker seccomp certificate",
                "enforce the versioned x86_64 dangerous-syscall denylist with real EPERM probes",
                "bind canonical filter bytes and SHA256 into durable specs and public journal summaries",
                "share memfd/pass_fds lifecycle across detached wrapper and direct Popen execution",
                "cover ExternalCommandEvaluator, GitWorktreeExecutor and MLE host/governed CLI",
                "reject unsupported architectures and rehashed semantic policy tampering before target start",
                "preserve policy across fork and owner-crash recovery without reexecution",
                "keep the denylist distinct from allowlists, proposer filesystem/network/credential isolation, cgroups and resource quotas",
                "preserve embedding model, credential-free API base and stored finite vectors",
                "reject embedding credentials, malformed URLs, empty vectors and dimension forks",
                "exercise native save/load, strict disk reads and restored-vector novelty behavior offline",
                "keep live novelty LLM objects and future external embedding responses outside the certificate",
                "bind selection receipts to candidate pools, validation evidence and chain terminals",
                "replay single-run, archive-best and best-single-chain selection deterministically",
                "reject wrong winners, ambiguous chains, missing validation evidence and receipt tampering",
                "keep official test scores outside pre-test selection and all selection data outside M9",
                "publish every run receipt digest in paired comparison reports",
                "bind every measured run to an explicit selection object, policy and split",
                "reject selection-contract forks within one paired comparison",
                "require actual measurements for every declared budget unit",
                "require identical declared and actual physical cost-unit sets across the full matrix",
                "enforce caller-required physical cost dimensions in both official campaign runners",
                "report selection and cost-unit coverage without inferring missing costs or USD efficiency",
                "rerun all v52 interoperability, recovery and governance behavior",
                "use the real vendored Program and ProgramDatabase implementations",
                "roundtrip code, primary/additional-parent lineage, generation, metrics and metadata",
                "preserve islands, feature grids, archive/best ids and feature scaling state",
                "exercise native save/load and host parent/inspiration sampling",
                "use a canonical schema-versioned SHA256 integrity envelope",
                "reject malformed, duplicate, dangling, inconsistent or unsupported state",
                "validate native disk before OpenEvolve can skip files or clean references",
                "export only complete eligible Frontier nodes without silent parent or Program loss",
                "map the first declared parent to native parent_id and preserve every additional parent",
                "bind every Program to one deterministic-anchor Frontier checkpoint and restore it exactly",
                "retain host-cell-displaced Programs without fabricating island or elite membership",
                "reject missing metadata, parent forks, graph invariant violations and rehashed tampering",
                "keep native OpenEvolve sampling single-primary-parent rather than claiming DAG credit propagation",
                "bind every referenced external artifact to the exact database snapshot hash",
                "roundtrip raw text/binary bytes with size and per-file SHA256 validation",
                "atomically migrate database and artifacts while rewriting final directory references",
                "reject symlink, nested, unsafe-path, duplicate, missing-directory and content forks",
                "exercise native get_artifacts after removing the source directories",
                "keep host metrics, feature metadata and artifacts outside M9",
                "no orphan-artifact migration, external benchmark, parity, USD or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v65/LAST_RUN.json").write_text(json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v65/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
