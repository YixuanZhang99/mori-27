# Verifier v9 — Framework cycle checkpoint and deterministic resume

v9 is additive and runs the complete v8 chain first. It checks real Framework.evolve
runs with the deterministic offline load; it does not claim a crash/power-failure
injection test, hosted CI, external API execution or benchmark performance.

## Required checks

1. **v8_complete** — all earlier acceptance remains green.
2. **uninterrupted_equivalence** — a run stopped cleanly after generation 3 and
   resumed from its atomic checkpoint matches an uninterrupted control for best
   prompt/score, main and IID-RS trajectories, accepted candidate lineage,
   generation/funnel count, ledger, health and archive health. Genesis executes
   only once. Replay matches the same control.
3. **archive_extension_recovery** — island migration and H2 extension state resume
   without alarm or archive drift.
4. **completed_resume_noop_and_refusals** — resuming a completed checkpoint adds
   no search receipts; integrity, task, profile and LoopConfig incompatibility are
   refused; checkpoints contain no inflight executor or temporary output file.
5. **loop_checkpoint_contract_tests** — all implementation-side interruption,
   no-op, island and refusal tests pass.
6. **ci_workflow_wiring** — v5–v8 commands remain, v9 and full offline tests are
   wired. Local wiring is not hosted CI evidence.

Every invocation appends timestamp, command, exit code, check booleans and values
to `verifier/runs/v9.jsonl`, including failures. External benchmark execution is
explicitly false.
