# Evidence-led delivery plan

> **For agentic workers:** Use superpowers:executing-plans for implementation. This plan coordinates three user-approved deliverables; retain the existing M7 plan for its unfinished review and acceptance. Write a focused implementation design for a newly discovered protocol change before changing that protocol.

**Goal:** Deliver a reproducible real MLE report, two explicitly scoped classic-method reproduction packages, and a controlled measurement of governance benefits and costs.

**Architecture:** Reuse Framework.evolve/inspect/replay and the existing task adapters, durable execution, physical accounting and shared currency authority. Freeze the method, runtime, dataset, evaluator, model, budget and selection contract for each experiment. Derive public reports from original run evidence; do not infer benchmark effectiveness from framework tests.

**Tech Stack:** Existing Python, pytest/uv, Git, official task graders, protected local data and credentials. No replacement framework or new paid service is implied.

**Spec:** User-approved three-deliverable direction of 2026-11-04; original requirements remain docs/ABSTRACTION_ALIGNMENT.md and autoresearch-fw/RUBRIC.md. The capability audit is research/2026-11-04-capability-evidence-comparison.md. This plan changes order, not the full Goal's completion conditions.

## Global constraints

- Preserve the original Goal and all A/B/C requirements; completion of these deliverables alone does not automatically complete v1.0.
- Continue codex/m7-construction. Do not create a branch per subtask. Keep milestone commits, remote synchronization and rollback bundles. Main integration retains the original platform gates.
- Preserve the user's cumulative CNY 200 model budget and existing spending history. Read the current ledger before paid work; never reset it, create a fresh allowance, or treat a prior snapshot as current balance. Historical settled upper bound was CNY 3.242064, not a supplier invoice.
- Keep credentials in their existing private locations. Never display, copy into reports, or commit their contents. Model identifier returned by the provider is recorded exactly; do not convert an alias into an unverified version claim.
- Keep failed and interrupted experiments. New software cannot retroactively repair their scores, costs or status.
- A fixture, adapter, method-shaped example, real smoke run, and completed benchmark are distinct evidence classes.
- No guaranteed score improvement, superiority, statistical significance, or two-hour completion promise. Honest null or negative results are publishable outcomes, while the original success criteria remain open when unmet.
- New architecture work must identify the deliverable it unblocks. Defer unrelated expansion without erasing the original backlog.

## Review focus

- A legacy method name must not certify a newer runtime or full-paper fidelity. Bind each run to the actual algorithm configuration and record omissions.
- A refused or failed run must remain in the experiment matrix. A rerun is a separate attempt; never replace it silently or choose seeds after seeing scores.
- Official hidden scores must not influence candidate selection, experiment tuning, reflection or another arm. Freeze selection before grading.
- A governance comparison must hold the search algorithm, target, model, data and resource limits constant. Existing greedy-versus-population experiments cannot isolate governance effects.
- Aggregate cost must include proposal, repair, evaluation, calibration and resident controls where incurred; unknown costs and estimate-only token admission must retain their real limitations.

## Current evidence and prerequisite

- Remote ec47899 contains M7 Tasks 1–5. Local candidate 8b5e018 adds v74 acceptance; 2,257 Linux tests, 84 tooling tests, axioms, examples, build and import checks passed with unchanged source.
- The first clean v74 run was deliberately stopped when the user paused development. It has no completed certificate. The single whole-branch review was interrupted and is now resumed, not replaced by another review.
- The existing MLE composed_agent still constructs schema-1 baseline/full profiles. Its historical real scores do not validate the new M7/v9 runtime. Any new wiring must be explicit and independently checked before paid execution.

### Task 1: Close the required M7 review and acceptance

**Files:** Existing docs/superpowers/plans/2026-11-04-m7-execution.md Task 6; its review ledger; research/experiments/2026-11-04-m7-integrated-acceptance/.

- [x] Finish the same fresh whole-branch review of f7ab273..8b5e018. Reproduce and fix Important/Critical findings; record decisions and deferred minors.
- [ ] Run required checks on the final source and clean v74 acceptance. Expected: all 55 checks, fresh certificate/journal, exact committed/executed source binding and unchanged historical evidence.
- [ ] Push the existing branch; independently verify same-SHA hosted artifacts; preserve a rollback bundle. Keep main and full-framework status separate.

### Task 2: Freeze the real MLE experiment protocol and integrate its runtime

**Files to inspect/change as required:** m0/zoo/mle_bench_lite/composed_agent.py, pilot.py, provider.py, governed_provider.py, governed_currency.py, composed_domain.py; docs/MLE_COMPOSED_V68.md; new focused integration design and tests under m0/tests/.

