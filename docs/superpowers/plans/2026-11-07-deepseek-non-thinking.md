# DeepSeek Non-Thinking Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Allow explicitly frozen `reasoning_effort=none` requests without altering historical enabled-thinking requests or authorizing a paid run.

**Architecture:** The existing canonical request builder maps `none` to DeepSeek's disabled thinking flag. The governed provider records the same setting in its immutable manifest, wire request and governance binding; existing replay reconstructs it from the manifest. No pilot or live entry point changes its current default.

**Tech Stack:** Python, pytest, local fixture HTTP.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md` (Candidate provider protocol).

## Global Constraints

- Preserve byte-identical `low`, `high`, and `max` requests and historical bindings.
- Use the original cumulative currency authority; do not initiate paid calls.
- A future pilot must freeze the same new protocol in both arms and distinguish it from the first experiment.

## Review Focus

- Unsupported effort values are rejected before dispatch.
- Canonical request and manifest cannot disagree about the thinking mode.
- Recovery rebuilds identical bytes from the frozen manifest.
- Output and context limits and usage accounting remain unchanged.
- Loopback tests never load or print real credentials.

### Task 1: Explicit disabled-thinking protocol

**Files:**
- Modify: `m0/zoo/mle_bench_lite/provider_protocol.py`, `m0/zoo/mle_bench_lite/governed_provider.py`
- Test: `m0/tests/test_governed_cny_provider.py` and governance bridge tests.

- [x] Test canonical disabled-thinking wire bytes, immutable manifest and sampling binding, local fixture response, unsupported efforts, and unchanged enabled-mode bytes.
- [x] Run the new test and observe failure because `none` is not supported.
- [x] Implement explicit `none` as `thinking.type=disabled`, with effort recorded as `none`; leave all other byte representations unchanged.
- [x] Run protocol and bridge tests, including a real journal recovery path, and independently review the diff.
- [ ] Commit only verified changes; no live calls.
