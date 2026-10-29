"""Explicit platform contract for local development and Linux acceptance.

`-m "not linux"` selects portable tests on any host; it does not catch failures
or auto-skip tests. The unfiltered suite retains every test. Linux acceptance
also uses `--fail-on-skip` so missing prerequisites cannot yield a green run.

The inventory follows execution dependencies, not the current platform. Mixed
modules keep their pure policy/validation cases in the portable suite. See the
2026-10-29 audit for the initial 337 portable / 153 Linux-dependent case split.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent

# Every test in these modules constructs a Linux-dependent execution backend.
LINUX_MODULES = {
    "test_external_batch_control_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_batch_partial_start_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_batch_post_settlement_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_batch_proposal_recovery.py": "direct-prctl proposer and Linux process identity",
    "test_external_batch_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_control_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_evaluator.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_genesis_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_post_settlement_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_proposal_failure_post_settlement_recovery.py": "external proposer/evaluator and Linux process identity",
    "test_external_proposal_failure_recovery.py": "direct-prctl proposer and Linux process identity",
    "test_external_proposal_recovery.py": "direct-prctl proposer and Linux process identity",
    "test_external_proposer.py": "direct-prctl proposer and Linux process identity",
    "test_external_recovery.py": "Bubblewrap evaluator and Linux process identity",
    "test_external_resource_policy.py": "Bubblewrap and Linux resource/process limits",
    "test_inprocess_proposal_failure_recovery.py": "in-process proposer paired with a Bubblewrap evaluator",
    "test_sandbox_executor.py": "real Bubblewrap and x86_64 seccomp execution",
    "test_settlement_crash_recovery.py": "durable executor uses Linux /proc process identity",
}

# These modules also contain portable tests. List only the Linux test functions;
# parametrized cases inherit their function's classification.
LINUX_FUNCTIONS = {
    "test_batch_execution_recovery.py": {
        "test_real_batch_owner_crash_recovers_settles_and_admits_exactly_once",
    },
    "test_benchmark_agents.py": {
        "test_real_host_and_governed_clis_with_local_openai_and_isolated_execution",
    },
    "test_executor_hitl.py": {
        "test_executor_success_commits_artifact_and_checks_protection",
        "test_executor_encodes_timeout_crash_missing_output_and_tampering",
        "test_executor_rejects_frozen_hypothesis_mismatch_and_base_tamper",
        "test_review_approval_is_bound_single_use_and_pause_resume_survives_restore",
    },
    "test_executor_pool.py": {
        "test_real_parallel_quota_failure_isolation_and_serial_absorb",
    },
    "test_executor_recovery.py": {
        "test_real_owner_crash_pending_then_recovers_exactly_once",
        "test_lost_wrapper_kills_registered_orphan_and_fails_closed",
        "test_finished_process_without_executor_evidence_is_finalized_once",
        "test_pid_start_mismatch_never_adopts_reused_process",
    },
    "test_external_default_sandbox.py": {
        "test_default_bubblewrap_is_real_and_audited",
        "test_only_explicit_disable_runs_without_isolation",
        "test_fork_inherits_policy_and_keeps_independent_process_history",
    },
    "test_proposer_seccomp.py": {
        "test_default_proposer_eperm_status_audit_and_fork",
        "test_only_explicit_proposer_seccomp_disable_omits_policy",
        "test_direct_delivery_rejects_rehashed_spec_before_target_start",
        "test_proposer_owner_crash_adopts_original_direct_seccomp_outcome",
    },
    "test_seccomp_policy.py": {
        "test_direct_popen_uses_same_memfd_contract",
        "test_external_evaluator_real_eperm_fork_and_public_audit",
        "test_only_explicit_disable_omits_seccomp_policy",
        "test_detached_wrapper_rejects_rehashed_spec_before_target_start",
        "test_invalid_policy_fails_before_process_journal_launch",
        "test_git_worktree_executor_enforces_and_audits_same_policy",
        "test_owner_crash_adopts_original_seccomp_outcome_without_reexecution",
    },
}


def _validate_inventory() -> None:
    """Reject stale names even when pytest is invoked on a smaller test subset."""
    for filename in sorted(LINUX_MODULES.keys() | LINUX_FUNCTIONS.keys()):
        source = TEST_ROOT / filename
        if not source.is_file():
            raise pytest.UsageError(f"Linux test inventory names missing file: {filename}")
        functions = {
            node.name for node in ast.parse(source.read_text(encoding="utf-8")).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing = LINUX_FUNCTIONS.get(filename, set()) - functions
        if missing:
            raise pytest.UsageError(
                f"Linux test inventory names missing tests in {filename}: {sorted(missing)}")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--fail-on-skip", action="store_true", default=False,
        help="Fail acceptance if any test or collection is skipped (including xfail).")


def pytest_configure(config: pytest.Config) -> None:
    _validate_inventory()
    if config.getoption("--fail-on-skip"):
        config.pluginmanager.register(_FailOnSkip(), "autoresearch-fail-on-skip")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Run before pytest's built-in -m selector, so explicit selection sees marks.
    for item in items:
        path = Path(item.path).resolve()
        if path.parent != TEST_ROOT:
            continue
        function = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
        if path.name in LINUX_MODULES or function in LINUX_FUNCTIONS.get(path.name, set()):
            item.add_marker(pytest.mark.linux)


class _FailOnSkip:
    def __init__(self) -> None:
        self.skipped: list[str] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # Expected failures also have a skipped outcome and cannot certify a run.
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.skipped and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter) -> None:
        if self.skipped:
            terminalreporter.write_sep(
                "=", f"acceptance rejected: {len(self.skipped)} skipped/xfail report(s)", red=True)
            for nodeid in self.skipped:
                terminalreporter.write_line(f"  {nodeid}")
