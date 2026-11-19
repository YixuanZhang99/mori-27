# Continuation Fixture Artifact Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bind independently verified source and runtime artifacts to the fixture campaign's exact head in a single append transaction without allowing live execution.

**Architecture:** Hold both existing private bundle locks while revalidating draft, Git tree, source bytes, runtime manifest and runtime bytes. Sync and reverify the artifacts before entering the campaign write transaction; the existing reducer independently checks the pinned head, predecessor proof, global currency and experiment uniqueness. Only marked fixture ledgers are accepted. Historical frozen replay after a real migration and any cell admission remain separate, unresolved requirements.

**Tech Stack:** Python, SQLite, Git, flock, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Global Constraints

- Never append a continuation event to a real campaign in this step.
- No provider call, new budget, or cell admission.
- Never create or replace source/runtime artifacts while binding.
- Original campaign head, original pair and currency remain authoritative.

## Review Focus

- Actual source, runtime, both manifests and draft must match before the append.
- A stale head, pending operation, protected funds, breach or duplicate ID fails without append.
- Concurrent binders cannot both commit at one previous head.
- Missing, symlinked, changed or overlapping artifact paths fail closed.
- An unmarked real campaign is rejected before any artifact side effect.

### Task 1: Verify and bind artifacts in fixture campaigns

**Files:**
- Create: `m0/zoo/circle_packing/continuation_binding.py`
- Modify: `m0/zoo/mle_bench_lite/cny_budget.py` (read-only binding accessor).
- Test: `m0/tests/test_openevolve_continuation_binding.py`.

**Interface:** `bind_fixture_continuation(ledger, draft, *, checkout, source_directory, runtime_directory, base_python)` verifies published artifacts and returns a detached recorded binding. It never installs dependencies, creates source trees or accepts a real campaign.

- [x] Test successful real SQLite fixture binding, preserved prior proof/funds, corruption and missing artifacts, stale head and real-campaign refusal, plus concurrent CAS.
- [x] Run tests and observe failure due to missing binder.
- [x] Implement locked source/runtime verification followed by one atomic fixture-only event; do not open cell admission.
- [x] Run binding, preparation and currency regressions; independently review.
- [ ] Commit only verified work and retain the real-campaign guard.
