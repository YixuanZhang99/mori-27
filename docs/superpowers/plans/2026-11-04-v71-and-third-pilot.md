# v71 and third real pilot implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Keep all historical verifiers and failed experimental evidence unchanged.

**Goal:** Certify the implemented provider admission/refusal repair with additive versioned checks, then execute the same six-run pilot using the existing authorized CNY200 campaign.

**Architecture:** Archive exact v70 local evidence, copy the historical verifier into v71 with all old command ASTs/timeouts preserved, add one unfiltered regression group, and advance the active wrapper/CI. Run acceptance from a clean commit and launch only its frozen source. Native/worktree resident controls remain the next separate feature.

**Tech Stack:** Existing Python/unittest/pytest acceptance tooling, git bundles, frozen pilot launcher and SQLite currency authority.

**Spec:** `research/2026-11-04-provider-token-bounds.md`, `docs/superpowers/plans/2026-11-04-provider-token-admission.md`, `docs/ABSTRACTION_ALIGNMENT.md`, `autoresearch-fw/RUBRIC.md`.

## Global constraints

- v1–v70 verifier sources and existing historical records are immutable. v14 remains rejected; v43 remains handled by its corrected successor.
- Archive only authenticated v70 output from clean `aedede3c2b78a5c2b57074c70d510af710f5af4e`; label it local, never hosted CI.
- Keep every v70 command and timeout. Add `provider_input_admission_refusal_and_durable_replay`, timeout 480 seconds, running full provider/currency-integration/composed-budget/composed-recovery test files without filters. Expected total: 42 checks, 33 commands plus 9 history/source checks.
- No initial v71 certificate or journal is committed. Certification of the new scope requires both the new group and the whole run to pass. Input-estimate hard guarantee and external provider execution flags remain false.
- Third pilot: same 3 tasks × baseline/full × seed1; token60000, iterations4, max output16384, wall600s, solution120s. Only the validated software/source changes. Do not optimize task algorithms against official hidden scores.
- Existing CNY200 ledger only: campaign `18509cd4f3514d51ae79aa3aceaf1779`, settled3242064 microCNY / 33 operations before attempt3; no pending calls. Never reset, replace or recreate it.
- Credentials may be parsed internally by the authorized launcher only, never printed or copied. Fresh output directories and exclusive attempt marker; no automatic retry.

## Review focus

- Lost prior command/timeout or mutated historical verifier bytes must fail transition checks.
- Archived certificate and journal must match each other and original SHA-256 hashes.
- Stale or partial v71 output must not pass; retain existing wrapper negative tests.
- A prior live/unknown operation must block another launch; inspect live handles rather than stale status files.
- Frozen source, ledger, official dataset and price identities must be checked before paid dispatch.

### Task 1: Additive transition

Files: new `m0/verifier/v71/{verify.py,README.md,v70-provenance.json}`, archive `m0/verifier/v70/LAST_RUN.json`, `m0/verifier/runs/v70.jsonl`; append verifier index; update active wrapper, CI label, Makefile/docs; extend transition tests and advance wrapper fixture version.

- [x] RED: Tests require exact archived v70 hashes and matching41-check certificate/journal; preserve all old command ASTs; execute the new unfiltered group at480s; certificate scope flags remain conservative.
- [x] Implement additive verifier and active wiring; validate archived outputs against their independent provenance first.
- [x] GREEN: Run full tooling suite; confirm old verifier source and history bytes unchanged except adding authenticated missing v70 artifacts.
- [ ] Independent review of this transition; fix any important findings. Commit after targeted verification, then run clean-source full v71 acceptance (includes full pytest/axioms and every historical command group).

### Task 2: Clean acceptance and frozen third attempt

Files: local outputs and launch artifacts outside the code worktree; public whitelisted validation report after completion.

- [ ] Capture clean before/after commit and evidence hashes; require all42 unique checks, matching certificate/journal, source history unchanged, wrapper exit0.
- [ ] Verify current official model/price contract matches the existing frozen campaign. Retain source provenance and readonly archive manifest.
- [ ] Build new attempt3 plan and launcher from the established workflow; fix source metadata assignment, update exact previous cumulative amounts, use exclusive new paths/marker and current completed acceptance provenance.
- [ ] Run production preflight and launch once; keep actual process/session handle. If terminal, audit all six outcomes, charges and official frozen reports; if live, keep monitoring the same process while doing independent development.
- [ ] Commit public evidence and verified complete-history rollback bundle. Push only when repository permission is actually writable; main requires same-SHA hosted CI.

### Task 3: Continue full release scope

- [ ] Pin a task-level schema/interface plan for resident IID-RS plus seven-account/protected-budget runtime based on the committed design; do not treat a six-run diagnostic as C1/C3/B1 completion.
- [ ] Preserve complete A/B/C/D release requirements and latest experiment limitations in continuation state.

Task1 review: fresh reviewer v71_transition_review found no Critical/Important/minor issues; independently verified64 tooling tests,242 unchanged historical files, all32 prior AST/timeouts, exact archive hashes and scope gating. Clean-SHA runtime acceptance remains next.
