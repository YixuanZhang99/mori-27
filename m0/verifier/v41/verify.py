"""v41 acceptance: certified external proposal-gap recovery without ambiguous retries."""
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
    journal = ROOT / "verifier/runs/v41.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    rc = 1
    try:
        run_command("v40_complete", [sys.executable, "verifier/v40/verify.py"], timeout=1500)
        run_command("proposal_boundary_real_sigkill_and_ambiguity_guards",
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "tests/test_external_batch_proposal_recovery.py",
                     "tests/test_external_batch_partial_start_recovery.py"])
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
        check("ci_workflow_wiring", "python3 verifier/v41/verify.py" in workflow,
              "current verifier command")
        rc = 0 if all(item["passed"] for item in CHECKS) else 1
    except Exception as error:
        check("verifier_exception", False,
              f"{error!r}\n{traceback.format_exc()}")
        rc = 2
    finally:
        proposal = next((item for item in CHECKS if item["check"] ==
                         "proposal_boundary_real_sigkill_and_ambiguity_guards"), None)
        report = {
            "version": "v41", "passed": rc == 0,
            "external_benchmark_execution": {
                "executed": False, "scores_produced": False,
                "re_bench_campaign_executed": False,
                "mle_bench_lite_campaign_executed": False,
                "host_parity_certified": False,
                "rubric_b2_complete": False, "rubric_b3_complete": False},
            "supersedes": ["v40 refusal of every incomplete external cohort proposal journal"],
            "proposal_recovery": {
                "executed": proposal is not None,
                "certified": rc == 0 and bool(proposal and proposal["passed"]),
                "ordered_prefix_only": True,
                "pre_call_operation_marker": "m0_proposal_started",
                "durable_proposal_marker": "m0_evaluation_started",
                "persisted_proposals_recalled": False,
                "missing_suffix_operations_called_once": True,
                "continued_processes_use_original_proposals": True,
                "separate_proposal_and_process_adoption_counts": True,
                "marker_only_active_call_certified": False,
                "legacy_incomplete_journal_certified": False,
                "incomplete_journal_with_process_or_settlement_certified": False},
            "previously_certified_windows": [
                "pinned RE-Bench numeric-score adapter and paired campaign mechanics",
                "default Bubblewrap, explicit audited disable and optional POSIX limits",
                "sequential external genesis, improve and same-cycle control",
                "prepared external cohorts from zero/partial starts through finalization",
                "completed external batch plus same-cycle control before checkpoint"],
            "uncertified_boundaries": [
                "actual seven-task RE-Bench campaign and external scores",
                "actual 22-task MLE-Bench Lite campaign and host parity",
                "proposal call started but has no durable completion evidence",
                "legacy incomplete proposals without operation-boundary evidence",
                "incomplete proposals combined with processes, settlement or finalization",
                "machine power loss", "non-external in-process evaluator crashes",
                "seccomp", "complete resource limits", "hostile-kernel boundary",
                "cgroup aggregate CPU/memory/disk/GPU quotas", "hosted CI execution"],
            "scope": [
                "write one intent-bound operation marker before any possible external LLM call",
                "resume only an exact ordered durable-proposal prefix with matching marker prefix",
                "a marker beyond the durable prefix is an ambiguous active call and fails closed",
                "persisted proposal, intent, parent, apply result, head and cost are rebound",
                "only the missing proposal suffix invokes the LLM, exactly once per candidate",
                "incomplete proposals cannot coexist with cohort processes or settlement",
                "continued proposal and process counts are reported independently",
                "real SIGKILL recovery matches uninterrupted ledger, state, snapshot and replay",
                "completed resume is a no-op and legacy incomplete journals remain uncertified",
                "no external benchmark score, parity, USD efficiency or A/B/C completion claim"],
            "checks": CHECKS}
        (ROOT / "verifier/v41/LAST_RUN.json").write_text(
            json.dumps(report, indent=2) + "\n")
        journal.open("a").write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "python3 verifier/v41/verify.py", "exit_code": rc,
            "checks": CHECKS}, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
