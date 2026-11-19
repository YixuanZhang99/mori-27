# Continuation Reference Authority Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Bind a fixture reference authority to the same versioned first-pair plan and runtime as Mori, under the original shared campaign.

**Architecture:** Reuse the bound fixture plan validator and continuation runtime runner; derive provider and physical budget from that exact plan. Namespace reference cell/authority identity and ensure source, runtime, protocol and limits match before creating authority. Legacy and non-fixture live paths stay unchanged.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

- Only the fixture seed 0 is supported; no real calls or later seeds.
- Never reuse original pilot source/runtime for a new version; no credentials persisted.
- Both reference main/control providers use the frozen `none` protocol.
- This task does not by itself execute or independently audit reference search.
- [x] Write tests for bound reference authority, provider protocol, mismatches and no external calls.
- [x] Verify red, implement and run legacy regression; independently review and commit.
