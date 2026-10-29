# Verifier v8 — M4 ResearchFrontier and portable recovery

v8 is additive and first runs the complete v7 chain. It checks local research
state recovery, not full Framework.evolve cycle resume and not external benchmark
performance.

## Required checks

1. **v7_complete** — the complete prior verifier exits zero.
2. **skeleton_reference_isolation** — parent/child depth and scoped best are
   correct; reference edges do not change deterministic sampling or best;
   pruning cascades through skeleton descendants only and hard-deletes nothing.
3. **portable_checkpoint_recovery** — canonical JSON bytes carry schema_version,
   GitState, InflightExecutor and messages; integrity/schema violations refuse
   restore; a restored running node can complete and change best; a round trip
   before completion is byte-identical.
4. **frontier_contract_tests** — all implementation-side ResearchFrontier tests
   pass, including minimize direction, failed evidence and lineage validation.
5. **ci_workflow_wiring** — v5/v6/v7 commands remain and v8 is appended alongside
   the complete offline test command. Hosted CI is still not claimed.

Every invocation, including failures and exceptions, appends timestamp, command,
exit code, checks and values to `verifier/runs/v8.jsonl`. External benchmark
execution remains explicitly false.
