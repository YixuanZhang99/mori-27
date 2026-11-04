# Invocation Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one private owner responsible for the accounting lifecycle of all hierarchical planning/operator/evaluation calls.

**Architecture:** Introduce InvocationLifecycle with a private started-operation state. Retain the real physical settlement adapter, remove duplicate operator paths, and keep request construction and result identity validation in orchestration.

**Tech Stack:** Python 3.12, existing pytest/uv, append-only physical authority and continuation store.

**Spec:** docs/superpowers/specs/2026-11-04-invocation-lifecycle-design.md

## Global Constraints

Preserve v6/v7/v8 runtime identities, authoritative event schemas/order, all existing test sources and historical verifier commands/timeouts. No public Framework expansion, new dependency, real supplier request or live campaign migration. The original full design and RUBRIC requirements remain open.

## Review Focus

- Known costs survive post-call binding/identity rejection: direct lifecycle and existing public tests.
- Unknown provider usage retains the full reservation: all three direct phase variants and existing recovery tests.
- BaseException and missing durable wall-time do not silently settle/retry: direct phase variants and original interrupted-wall test.
- Measured executor error gets one charge even when a later integrity check rejects it: existing worktree/currency suites.
- Replay and old checkpoint adoption preserve provider state and event order: installed-base compatibility rehearsal and full governance recovery tests.

### Task 1: Own and integrate physical invocation accounting

**Files:** Create `m0/core/composition/invocation.py`, `m0/tests/test_invocation_lifecycle.py`; modify `hierarchical_runtime.py`, `governed.py`, `runtime.py`; update the current status/module map after verification.

**Interfaces:** `InvocationLifecycle(budget, store, settle, *, governance=None)` exposes async `planning(receipt, provider, invoke)`, `operator(operator, request, candidate, receipt, *, provider, lane="main", slot_id=None)` and `evaluation(receipt, provider, invoke, *, identity, domain, elapsed=None, lane="main", slot_id=None)`. `elapsed` is a supervisor wall-time supplier only for ungoverned durable execution. All three return measured results with settlement complete or raise with an explicit unresolved/settled state. The owner receives no runtime object.

- [ ] Write `test_invocation_lifecycle.py`: all phases settle known costs; unknown usage and BaseException keep reservations; post-settlement integrity rejection retains actual usage; typed operator failure remains a charged failed sample; a repeated attempt cannot dispatch a second call. Use actual HierarchicalBudget state, not a mocked settlement call count.
- [ ] Run new tests against the baseline. Expected: failure because the new lifecycle entry is absent; existing baseline is already verified at 75f397e locally and hosted.
- [ ] Implement the owner and route all hierarchical phases through it. Delete duplicated legacy/governed operator lifecycle and obsolete planning/unresolved helpers. Retain physical settlement and the flat-runtime provider-floor adapter.
- [ ] Run `pytest -q tests/test_invocation_lifecycle.py tests/test_composed_budget.py tests/test_governed_runtime.py tests/test_composed_recovery.py tests/test_governed_cny_framework.py`. Expected: all pass without weakening old tests.
- [ ] Rehearse cross-commit pause/resume with installed 75f397e code, then run full project checks and update the scope documentation. Expected: no replayed provider request, no stale schema reinterpretation; all checks pass.
- [ ] Commit implementation with exact validation, obtain a fresh whole-branch review, resolve Important/Critical findings with RED→GREEN tests, and run clean same-SHA v73 acceptance. Push a verified rollback milestone; do not merge main or claim full design completion.
