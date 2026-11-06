# Continuation Mori Loopback Execution Plan

> **For agentic workers:** Use superpowers:executing-plans, systematic debugging and test-driven development.

**Goal:** Execute a versioned fixture Mori search through the actual Framework, locked runtime, loopback provider and shared currency ledger.

**Architecture:** Prepare source from the current committed Git tree and runtime from the local offline uv cache. Bind to a fixture campaign, start and claim the versioned seed-0 clock/worker, compose the controller, and run its fixed six iterations using only a local fake provider. Verify physical requests, protocol, measured ledger state and evidence; keep the real campaign gate closed.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

- A test must not use or print real credentials, connect externally, or mutate the real campaign.
- The test must use actual framework and candidate evaluator; no claim of benchmark performance.
- Preserve original ledger claims and require no unresolved or protected currency at completion.
- Fix errors at their source; retain failure evidence and do not retry uncertain paid work.
- [x] Construct and run loopback fixture; identify and fix integration failures.
- [x] Verify no external calls, currency accounting and six-cycle behavior where completed.
- [x] Review, regressions, document precise limits, commit and push.

The controller is imported by the current pytest process, not launched from the frozen source; replay is in-process and does not demonstrate process recovery. The full test requires `MORI_TEST_OFFLINE_CACHE`.
