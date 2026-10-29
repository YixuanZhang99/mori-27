# Verifier v7 — official grading evidence, M7 execution, X2 control

v7 is additive. It runs the complete v6 verifier and does not weaken or replace
any earlier criterion. Offline fixtures and real local git/process execution are
not external benchmark performance evidence.

## Required checks

1. **v6_complete** — `python3 verifier/v6/verify.py` exits zero.
2. **official_grading_evidence** — the grading entry receives `submission.csv`,
   returns only dev-visible validity, retains the raw official-shaped report in
   the append-only audit lane, and creates a measured record requiring evidence
   references. The injected grader is a protocol fixture, not an MLE-Bench run.
3. **m7_git_worktree_execution** — real local git worktrees and subprocesses
   produce exactly one structured EvidenceRecord per call; success persists a
   resolvable artifact; timeout, nonzero exit, missing required output and
   protected-path tampering become timeout/failed_to_run/invalid states;
   protected checks occur at startup and pre-merge; work copies are removed.
4. **x2_review_control** — review starts pending, approval is bound to the
   canonical action payload, is single-use, pause denies auto/review actions,
   resume restores operation, and another controller instance reconstructs the
   same state from append-only evidence.
5. **m7_x2_contract_tests** — the complete implementation-side M7/X2 test module
   passes, including executor+HITL integration and frozen-hypothesis checks.
6. **ci_workflow_wiring** — the workflow retains v5/v6 and adds v7 plus the full
   offline test command. Hosted CI execution is not inferred from local wiring.

## Exit and evidence

Every invocation appends timestamp, command, exit code, check booleans and result
values to `verifier/runs/v7.jsonl`, including failures and exceptions. v7 exits
zero only when every check passes. It always records external benchmark
execution as false unless a future external runner separately supplies evidence.
