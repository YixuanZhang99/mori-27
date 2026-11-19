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

The first committed Linux runs on 2026-11-19 exhausted the unchanged 1,500-second
full-regression timeout. A separate six-case diagnostic identified repeated
per-file relative-path construction during complete artifact verification.
Compute each directory's relative prefix once and remove the consecutive
duplicate sandbox precheck; retain full prelaunch/postexecution byte checks.
The temporary manual profiling job is removed after collecting its evidence.
The final same-commit acceptance gate above remains required.

## 2026-11-19: close the observed namespace-init startup race

Candidate `29e0cb8` passed push v76 (57 checks, 3,398 tests); its exact committed
source binding was independently verified. The identical-tree PR run failed
`test_existing_executor_crash_leaves_lost_result_and_stops_detached_child`:
the same non-zombie process identity remained alive after five seconds. Preserve
both runs; neither retrying nor extending the assertion deadline resolves this.
The process identity, journal, wrapper, sandbox, seccomp and failed test files
were unchanged between this continuation's base `2c7fb7f` and `29e0cb8`.

Bubblewrap 0.9.0 forks its command before its separate namespace init arms
`PR_SET_PDEATHSIG` in `do_init` ([upstream source](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c)).
A controlled FIFO barrier before that registration reproduced continued child
execution after wrapper death on isolated arm64 containers with Bubblewrap 0.8.0
and Ubuntu's 0.9.0 package. Captured namespace/birth identities and complete
cleanup are retained in local development evidence. These architecture-neutral
diagnostics do not certify the x86_64 seccomp policy or prove the original CI
process escaped its PID namespace.

Use `--as-pid-1` only with a fixed, trusted init executed by read-only system
Python with isolated imports. It must verify PID 1 and inherited SIGKILL parent
death protection, disable process-memory inspection, then fork the original
command, reap orphaned children and preserve its exit status. The untrusted
command must never become namespace init or control its lifecycle binding.
Validate fail-closed bootstrap, argument/environment and exit-status behavior,
orphan reaping, wrapper crash/timeout and payload-local signal changes with and
without seccomp; finish with fixed-commit full acceptance and independent review.

This closes the observed command-ready-before-init-armed window. It does not
prove Bubblewrap's earlier pre-exec parent-death window is closed, or certify
whole-cell cgroup containment. Existing live/continuation gates remain in force;
reference-host supervision and the remaining method delivery work stay open.
