# Verifier v10 — M1 absorb and serial governed state mutation

v10 is additive and runs the complete v9 chain first. It verifies the new M1/M4/M5
protocol path, not that the legacy M0 Framework loop has been migrated to the full
SPEC main_loop, and not external benchmark performance.

## Required checks

1. **v9_complete** — the complete prior verifier exits zero.
2. **absorb_lifecycle** — BestFirstPolicy converts OK evidence into UPDATE_NODE,
   WRITE_MEMORY and PROMOTE_MEMORY; L1 raw text and L2 incremental insight both
   survive; failed evidence remains candidate L1 and ungated.
3. **mutation_whitelist_and_merge** — empty rationale, lineage-field updates and
   whole-payload memory replacement are refused before state change and logged;
   only scored done nodes merge; prune remains a soft state transition.
4. **serial_write_integrity** — real threaded writes through StateApplier preserve
   every memory entry, state-mutation receipt and unique monotonically increasing
   memory sequence number.
5. **state_mutation_contract_tests** — the complete implementation-side mutation,
   absorb, lifecycle and threaded-write tests pass.
6. **ci_workflow_wiring** — v5–v9 remain and v10 plus full offline tests are wired;
   hosted CI is not inferred.

Every invocation appends timestamp, command, exit code, checks and values to
`verifier/runs/v10.jsonl`, including failures. External benchmark execution is
explicitly false.
