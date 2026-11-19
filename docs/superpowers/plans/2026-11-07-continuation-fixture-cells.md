# Continuation Fixture Cells Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Allow a bound fixture continuation's first paired cells to preserve distinct original clocks and worker identities while keeping later seeds and all real campaigns closed.

**Architecture:** Parse legacy and version-qualified cell IDs in one shared, dependency-free helper. The campaign reducer accepts only seed 0 of an already bound fixture continuation, using its own draft reference and fixed deadline; original pilot behavior is unchanged. Existing clock and recorded-clock code recognizes qualified identities, and worker/host/run claims continue to use the original global campaign accounting.

**Tech Stack:** Python, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- Non-fixture continuation events remain forbidden; no live provider or candidate execution.
- No new budget, no clock reset, no worker restart, no relabeling old evidence.
- Continuation seeds 1 and 2 stay denied until complete independent first-pair coverage is implemented.
- Versioned cells are scoped to one already-bound draft, original global ledger and fixed limits.

## Review Focus

- Legacy cell parsing, claims and restore behavior must remain unchanged.
- Cross-experiment IDs, wrong plan or duration, later seeds and duplicate claims fail.
- A Mori run cannot bind before its one worker; a vendor host retains its one-start order.
- Original first pair claims and the campaign's remaining money are not replaced.
- Clock recovery does not reset the original start or extend the deadline.

### Task 1: Version-qualified fixture clock and worker claims

**Files:**
- Create: `m0/zoo/circle_packing/cell_identity.py`
- Modify: `m0/zoo/circle_packing/cell_deadline.py`, `m0/zoo/mle_bench_lite/cny_budget.py`
- Test: `m0/tests/test_openevolve_continuation_cells.py`.

**Interface:** `parse_cell_identity(value)` returns `(experiment_id | None, arm, seed)` for valid legacy or version-qualified IDs. Bound fixture seed-0 clocks use `sha256:<draft_sha256>` and the draft's original wallclock limit.

- [x] Test paired fixture clocks, original clock recovery, qualified worker/host claims and single-run binding, plus invalid plan/seed/identity/duplicate cases.
- [x] Confirm tests fail before the qualified cell path exists.
- [x] Implement scoped fixture-only qualified claims and preserve all legacy behavior.
- [x] Run clock, ledger and continuation regressions; independently review.
- [ ] Commit only after tests pass. Full first-pair coverage, actual live admission and real migration remain unimplemented.
