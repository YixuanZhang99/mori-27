# Continuation Binding Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Validate append-only version identity and currency invariants against a fixture journal before touching the real campaign.

**Architecture:** A fixture-only v2 event checks the exact predecessor head, reconstructs the draft from current reducer state, checks the original pilot/runtime/audit and global funds, then stores immutable source/runtime identities in a new map. It never grants cell or model admission. Real journal migration stays disabled until verified source/runtime binding and frozen-reader replay compatibility are implemented.

**Tech Stack:** Python, SQLite journal reducer, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- No event may be appended to a non-fixture campaign by this feature.
- Never alter historical pilot, runtime, claims, proof, costs, or the global limit.
- A bound identity does not admit a cell or a provider request.
- Older journal readers fail closed on the new event; real migration remains disabled until historical replay is proven.

## Review Focus

- Stale heads, malformed or modified drafts and original proof mismatches fail.
- Pending usage, protected capacity, or budget breaches fail at the transaction head.
- Duplicate experiment IDs cannot overwrite an existing binding.
- Different source, runtime or protocol identities are not mixed with the original pair.
- Non-fixture campaign histories reject the event even if all other values look valid.

### Task 1: Fixture-only continuation binding reducer

**Files:**
- Modify: `m0/zoo/mle_bench_lite/cny_budget.py`
- Test: `m0/tests/test_openevolve_continuation_event.py`

**Interface:** Fixture-only `bind_circle_continuation` v2 journal event containing predecessor head, full draft, tree/runtime refs, base-Python hash and runtime manifest hash; reconstructed state stores immutable bindings by experiment ID.

- [x] Exercise valid binding, duplicate IDs, stale heads, changed proof/draft, malformed artifacts and non-quiescent or non-fixture state using synthetic journal reducer state.
- [x] Verify tests fail before the reducer exists.
- [x] Implement the reducer with exact event fields and existing draft/inventory validators; do not expose an actual campaign binding entry point.
- [x] Run event, old journal and budget tests; seek independent review.
- [ ] Commit only verified changes; real binding, original frozen replay and new-cell admission remain unfinished.
