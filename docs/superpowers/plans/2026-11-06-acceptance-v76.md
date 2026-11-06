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
