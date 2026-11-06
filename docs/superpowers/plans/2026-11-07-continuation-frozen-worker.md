# Continuation Frozen Worker Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Run the first Mori continuation fixture using the bound source and interpreter in an independent process, with only loopback credentials and the original fixture ledger.

**Architecture:** Extend the existing fixture worker's authority preparation for schema-3 continuations, reusing bound-artifact verification and the original named cell clock. The existing fixture entry continues to reject non-fixture campaigns and non-loopback services. A subprocess integration test launches the committed frozen worker with an explicitly filtered environment; its sandbox and in-process replay remain within the fixture boundary.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

- No real credentials, non-loopback providers or non-fixture campaigns.
- Exact original deadline, plan, source, runtime and campaign identity; no restart of a paid worker.
- Record six search attempts and shared-ledger settlement, with process paths proving frozen source/runtime.
- This standalone process is not the whole-cell supervised live path, a recovery test or a benchmark.
- [ ] Test fixture authority preparation and altered identities, then implement worker.
- [ ] Run frozen-source subprocess with real offline runtime and fake provider; verify accounting and replay.
- [ ] Regress legacy fixture entry, review, document limits and push.
