# Continuation Controller Binding Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Make the Mori controller recognize a fixture continuation's bound first cell and its frozen reasoning protocol without changing old or live campaigns.

**Architecture:** Extend the existing draft validator with a strictly fixture-only branch that checks the stored bound draft, artifact assertion and qualified cell identity. Select the provider's reasoning effort from that verified timed plan for both main and control providers. Preserve the original low-effort behavior for legacy and recorded-only paths; no continuation live entry is opened.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

## Constraints

- The original campaign, old pilot, and real-provider gates remain unchanged.
- Only seed 0 of a fixture continuation with a verified binding may validate; no later-seed admission.
- Validate full canonical draft, campaign identity, declared cell, plan digest, and recorded artifact assertion.
- Both main and independent-control providers must use the bound plan's `none` setting; legacy uses `low`.
- This is not the complete supervised runtime, provider execution or real benchmark.

### Task 1: Bound plan validation and frozen provider protocol

- [x] Add tests for qualified fixture validation, tampering, mismatched campaign/ref and later-seed rejection.
- [x] Add tests for provider binding and recorded main/control reasoning, preserving old behavior.
- [x] Observe failing tests, implement minimal fixture-only changes and run regressions.
- [x] Independently review, document limits and commit.
