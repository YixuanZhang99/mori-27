# Campaign Continuation Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Read the original campaign, version identity and monetary state at one pinned journal head before designing continuation; never mutate or authorize a run.

**Architecture:** Extend the existing SQLite-backed campaign authority with one read transaction returning pilot, runtime, audit, cell claims and global monetary state. A stale head fails, and callers receive detached values. A later atomic bind must independently recheck everything in its own write transaction.

**Tech Stack:** Python, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`

## Global Constraints

- Preserve the existing one-campaign ceiling and complete original history.
- No new event, source binding, budget, or paid authority is created by this read.
- A preflight result alone cannot authorize migration or work.

## Review Focus

- Stale or malformed head must fail instead of returning mixed state.
- Pending calls and protected balances must be visible together with original bindings.
- Mutating a returned structure must not affect journal state or future reads.
- Legacy journals without pilot or audit must retain their original meaning.
- The method must not disclose provider credentials or prompt contents.

### Task 1: Consistent campaign continuation inventory

**Files:**
- Modify: `m0/zoo/mle_bench_lite/cny_budget.py`
- Test: `m0/tests/test_openevolve_continuation_inventory.py`

**Interface:** `CampaignBudget.circle_continuation_inventory(*, expected_head)` returns a detached dict of head, policy identity, original pilot/runtime/first-pair audit identity and cell claims, plus global settled/reserved/protected/pending/breaches. No event is appended.

- [x] Test legacy ledger, frozen pilot/runtime, pending and protected amounts, detached results, stale head, and unchanged journal.
- [x] Observe new tests fail because the method is absent.
- [x] Implement one transaction and exact head comparison; do not authorize new cells.
- [x] Run inventory, currency governance and budget tests; independently review.
- [ ] Commit verified changes; version binding and artifact durability remain separate work.
