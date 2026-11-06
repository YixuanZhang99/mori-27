# Historical Campaign Prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make an independently verified historical journal prefix temporarily available for offline replay after later journal events have been appended.

**Architecture:** Under the original campaign's transaction, verify the complete current journal and reconstruct the exact caller-pinned prefix with the existing reducer. Materialize it only inside a private temporary context and remove it on exit. Frozen-source replay must run with no credentials or network and see this prefix at the original ledger path in an isolated mount namespace; no copied journal can be used to authorize new paid work.

**Tech Stack:** Python, SQLite, bubblewrap, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- Never mutate the original campaign or grant a new budget.
- The prefix is temporary, private and exclusively for offline audit; no model dispatch or candidate execution.
- Verify the full journal and the requested prefix hash before exposing a snapshot.
- Frozen-source replay and its original artifacts remain independently verified.

## Review Focus

- Wrong head, missing events or corrupt current history cannot yield a snapshot.
- A later valid fixture event is excluded while prior policy, claims and proofs remain unchanged.
- Existing paths, symlinks and permissions cannot be overwritten or exposed.
- Temporary copy disappears even after exceptions; network and API credentials are unavailable to replay.
- A historic prefix is not itself a new campaign or permission to run a cell.

### Task 1: Temporary verified prefix

**Files:**
- Create: `m0/zoo/circle_packing/historical_prefix.py`
- Test: `m0/tests/test_openevolve_historical_prefix.py`

**Interface:** `_temporary_verified_prefix(ledger, *, expected_head)` is a context manager that yields a temporary private SQLite path after verifying the complete current history and pinned prefix; it deletes the temporary directory on exit.

- [x] Test a genuine fixture journal with a later continuation event, exact original identity, no mutation, bad head/hash, corrupt current journal and cleanup on exceptions.
- [x] Observe failures before implementing the context manager.
- [x] Implement the private temporary copy using existing reducer, read transaction and strict permissions.
- [x] Run budget and prefix regressions and independently review.
- [x] Add isolated frozen replay as a separate task before any real migration is permitted.

### Task 2: Isolated frozen replay

**Files:**
- Modify: `m0/zoo/circle_packing/historical_prefix.py`
- Test: `m0/tests/test_openevolve_historical_prefix.py`

**Interface:** `replay_historical_pair(ledger, *, expected_head, expected_plan_ref, seed, mori_directory, vendor_directory, replay_output)` runs the original frozen audit with a temporary prefix mounted at the original ledger path, no network and a credential-free environment; returns the audited summary.

- [x] Test that a later fixture event does not enter the mounted prefix, the subprocess has network isolation, credentials are absent and the original journal is unchanged.
- [x] Verify test fails before the entry point exists.
- [x] Implement source/runtime/output validation, bubblewrap isolation and bounded subprocess execution; fail closed on errors or unexpected output.
- [x] Run unit tests and the actual private old-pair offline replay; seek independent review.
- [ ] Do not enable real campaign migration until the historical replay path is independently verified after an appended event.
