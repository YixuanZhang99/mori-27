# Continuation Frozen Worker Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development.

**Goal:** Run the first Mori continuation fixture using the bound source and interpreter in an independent process, with only loopback credentials and the original fixture ledger.

**Architecture:** Extend the existing fixture worker's authority preparation for schema-3 continuations, reusing bound-artifact verification and the original named cell clock. The existing fixture entry continues to reject non-fixture campaigns and non-loopback services. A subprocess integration test launches the committed frozen worker with an explicitly filtered environment; its sandbox and in-process replay remain within the fixture boundary.

**Spec:** `docs/superpowers/specs/2026-11-07-openevolve-campaign-epochs.md`.

- No real credentials, non-loopback providers or non-fixture campaigns.
- Exact original deadline, plan, source, runtime and campaign identity; no restart of a paid worker.
- Record six search attempts and shared-ledger settlement, with process paths proving frozen source/runtime.
- This standalone process is not the whole-cell supervised live path, a recovery test or a benchmark.
- [x] Test fixture authority preparation and altered identities, then implement worker.
- [x] Run frozen-source subprocess with real offline runtime and fake provider; verify accounting and replay.
- [x] Regress legacy fixture entry, review, document limits and push.

## 2026-11-19: use the existing controller supervisor

The frozen and paired tests still supplied a synthetic worker claim and invoked
the worker directly. Continue the same fixture milestone by routing schema-3
Mori cells through `launch_fixture_controller`; keep the legacy and live paths
under their existing contracts.

- [x] Reproduce the versioned cell rejection before changing the supervisor.
- [x] Validate the bound continuation source/runtime before claiming the worker;
  preserve the original cell ID, deadline and campaign. Protect both complete
  artifact bundles from overlap with supervisor output.
- [x] Replace synthetic claims/direct subprocess calls in the frozen and paired
  fixture tests with the supervisor and assert the original process/claim link.
- [x] Verify rejection of mismatched identities, expired clocks and altered
  artifacts before a claim or launch; retain legacy regression coverage.
- [x] Fix the observed portable-test classification and obsolete effort
  expectation; supply the already-populated offline uv cache to Linux acceptance.
- [x] Run focused portable checks and independent review (no remaining findings).

Final integration gate: full portable checks and committed-source Linux
acceptance, including the formerly skipped frozen/paired cases. Track the exact
commit's results in [PR #9](https://github.com/YixuanZhang99/mori-27/pull/9);
focused results do not substitute for that gate.

This is fixture controller deadline supervision. It does not certify cgroup
containment of every descendant, complete reference iteration accounting,
independent continuation geometry replay, or readiness for paid continuation.
