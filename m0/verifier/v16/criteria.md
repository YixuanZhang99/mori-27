# Verifier v16 — durable batch finalization recovery

v16 is additive and runs the complete current v15 chain first. It verifies local,
append-only recovery of canonical BatchScheduler finalization from fully settled
EvidenceRecord journals. It covers caught admission exceptions and clean state
reconstruction, not power-loss injection, ambiguous decision application, external
subprocess takeover or benchmark execution.

## Required checks

1. **v15_complete** — the complete current prior verifier exits zero.
2. **same_process_resume_and_new_batch_guard** — after the second admission callback
   fails, recovery_state reports ready with exactly the remaining candidates. Starting
   another batch is refused without execution. Resume neither re-executes nor resets
   the three real costs, does not repeat the first candidate's ADD_NODE, produces
   merged/pruned/pruned states and emits exactly one cycle completion.
3. **fresh_state_rebuild_and_completed_noop** — a new scheduler with empty M4/M5 state
   rebuilds every candidate from journaled candidates and EvidenceRecords with zero
   backend calls and zero additional settlement events; admission events are not
   duplicated. A subsequent completed resume returns identical evidence and appends
   no records or mutations.
4. **ambiguous_and_incomplete_refusal** — a decision journal without its admission is
   classified ambiguous and never automatically replayed; execution-incomplete
   journals cannot resume or execute. Pre-submission parameter failure is classified
   aborted rather than recoverable execution.
5. **batch_recovery_contract_tests** — recovery, scheduler, multi-currency, pool,
   executor/HITL, state-mutation and Framework checkpoint tests pass.
6. **ci_workflow_wiring** — v5–v13 and v15 remain, historical failing v14 is not a
   gate, and v16 plus full offline tests are wired. Hosted CI is not inferred.

Every invocation appends timestamp, command, exit code, checks and values to
`verifier/runs/v16.jsonl`, including failures and exceptions. Each check uses an
isolated evidence directory. External benchmark execution is explicitly false.
