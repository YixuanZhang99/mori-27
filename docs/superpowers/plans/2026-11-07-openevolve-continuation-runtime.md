# OpenEvolve Continuation Runtime Preparation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Prepare, verify and recover a frozen offline Python runtime for a continuation draft without writing to the original campaign.

**Architecture:** Reuse the validated source preparation, locked offline uv installation and runtime manifest/sync helpers. Under a private directory lock, install each attempt into a unique permanent path, verify and sync it, and publish one no-overwrite manifest. Interrupted unbound attempts remain untouched; a subsequent attempt creates a new path. Once published, recompute and compare every runtime entry and resync before returning.

**Tech Stack:** Python, uv offline cache, Git, fsync, flock, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- No network, credentials, campaign event, budget reset or paid authority.
- Runtime references include their real absolute root; never relocate an installed virtual environment.
- Preserve already published source, runtime and manifests. An abandoned pre-binding attempt is not silently replaced.
- A later version binding must independently revalidate both source and runtime in the original campaign's write transaction.

## Review Focus

- Interrupted installation or publication can resume without overwriting an earlier attempt.
- A changed source, runtime, manifest, base interpreter, dependency lock or original head fails closed.
- Two preparers serialize and publish only one runtime identity.
- Lock, source, cache, journal and runtime locations cannot overlap or escape private ownership rules.
- Installer subprocess receives an explicit credential-free offline environment.

### Task 1: Prepare and verify an offline runtime

**Files:**
- Create: `m0/zoo/circle_packing/continuation_runtime.py`
- Test: `m0/tests/test_openevolve_continuation_runtime.py`

**Interface:** `prepare_continuation_runtime(ledger, draft, *, checkout, source_directory, directory, uv_cache, base_python)` returns source and runtime refs and private paths; it does not modify the ledger.

- [x] Add tests for initial install, same-identity recovery, interrupted manifest publication, tampering, stale head and concurrent preparation. Verify offline credential-free subprocess environment.
- [x] Observe missing implementation fail.
- [x] Implement using existing locked install, runtime manifest and durability helpers; fail closed on unsupported inputs.
- [x] Run source/runtime tests and one real locked offline installation, then seek an independent review.
- [ ] Commit only after verified; no live cell may use the result until an atomic version binding exists.
