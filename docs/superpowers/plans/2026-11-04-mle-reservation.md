# Variable-usage proposal reservation implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task. The user authorized autonomous repairs and asked to avoid further routine configuration questions.

**Goal:** Permit valid variable-size proposals within their actual remaining physical budget while preserving accounting and recovery invariants.

**Architecture:** Extend `HierarchicalBudget` with an opt-in operator reservation policy, resolved atomically and recomputed during journal replay. Enable it in the existing MLE profile; no parallel ledger, new execution entry point or provider-specific core rule.

**Tech Stack:** Existing Python 3.12, Decimal, RLock, append-only journal and pytest/local HTTP fixtures.

**Spec:** `docs/superpowers/specs/2026-11-04-mle-reservation-design.md`.

## Global constraints

- The running pilot source and outputs remain unchanged.
- `reservation_modes` permits `operator` only, configured physical units only, and mode `remaining` only. Numeric values remain minimum admission requirements.
- Existing fixed policies and historical verifier source are immutable in meaning.
- Actual costs, unknown usage and true overrun rules remain authoritative. No new spending ledger or automatic paid retry.

## Review focus

- Open reservations must reduce available headroom before another grant.
- Smaller direction/candidate limits must win over global headroom.
- A remaining balance below the numeric minimum must refuse before dispatch.
- Rehashed quote tampering must fail semantic journal replay.
- Real proposal failure after known usage must retain cost; unchanged global overrun rules must remain covered.

### Task 1: Atomic remaining reservation and MLE regression

Files: `m0/core/composition/budget.py`, `m0/zoo/mle_bench_lite/composed_agent.py`, `m0/tests/test_hierarchical_budget.py`, `m0/tests/test_mle_currency_integration.py`.

Validation-discovered prerequisite: `m0/core/x1/store.py` and new `m0/tests/test_x1_store_concurrency.py`; the design addendum defines cooperative interprocess append/snapshot locking. Preserve the full-suite failure as evidence, reproduce deterministic partial-record reads/writes before repair, and rerun the original recovery test. Do not suppress JSON decoding failures.

Interface: add optional JSON `reservation_modes={"operator":{"token":"remaining"}}`; keep public `reserve_operation` and settlement signatures. Internal `_intent` and `_reservation` accept the replay state explicitly, so replay does not consult the live controller's final state.

- [x] Add local HTTP/public Framework regression with first response `prompt_tokens=3190`, `completion_tokens=10204`, `total_tokens=13394`, token budget 60000, iterations 4. Require a real submission and complete cost audit; observe failure before changing production code.
- [x] Add unit regressions for quotes 60000 then 46606, mixed units, competing scopes and open operations, numeric minimum rejection, exact restoration and rehashed quote tampering; observe failures.
- [x] Implement strict option validation and resolution inside the reservation lock; recompute amounts from the event-prefix state during restore.
- [x] Enable the policy in both MLE arms; run focused tests and confirm prior fixed-policy tests remain green.
- [ ] Run full Linux tests/examples/axioms/tooling/build/import checks; obtain one independent whole-change review, fix confirmed issues with failing regressions, commit and preserve a verified local bundle.

### Task 2: Versioned validation and real evidence

Files: new `m0/verifier/v70/`, acceptance wrapper and transition tests; continuation/alignment/experiment reports.

- [x] Preserve authentic v69 certificate/journal with provenance from clean `5fa85d3`; retain all v69 command groups/timeouts and add explicit remaining-reservation coverage in v70.
- [ ] Run v70 from a clean committed source, verify matching fresh certificate/journal and unchanged history.
- [x] Analyze the completed original six-run pilot, retain every failure and official score, export only whitelisted metadata.
- [ ] If the repair is fully verified, prepare a new frozen six-run attempt using the SAME existing campaign ledger and CNY authorization; preserve attempt identities and all cumulative costs.

Validation record: both actual-usage reproductions failed before the repair; ten policy behavior cases failed before implementation. The first focused group passed 75 tests. Independent whole-change review found one Important fractional rounding defect and no Critical findings. Three wallclock/GPU/USD regressions reproduced it; downward-only quote conversion repaired it. The initial expected float literal also rounded upward and was corrected to its actual representable predecessor. Fresh budget/MLE/recovery verification then passed 129 tests (16.85 seconds). The full suite launched before this final repair is intermediate evidence only; final-source full validation remains pending. No new external model request was made during this repair.

The subsequent full suite failed `test_completed_partial_start_resume_is_a_noop`: a live cross-process reader saw an unfinished JSON record. The source stayed unchanged during that run; 1,815 cases passed and one failed, so it is not passing acceptance. New deterministic interprocess/read-snapshot tests failed three cases first; file locks and lock-free snapshot iteration then passed all 11 tests in the new file plus the original recovery file (17.34 seconds). Independent review of this separate X1 repair found no Critical or Important issues and independently passed the same 11 tests with the supported system-path interpreter.

Ruling: stage v70 wiring before the next full pipeline so that its tooling checks cover the new active wrapper in the same run; commit the verified functional repair and transition together, then execute clean-SHA v70. This changes only the task sequencing, not the required full checks, independent review, immutable history or paid-run gate.

Transition verification: 53 wrapper/contract tests and 315 subtests passed. The new v70 retains all 30 prior command groups and adds two unfiltered groups (41 total checks). Full final-source validation and clean-SHA acceptance remain pending.

Final candidate pipeline passed: 1,821 pytest in 371.48 seconds; 60 tooling tests, 11 axioms, four offline examples, wheel/sdist and 1,020-file import verification. Total 374.25 seconds with identical before/after source fingerprints. Official three-task CPU synthetic grading also passed without provider calls. Afterwards only documentation was corrected/updated (one relative link and this evidence/alignment record). Commit, verified bundle and clean-SHA v70 remain the next gates.
