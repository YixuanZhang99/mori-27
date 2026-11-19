# Continuation Currency Report Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Attach independently replayed, head-pinned per-run currency accounting to versioned continuation cell inventory.

**Architecture:** Reuse `snapshot_continuation_matrix`, `RecordedCurrencyView` and `RecordedCellClock`. For each supplied cell proof require the same independently pinned campaign head, campaign policy, cell plan, original clock claim and unique run binding; reduce costs from the proof. Missing proof remains null, scores and terminal status remain unverified; no operation opens a seed gate.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-matrix-report.md` and `2026-11-07-openevolve-campaign-epochs.md`.

- Reject changed head, crossed cells/runs/campaigns, unpinned proofs, tampered clocks and unknown identities.
- Do not infer zero cost for unclaimed or unverified cells or claim invoice verification.
- Currency evidence is private and must never be emitted to a model; return summary only.
- This report does not certify a physical process, geometry, complete search or benchmark.
- [x] Test recorded per-run evidence, unclaimed slots, wrong identities/head and no mutations.
- [x] Implement report and run focused plus legacy regressions; review.
- [x] Verify against existing actual paired fixture evidence; document and push.

The paired run completed with the report before extraction of the shared verifier; the final shared verifier was separately run on the same pinned proofs and produced 228 micro-CNY per simulated arm without changing the ledger. Both legacy and continuation reports reject altered cached audits.
