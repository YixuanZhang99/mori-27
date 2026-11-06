# OpenEvolve Continuation Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Generate a non-executable, versioned six-cell continuation draft anchored to the original campaign, first-pair evidence identity and a single journal head.

**Architecture:** A pure draft builder consumes the detached, head-pinned continuation inventory. It checks original binding and audit identity, global quiescence, new source and explicit protocol differences; it namespaces all cell IDs. It writes no files, journal events or monetary reservations, and cannot itself authorize work.

**Tech Stack:** Python, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- No new budget, paid operation, or modification of the frozen first experiment.
- `none` changes the model protocol and all comparisons remain separate from the original pair.
- Runtime/source bundles and atomic revalidation at binding remain mandatory future prerequisites.
- All inventories must be re-read and validated within the future write transaction; this draft is not authorization.

## Review Focus

- Invalid or missing original audit, source identity, runtime or campaign policy must fail.
- Pending, reserved or protected funds and budget breaches must fail preflight.
- IDs must be bounded and unambiguous across experiments and arms.
- Mutating input or output after construction cannot alter the other.
- All future seeds remain unrun and no output claims benchmark performance.

### Task 1: Build a versioned continuation draft

**Files:**
- Create: `m0/zoo/circle_packing/continuation_draft.py`
- Test: `m0/tests/test_openevolve_continuation_draft.py`

**Interface:** `build_continuation_draft(inventory, *, experiment_id, source_commit, dependency_lock_sha256, method_changes)` returns a schema 3, `draft_not_executable` dictionary with `draft_sha256`, explicit `reasoning_effort=none`, and six namespaced unrun cell identities.

- [x] Test a complete quiescent inventory, deterministic digest, distinct namespaced cells, changed inputs, nonmutation and all failure conditions above.
- [x] Run tests and observe failure due to missing builder.
- [x] Implement the pure builder using existing campaign policy and digest validators.
- [x] Run the new tests and original pilot-plan tests; independently review.
- [ ] Commit the non-executable draft; never use it as a gate for paid work.
