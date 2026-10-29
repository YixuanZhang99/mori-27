# Verifier v11 — Framework main-loop governed-state migration

v11 is additive and runs the complete v10 chain first. It supersedes v10's historical
`legacy_m0_main_loop_migrated=false` boundary for main-search M4/M5 writes. It does
not claim ExecutorPool migration, container isolation, external in-flight recovery,
hosted CI execution or external benchmark performance.

## Required checks

1. **v10_complete** — the complete prior verifier exits zero.
2. **main_loop_absorption_and_admission** — Framework materializes every evaluated
   main-search candidate through ADD_NODE, applies policy.absorb through the serial
   StateApplier, writes L1→L2 memory, then applies exactly one M9 MERGE or soft PRUNE.
   Rejected candidates cannot remain eligible parents; accepted IDs equal merged IDs.
3. **resident_control_isolation** — IID-RS still executes and spends from control,
   but baseline candidate IDs never enter the research frontier or its memory.
4. **governed_state_resume** — interrupted/resumed, replayed and uninterrupted runs
   have identical frontier checkpoint bytes, memory state and governed-state summary;
   completed resume adds neither admission Receipts nor state-mutation receipts.
5. **loop_governed_state_contract_tests** — implementation-side absorption,
   admission, control-isolation, memory checkpoint and recovery tests pass.
6. **ci_workflow_wiring** — v5–v10 remain and v11 plus full offline tests are wired;
   hosted CI is not inferred.

Every invocation appends timestamp, command, exit code, checks and values to
`verifier/runs/v11.jsonl`, including failures and exceptions. Each check uses an
isolated evidence directory. External benchmark execution is explicitly false.
