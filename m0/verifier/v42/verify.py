"""v42 acceptance: exactly-once adoption of active durable external proposal calls."""
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
    journal = ROOT / "verifier/runs/v42.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v41_complete", [sys.executable, "verifier/v41/verify.py"], timeout=1800)
        run_command("active_external_proposal_sigkill_protocol_and_ambiguity_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
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
                     "tests/test_external_proposer.py",
                     "tests/test_external_evaluator.py",
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
        check("ci_workflow_wiring", "python3 verifier/v42/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False,
              f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        active = next((item for item in CHECKS if item["check"] ==
                       "active_external_proposal_sigkill_protocol_and_ambiguity_guards"), None)
        report = {
            "version": "v42", "passed": rc == 0,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "re_bench_campaign_executed": False,
                "mle_bench_lite_campaign_executed": False,
                "host_parity_certified": False,
                "rubric_b2_complete": False, "rubric_b3_complete": False},
            "external_provider_execution": {
                "real_external_api_executed": False,
                "local_openai_compatible_http_worker_executed": bool(active and active["passed"]),
                "external_scores_or_cost_efficiency_produced": False},
            "supersedes": [
                "v41 refusal of a marker-only active external proposal call"],
            "proposal_recovery": {
                "executed": active is not None,
                "certified": rc == 0 and bool(active and active["passed"]),
                "ordered_prefix_only": True,
                "pre_call_operation_marker": "m0_proposal_started",
                "durable_proposal_marker": "m0_evaluation_started",
                "durable_outcome_marker": "external_proposer_outcome",
                "active_call_adapter": "ExternalCommandLLM",
                "active_marker_reused_without_duplicate": True,
                "original_detached_worker_adopted": True,
                "provider_request_retried": False,
                "persisted_proposals_recalled": False,
                "ordinary_in_process_marker_only_certified": False,
                "legacy_incomplete_journal_certified": False,
                "active_call_with_evaluator_process_or_settlement_certified": False,
                "failed_active_call_full_cohort_recovery_certified": False,
                "separate_proposal_process_and_new_call_counts": True},
            "previously_certified_windows": [
                "pinned RE-Bench numeric-score adapter and paired campaign mechanics",
                "default Bubblewrap, explicit audited disable and optional POSIX limits",
                "sequential external genesis, improve and same-cycle control",
                "prepared external cohorts from safe proposal gaps and zero/partial starts",
                "completed external batch plus same-cycle control before checkpoint"],
            "uncertified_boundaries": [
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "real external provider API campaign",
                "failed active proposal followed by complete M0 cohort recovery",
                "legacy incomplete proposals without operation-boundary evidence",
                "ordinary in-process LLM active calls",
                "incomplete proposals combined with evaluator processes or settlement",
                "machine power loss and whole-machine worker survival",
                "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "bind each durable proposer request to one cohort/candidate operation",
                "run the trusted proposal adapter in a detached journaled process group",
                "write request, response and native outcome atomically without credentials",
                "on owner SIGKILL, wait for and adopt the original worker instead of retrying",
                "reuse the active operation marker and distinguish adopted from new calls",
                "persist malformed, timeout and failed terminal outcomes without retry",
                "reject changed requests and mixed recovery windows",
                "keep ordinary in-process marker-only calls fail-closed",
                "exclude auxiliary proposer processes from the evaluator execution matrix",
                "exercise the real OpenAI-compatible worker only against a local HTTP server",
                "fork replay proposer evidence into an independent namespace",
                "match uninterrupted results, ledger, governed state and certified snapshot",
                "completed resume is a no-op and fresh certified replay passes",
                "no external benchmark score, parity, USD efficiency or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v42/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v42/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
