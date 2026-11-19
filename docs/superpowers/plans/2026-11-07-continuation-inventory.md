# Continuation Inventory Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Show all six cells for a separately bound continuation at a pinned campaign head without treating claims as results.

**Architecture:** Extend the existing atomic claim inventory with the detached bound draft and artifact identities. A read-only continuation snapshot validates the caller's full draft and reference against that same snapshot, enumerates its six declared IDs, and marks claimed cells unresolved. It never calls a provider or authorizes a seed.

**Tech Stack:** Python, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md` and `2026-11-07-openevolve-matrix-report.md`.

## Constraints and review focus

- Same original campaign and exact pinned head; stale head and changed draft rejected.
- Original and other experiments never appear as cells of this experiment.
- Six declared cells are always present, including unclaimed and unresolved cells; no score or cost is inferred.
- Results are detached; report has no writes, model calls or execution authority.
- Actual evidence reduction and real campaign migration remain separate unfinished work.

### Task 1: Atomic continuation claim snapshot

- [x] Test unclaimed and claimed seed-0 cells, six IDs, isolation, changed draft/head, detached values and no ledger mutation.
- [x] Confirm the new tests fail before implementation.
- [x] Implement snapshot against the single pinned ledger projection.
- [x] Run focused regression and review; document limits and commit.
