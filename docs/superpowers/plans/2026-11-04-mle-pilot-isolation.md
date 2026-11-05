# MLE pilot isolation repair implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task; preserve the existing S9 scope and use independent review before completion.

**Goal:** Make the existing real MLE pilot respect its held-out isolation and fail before paid generation when its execution environment is unusable.

**Architecture:** Keep Framework, the existing three CSV tasks and baseline/full protocol. Give the trusted controller a private anonymization key per task/seed, bind the derived input bytes, and probe the exact candidate sandbox before generation.

**Tech Stack:** Python 3.12, standard-library HMAC/secrets, existing Bubblewrap/seccomp and pytest.

**Spec:** `docs/MLE_COMPOSED_V68.md` (anonymous validation rows; candidate receives no split labels or validation answers; full environment verified before provider calls); `docs/ABSTRACTION_ALIGNMENT.md` S9, M8-03/M9-04.

## Global constraints

- Never place anonymization keys in candidate inputs, prompts, public summaries or provider environment.
- Keep one identical dataset identity for each baseline/full pair; retain keys in trusted local experiment evidence for reproducibility.
- Missing or altered keys/inputs during resume fail before model calls; no silent re-randomization.
- Preserve all previous verifier source and historical evidence. Neither repair establishes real benchmark performance.

## Review focus

- Public seed/class counts reconstruct label ordering: reproduce the 396-row metadata attack and reject it after repair.
- Two arms accidentally use different permutations: test paired input manifests with one private key.
- Resume generates a new secret: test persisted secret reuse and refusal on missing/changed secret.
- Secret escapes via manifest or candidate environment: inspect actual generated files and Linux sandbox access.
- Inaccessible Python or missing runtime dependencies survive readiness: exercise a failing real subprocess and require zero provider calls.

### Task 1: Private anonymous prediction order

Files: `m0/zoo/mle_bench_lite/public_train.py`, `composed_agent.py`, `pilot.py`; tests `m0/tests/test_mle_composed.py`, `test_mle_pilot.py` and a focused isolation regression file.

Interfaces: PublicTrainBundle gains explicit keyword `anonymization_key: bytes` (32 bytes). The controller creates one key per task/seed; agent loads a trusted key file outside candidate workspace, or creates a private local key for standalone execution. Candidate visible seed still controls model/search randomness, never anonymous row ordering.

- [x] Add a failing regression that replays the public RNG using only candidate input metadata and recovers all held-out labels on v68.
- [x] Use keyed SHA-256 ordering for the mixed local/official prediction rows; retain the existing split selection and bind the resulting bytes to manifests.
- [x] Persist keys with restrictive permissions outside candidate roots. Pass only key-file locations to trusted agent processes; both arms use the same key. Resume requires existing key and exact dataset identity.
- [x] Verify paired identity, different-key isolation, resume refusal, no secret in public artifacts, and public Framework composition.
- [x] Run all affected tests, update S9 boundaries, commit the repair.

### Task 2: Exact sandbox readiness

Files: `m0/zoo/mle_bench_lite/composed_domain.py`, `composed_agent.py`, `pilot.py`; tests in the same focused regression and existing MLE tests.

Interfaces: SandboxRunner exposes a trusted, bounded readiness probe using its exact interpreter, sandbox mounts and seccomp policy. Pilot reports a structured missing requirement; direct agent refuses before provider generation.

- [x] Add failure tests for inaccessible interpreter and missing candidate runtime imports, asserting zero provider calls.
- [x] Run a minimal trusted program through the real sandbox, with no credentials or network, before paid work.
- [x] Keep portable protocol fixtures explicit; verify actual Linux execution in the full acceptance environment.
- [x] Update operational docs and commit after regression checks.

### Task 3: Verification and continuation evidence

- [x] Run `make check`, `make build`, `make verify-import`; keep exact command outputs and environment boundaries.
- [x] Review the diff independently, fix confirmed regressions, retain failed attempts.
- [ ] Add the next versioned acceptance with all previous commands retained and authentic v68 archive provenance when the repair scope is stable.
- [ ] Push a validation branch when original-repository write access is available; inspect same-SHA Linux CI before any main update.
- [ ] Prepare the six-run real pilot spec after the user supplies model and budget; run zero-model preflight first. No paid run before credentials/data permissions and explicit limits are established.

## Execution record

2026-11-04: seed-replay regression RED→GREEN, readiness-before-provider regressions RED→GREEN. A fixture key was initially 33 bytes, causing 17 targeted failures; corrected to an explicit 32-byte fixture and reran. Final make check: 1,587 passed, 163 Linux deselected, 11 axioms, four examples, 52 tooling; build and immutable import check passed. Independent review found no important remaining repair defect. Linux full acceptance is pending a sandbox-visible interpreter, not replaced by portable checks.

Ruling: this commit restores the existing S9 isolation contract; DeepSeek request compatibility and a shared CNY ledger are a separate subsequent increment. No external provider call is allowed until that budget work is verified. The next versioned verifier will include both increments before production pilot acceptance.
