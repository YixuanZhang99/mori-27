# Verifier v13 — frozen-cohort BatchScheduler and canonical admission

v13 is additive and runs the complete v12 chain first. It verifies the canonical M7
batch path: one frozen candidate cohort, atomic all-intent reservation, bounded
execution, settlement of every returned real cost before serial M1/M9 finalization,
and exactly one candidate-local MERGE or PRUNE decision. It does not claim that the
sequential M0 Framework evaluator has been parallelized, that in-flight external
processes are recoverable, or that any external benchmark has executed.

## Required checks

1. **v12_complete** — the complete prior verifier exits zero.
2. **frozen_cohort_execution_and_gate_not_rank** — three pre-created candidates execute
   through a real bounded ExecutorPool with observed max_inflight=2; intent budgets
   replace request budgets; no admission begins until all executions and settlements
   finish; absorb/admission remains serial in input order. A low-score positive-flip
   candidate is MERGEd, a high-score negative-flip candidate is PRUNEd, and failed
   evidence is PRUNEd. Actual token cost is 2+3+4=9, with no open reserve.
3. **atomic_batch_budget_rejection** — if any intent cannot be reserved, every earlier
   reservation is released, backend execution is zero, all spent accounts are zero,
   rejection evidence names both released intents, and checkpoint becomes legal.
4. **admission_failure_preserves_real_costs** — an exception in the second admission
   propagates after all three returned EvidenceRecords have settled their actual cost;
   no later candidate is materialized, no cycle-complete record is emitted, reserves
   are empty, and checkpoint state resets.
5. **non_ok_admission_and_checkpoint_guards** — an illegal MERGE decision for non-OK
   evidence is refused after its real cost settles, leaving the node done rather than
   merged. Checkpoint is refused both during an active cohort and with an open reserve,
   and succeeds after cleanup.
6. **batch_scheduler_contract_tests** — implementation-side scheduler, pool,
   executor/HITL, state-mutation and governed-loop tests pass.
7. **ci_workflow_wiring** — v5–v12 remain and v13 plus full offline tests are wired;
   hosted CI execution is not inferred.

Every invocation appends timestamp, command, exit code, checks and values to
`verifier/runs/v13.jsonl`, including failures and exceptions. Each check uses an
isolated evidence directory. External benchmark execution is explicitly false.
