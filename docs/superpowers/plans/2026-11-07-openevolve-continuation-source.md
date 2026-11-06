# OpenEvolve Continuation Source Preparation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Durably prepare and recover the exact committed source for a continuation draft without binding or authorizing any experiment.

**Architecture:** Revalidate the draft against a fresh, fixed-head inventory, derive the existing source-export plan, and use the existing Git blob exporter and verifier. Under an exclusive private-directory lock, publish durable draft and source manifest, sync a complete staged tree, then rename it into place. Interrupted staging is retained and a later attempt can reconstruct the same tree without replacing published evidence. The journal is never changed.

**Tech Stack:** Python, Git, fsync, flock, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- The original campaign and its proof identities remain unchanged.
- The draft remains non-executable; source preparation is not a binding or paid-run gate.
- Never copy ignored local files, credentials or the Git worktree into the bundle.
- Only an independently verified source manifest and immutable commit can identify the tree.

## Review Focus

- A stale campaign head or tampered draft must fail before publishing source.
- Interrupted publication must resume without replacing an existing published file or tree.
- Existing source bytes, manifest, or file type changes must be rejected.
- Concurrent preparation must serialize rather than replace evidence.
- Checkout, bundle and journal paths must remain private and separate.

### Task 1: Prepare a durable source tree

**Files:**
- Create: `m0/zoo/circle_packing/continuation_source.py`
- Test: `m0/tests/test_openevolve_continuation_source.py`

**Interface:** `prepare_continuation_source(ledger, draft, *, checkout, directory)` returns the verified draft hash, source tree reference and paths without changing the journal.

- [x] Write tests using temporary Git repositories and fixture campaign inventories for successful preparation, interrupted rename recovery, source or manifest tampering, stale heads and a concurrent call.
- [x] Run the tests and verify the missing API fails.
- [x] Implement the source-only, locked and durable preparation using existing exporter/verifier and manifest helpers.
- [x] Run source and continuation regressions, inspect journal immutability, and request an independent review.
- [ ] Commit only verified changes; runtime creation and atomic campaign binding remain future work.
