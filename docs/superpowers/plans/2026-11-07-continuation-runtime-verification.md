# Bound Continuation Runtime Verification Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Reverify the actual source and runtime against a previously bound fixture continuation before downstream execution preflight.

**Architecture:** The verifier reads the existing campaign binding at a pinned head, opens the original private manifests, and recomputes the source and runtime identities using existing frozen-source/runtime verifiers. It does not create or append artifacts, admit a cell, verify immutable execution, or permit real paid work.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Constraints and review focus

- Only fixture campaigns with a binder assertion are accepted; exact draft and head required.
- Source, manifest, runtime bytes, paths and locked dependency identity must match the journal binding.
- No writes, provider calls, credentials, cell claims or artifact replacement.
- Protect against changed draft values, missing marker, stale head, substituted artifacts, missing files and symlinks.
- This check alone cannot guarantee artifacts remain unchanged afterwards or authorize real execution.

### Task 1: Verify bound artifact identity at a pinned head

- [x] Add tests for success, stale/mismatched identity and tampering; prove no ledger change.
- [x] Run tests and observe failure before implementation.
- [x] Implement verifier using existing manifest and source/runtime checks.
- [x] Run related regression, review, document limitations, and commit.
