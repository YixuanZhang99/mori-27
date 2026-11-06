# Continuation Reference Worker Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Execute the fixture reference worker under its versioned cell clock and bound source/runtime, preserving the original campaign.

**Architecture:** Route schema-3 fixture worker checks through the bound continuation verifier before and after the worker; leave original frozen-pilot checks intact. Update reference worker's cell parsing and host runtime's source/runtime checks to use the same binding. Exercise a real isolated worker and then an end-to-end loopback reference cell.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

- Fixture seed 0 only; non-fixture and later seeds remain closed.
- Validate exact source/runtime manifest, campaign, clock and bound plan before worker claim; reverify after process completion.
- Worker uses one original clock and claim; no provider credential enters its sandbox.
- Preserve old pilot behavior; failed or uncertain worker remains unresolved.
- [ ] Test real sandbox worker and reject tampered source/runtime before claim; implement scoped version handling.
- [ ] Run original worker regressions, independent review, and loopback reference search.
- [ ] Document evidence scope and push.
