# Verifier v12 — bounded real ExecutorPool and serial finalization

v12 is additive and runs the complete v11 chain first. It verifies the M7 pool as a
composable execution backend. It does not claim that the sequential M0 Framework has
become a batch scheduler, that worktrees are security sandboxes, or that externally
running processes can be recovered after power loss.

## Required checks

1. **v11_complete** — the complete prior verifier exits zero.
2. **real_parallel_quota_and_failure_isolation** — real git worktrees and subprocesses
   reach but never exceed max_inflight=2; four candidates return exactly four ordered
   EvidenceRecords, with OK, failed_to_run and INVALID kept candidate-local; shared
   JSONL evidence remains parseable and worktrees are cleaned.
3. **serial_absorb_and_checkpoint_guard** — queued/running work makes checkpoint_state
   fail; result callbacks run serially in candidate input order through M1.absorb and
   StateApplier; only OK evidence is frontier-eligible, failed evidence remains L1;
   the quiescent pool checkpoints with no inflight work.
4. **pool_robustness** — duplicate candidate batches are refused before execution;
   an unexpected backend exception becomes one failed EvidenceRecord with increasing
   attempts; finalization exceptions propagate unchanged and finalizing state resets.
5. **executor_pool_contract_tests** — all implementation-side real-process, pool,
   executor/HITL and serial-state tests pass.
6. **ci_workflow_wiring** — v5–v11 remain and v12 plus full offline tests are wired;
   hosted CI is not inferred.

Every invocation appends timestamp, command, exit code, checks and values to
`verifier/runs/v12.jsonl`, including failures and exceptions. Each check uses an
isolated evidence directory. External benchmark execution is explicitly false.
