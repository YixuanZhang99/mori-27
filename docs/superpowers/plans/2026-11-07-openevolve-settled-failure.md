# OpenEvolve Settled Failure Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Distinguish a durably settled failed provider call from an unknown outcome in an opt-in, offline-tested transport, without enabling any additional paid experiment.

**Architecture:** The existing trusted dispatcher is the authority that recovers currency and settles physical usage before returning `known_failed`. Broker and client each require an explicit boolean opt-in; only a measured `known_failed` provider request with no result can leave transport usable for the next upstream iteration. Unknown, invalid, late and lost responses, stage requests, and refusals remain fail-closed. Defaults remain unchanged and the existing live entry points do not opt in.

**Tech Stack:** Python, Unix sockets, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`

## Global Constraints

- The frozen `49fb076` experiment and original campaign remain unchanged.
- A settled failure is an observed failed attempt, not a retry of an unknown operation; do not perform paid calls.
- New transport behavior alone must not grant any cell, clock, or currency authority.

## Review Focus

- Lost reply after dispatch halts both sides; no repeat is sent.
- Missing or invalid usage cannot be treated as a settled failure.
- A stage failure cannot opt into provider continuation.
- Refusals, deadline failures, and unknown responses remain halted.
- Defaults and independently mismatched opt-ins do not silently enable live continuation.

### Task 1: Explicit, measured failure handling

**Files:**
- Modify: `m0/zoo/circle_packing/host_transport.py`
- Test: `m0/tests/test_openevolve_host_transport.py`

**Interfaces:**
- `HostBridgeClient(model, *, continue_settled_failures: bool = False)`.
- `HostBroker(path, token, dispatch, *, continue_settled_failures: bool = False)`.
- `SettledProviderFailure(UsageError)` carries no provider result; measured usage remains in `client.last_usage`.

- [x] Add a two-request Unix-socket test showing an opted-in measured provider failure raises `SettledProviderFailure`, preserves usage, and permits the next distinct request to succeed; use only a fixture dispatcher.
- [x] Add cases for unknown/lost response, invalid usage, stage requests, default behavior, and non-boolean configuration; assert no further successful dispatch after uncertainty.
- [x] Run `cd m0 && PYTHONPATH=.:tests python -m pytest -q tests/test_openevolve_host_transport.py` and verify the new test fails because the opt-in API is missing.
- [x] Implement both opt-in paths and the typed failure; do not change the dispatcher or any live constructor.
- [x] Run transport and dispatcher regression tests; verify their complete outputs and review the diff.
- [ ] Commit only after the fixture tests pass. Full epoch admission, durable artifacts, journal namespace and complete coverage remain separate required work.
