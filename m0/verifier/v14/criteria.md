# Verifier v14 — multi-currency frozen-cohort accounting

v14 is additive and runs the complete v13 chain first. It verifies that canonical
BatchScheduler execution settles explicit EvidenceRecord costs into independent
physical accounts without allowing those costs into M9 admission. It does not claim
an external benchmark run, hosted CI execution, container isolation or external
in-flight process recovery.

## Required checks

1. **v13_complete** — the complete prior verifier exits zero.
2. **per_unit_settlement_and_gate_not_rank** — a real bounded two-candidate cohort
   settles token=140, USD=1.25, eval_count=2, node=2, wallclock=6 and gpu_hours=0.25
   into separate accounts; request token limits come from each reserved basket;
   versioned conversion to standard coin is reporting-only and totals 547. The
   lower-scoring positive-flip candidate merges while the higher-scoring, higher-cost
   negative-flip candidate prunes. Settlement evidence carries every physical unit.
3. **atomic_cohort_and_legacy_refusal** — insufficient USD in a later intent releases
   every earlier basket with zero backend calls and zero per-unit spending. A legacy
   single-currency ledger refuses a requested basket rather than silently dropping
   its non-token units.
4. **invalid_costs_cannot_partially_settle** — a non-finite value in the second
   returned CostVec is detected before any cohort settlement or admission, leaving
   no settled intent and no node. Direct ledger reservation rejects NaN/infinity;
   invalid settlement preserves its open reserve for later release or correction.
5. **multicurrency_batch_contract_tests** — scheduler, multi-currency, pool,
   executor/HITL, state-mutation, governed-loop and Pareto tests pass.
6. **ci_workflow_wiring** — v5–v13 remain and v14 plus full offline tests are wired;
   hosted CI execution is not inferred.

Every invocation appends timestamp, command, exit code, checks and values to
`verifier/runs/v14.jsonl`, including failures and exceptions. Each check uses an
isolated evidence directory. External benchmark execution is explicitly false.
