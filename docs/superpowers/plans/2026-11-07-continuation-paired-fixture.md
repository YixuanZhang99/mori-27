# Continuation Paired Fixture Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and systematic-debugging.

**Goal:** Exercise both first-pair arms under the same versioned fixture draft, source, runtime and cumulative campaign.

**Architecture:** Prepare one bound continuation, run the fixed-source Mori fixture process, then run the isolated upstream reference worker with the same plan and ledger. Use an idempotent fake patch to avoid artificial parent mismatch, preserve all outcomes, and assert each arm's recorded counts and shared monetary settlement.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

- Only loopback and fixed fake credentials; never load the real key or use a real campaign.
- Six declared iterations for each side, independent cell identities, clocks and workers; no reset of total currency.
- Verify original pilot and audit remain present, no unresolved/reserved/breach at completion.
- Preserve errors; if stable fake patch cannot generate candidates, diagnose rather than claim success.
- The test is not an independently audited comparable benchmark or whole-cell supervised live work.
- [x] Run paired fixture with actual evaluator and inspect per-arm and total evidence.
- [x] Review, document limitations, regress and push.

Full paired test passed before the additional Mori trace assertion was added; that assertion was separately executed against the same saved run. Cumulative fixture amounts do not prove per-cell cost attribution.