- [ ] Trace current candidate generation, domain scoring and budget ownership from the public entry point; identify exactly how the selected M7 runtime will replace schema-1 construction without a second unmetered generator or duplicate evaluation.
- [ ] Freeze one protocol for both arms: spooky-author-identification, leaf-classification, nomad2018-predict-transparent-conductors; initial seed 1; 6 run slots. Keep existing greedy/full definitions explicit. Bind exact splits, official revision, model, budget, selection and stop semantics before results exist.
- [ ] Write focused integration steps and RED→GREEN tests for the discovered seams. Expected: both arms use the declared runtime through the public API; construction is charged once; original candidate predictions are reused; held-out labels stay private; refusals retain known costs and eligible prior results.
- [ ] Verify current official model/service limits and price contract before paid work. Perform no-paid-call preflight with the existing credentials, datasets and ledger. Keep estimate-only token admission explicitly labeled; do not silently raise the existing per-run limit to make a run pass.

### Task 3: Produce the real MLE report

**Files:** New immutable attempt directory under research/experiments/; existing pilot reporting/usage audit; docs/FRAMEWORK_STATUS.md.

- [x] Run the frozen 3-task × 2-arm × 1-seed diagnostic matrix. Preserve all six terminal outcomes, receipts, actual model identity, selected submission hashes and official scores when valid. The completed `a6b5826` subset and both earlier failed attempts are documented under `research/experiments/`.
- [x] Independently reconcile the run matrix, physical/provider usage and shared CNY authority. All six completed slots and official report hashes were rechecked without external requests; the shared ledger was unchanged. The provider identifier is a mutable alias, not a verified immutable snapshot.
- [ ] Once diagnosed prerequisites are stable, extend the preregistered protocol to seeds 1, 2 and 3, totaling 18 slots. The 18 slots have now been run and independently audited, but as two separately frozen batches: the seed 2/3 batch was frozen after seed 1 results, and its arm order differs from a single `[1, 2, 3]` matrix. Preserve both batches and do not present them as one pre-result preregistration.
- [x] Publish per-task/per-seed scores, paired deltas where valid, failure rate, actual token/wallclock/currency coverage and reproduction command. Three seeds are preliminary evidence, not automatic statistical significance or a 22-task Lite certification. See `research/experiments/2026-11-05-m7-real-mle-three-seeds/` for both batches and their limitations.

### Task 4: Deliver GEPA and FunSearch reproduction packages

**Files:** New method-specific designs/plans, profile/plugin implementations as needed, public task configurations, and research/experiments/ result packages. Preserve legacy profiles and their labels.

- [ ] Pin primary implementation/paper revisions and one feasible public workload for each method. Compare our actual mechanisms against the reference before selecting a fidelity claim.
- [ ] For GEPA, specify candidate retention/parent selection, feedback and reflection, evaluation sampling and acceptance. For FunSearch, specify program skeleton, editable region, archive/signature grouping, island selection/migration/reset and evaluation. Explicitly document which reference features are required, optional or omitted.
- [ ] Implement missing required mechanisms through the planned module/configuration interfaces, with behavioral tests and no cosmetic renaming of the old greedy loop. Prove public-entry execution and configuration restoration before paid experiments.
- [ ] Package each method with a runnable command, fixed task/evaluator/data identity, model/budget/seed settings, original outputs, scores and fidelity limitations. Report a bounded adaptation when the reference protocol cannot be matched; leave RUBRIC B4 open until an actual public reported interval is reproduced.

### Task 5: Measure governance benefit and overhead

**Files:** New focused experiment protocol and report derived from the existing accounting/receipt/selection interfaces; add runner support only where the protocol requires it.

- [ ] Freeze a same-search governance comparison independently of the MLE greedy/full comparison. Preserve essential spending limits, isolation and data protection in every arm; vary only the declared research-governance mechanisms.
- [ ] Report final task quality, admitted candidates, actual costs, control/calibration overhead and failure rates at equal declared budgets. Use paired seeds and retain null/negative results.
- [ ] Separately exercise recovery cuts and receipt reconciliation. Report duplicate calls/charges and recovery behavior as mechanism evidence, not as benchmark score gains.
- [ ] Calculate RUBRIC B5's admitted_per_usd ratio only when price and admission units are comparable and fully measured; otherwise publish the measured coverage and leave that criterion open.

### Task 6: Publish one coherent capability and results entry

**Files:** README.md, docs/FRAMEWORK_STATUS.md, method/run documentation and immutable experiment summaries.

- [ ] Show a method × task × runtime × evidence-level table with links to exact code, commands and results. Separate framework tests from real runs and reference-author results from our own.
- [ ] Update the existing PR chain and synchronize verified milestones. Integrate only after original gates; clean historical branches after integration while retaining rollback references.
- [ ] Audit the full original Goal against A/B/C and alignment requirements. Keep unresolved concurrency, A7, full-suite/time-budget experiments and other requirements open; do not replace them with this smaller delivery plan.

## Execution order and status

Task 1 is active. Tasks 2–3 are the next product-facing deliverable; Task 4 follows, then Task 5. Task 6 is updated alongside each deliverable. No new paid run has been launched under this plan. The user restored the existing Goal to active after approving this direction.
