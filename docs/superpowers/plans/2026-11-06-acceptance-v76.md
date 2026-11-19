# Linux acceptance v76 implementation plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven-development.

**Goal:** Preserve the complete v75 acceptance while allowing full Linux regression enough time on hosted runners.

**Architecture:** Append v76 without changing the v75 verifier or its historical evidence. Keep every v75 command and check, raise only the complete-regression timeout from 900 to 1500 seconds, add a check that authenticates v75 source files, and bind the new runner and independent verifier to the exact committed source. Give the outer runner 3000 seconds and the CI job 60 minutes.

**Tech stack:** Python 3.12, pytest, unittest, GitHub Actions.

**Spec:** `docs/CURRENT_GOAL.md`; append-only verifier history in `m0/verifier/README.md`.

## Constraints

- Preserve all checks and no-skip behavior. Never alter historical verifier source or archived evidence.
- Keep the existing v75 command available for historical use. Do not claim an acceptance passed before a real run completes.
- Existing v75 contract tests must continue to validate their original contracts; adapt only active CI assertions where necessary.

## Tasks

1. Add failing tests that compare v76 to v75 by AST, require the new timeout, old-source hash verification, 57 distinct checks and exact-source binding. Run them and record the failure.
2. Append the v76 verifier, frozen v75 manifest, runner and independent artifact verifier. Update active CI and Makefile, retain the v75 target, and add the index entry. Run the new and existing contract tests.
3. Run `make check` on a fixed commit; review the version diff and source binding. Push the existing method branch and let the exact-head CI run. Do not report a remote pass without its result.

## Follow-up: preserve Git identity in the isolated execution copy

The first complete local v76 run reached the full-regression deadline but failed three tests: the copied source had no Git checkout, while OpenEvolve fixtures require commit identity and a local clone. Reproduce this with an acceptance fixture that checks the execution commit and excludes a fake untracked secret. For v76 only, create a local, non-hardlinked checkout of the exact commit; retain the original source and execution-manifest binding and the v75 default copy behavior. Verify both wrapper generations, rerun the three failing cases in an isolated checkout, then rerun the complete acceptance and publish its actual result.

## Follow-up: measured active v76 limits (2026-11-19)

The unfiltered Linux diagnostic [run 44476673632](https://github.com/YixuanZhang99/mori-27/actions/runs/44476673632), at commit `7bd740e6bdc9d822890c318f794b133cf5951270`, completed with **3398 passed, no skips, in 1598.90 seconds**. The offline dependency cache was enabled, so the continuation integrations ran. This establishes the full-suite duration; it is not a certificate for the revised v76 harness.

Adjust the active v76 full-suite limit to 2100 seconds: `ceil(1598.90 * 1.25 / 300) * 300`. Set the outer limit to 3300 seconds: `ceil((2100 + 957 + 120) / 300) * 300`, using 957 seconds of observed other verifier work and 120 seconds of margin. The hosted job remains at 60 minutes. Keep every command, all other group limits, the 57 checks, no-skip enforcement and exact-source artifact verification. Production cell deadlines, stage limits and paid campaign budgets do not change.

This updates the active v76 harness rather than adding another verifier generation. Preserve v75 source bytes, its entrypoint and every historical result, including the original v76 timeout failures. The active contract expectations must fail at 1500/3000 and pass at 2100/3300; run `make tooling`, then run the revised committed v76 acceptance and independently verify its artifacts before claiming acceptance.

Local verification: both updated deadline contract tests failed against the old limits and passed after the change. `make tooling` passed all 154 tests in 8.349 seconds, including historical-source, required-check, wrapper and independent artifact-verifier regressions. The revised committed Linux acceptance and artifact verification remain pending.
