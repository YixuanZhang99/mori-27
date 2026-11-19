# OpenEvolve delivery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inline execution and one final whole-branch review preserve the execution method already authorized for this sequence.

**Goal:** Deliver C05 O1–O5 as a serial adapted OpenEvolve recipe in the public Framework, with real circle-packing vendor/Mori results and complete failure/cost evidence.

**Architecture:** A thin host adapter owns the pinned ProgramDatabase and PromptSampler. The existing Framework owns construction, invocation budgets, evaluation, admission and original records; no second Mori optimizer loop. A separate pinned upstream controller supplies the external comparison arm.

**Tech Stack:** Existing Python >=3.11, JSON profiles/registry, current dev/pilot environments, vendored OpenEvolve, numpy and Bubblewrap/seccomp. No new environment installation is assumed.

**Spec:** docs/specs/classic/OPENEVOLVE.md and COMMON.md; docs/superpowers/specs/2026-11-05-openevolve-design.md. Source findings docs/superpowers/specs/2026-11-05-openevolve-source-notes.md and actual byte audit /tmp/mori-c05-vendor-audit.json.

## Global constraints

- Preserve the nine logical module owners and Framework.from_profile/evolve/inspect/replay; no new optimizer loop, ledger, scheduler or certificate system.
- Pin upstream 5153a7d74ee615b7090ec52903629870ecdacdf1. Circle packing is exactly 26 nonoverlapping circles in the unit square; target normalization is 2.635.
- Four islands, population60/archive25, complexity/diversity features, ten bins, exploitation .7/exploration .2, elite .3. Full migration interval50; pilot interval2, rate .1, explicitly disclosed.
- Diff mode and evolve-marker enforcement are enabled; two same-parent construction attempts maximum, including their failed usage. Preserve upstream partial-match behavior.
- Use absolute cascade thresholds [.5,.75], two actual stages, at most60seconds per stage in both arms. No later-stage call or charge after early exit.
- Async quotas remain a declared fidelity gap. Embeddings, novelty LLMs and knowledge imports are disabled. Current default profiles/prompts/manifests remain unchanged.
- Every paid call uses the original cumulative ¥200 campaign, supplied by path; do not print/copy secret contents. No paid C05 run while Arbor is active.
- Publish only after Arbor has merged; maintain main plus one active method branch. Until then, this plan/design stay outside the frozen Arbor source.

## Review focus

1. A migrant UUID is sampled but has no new evaluation: resolve it to the original candidate/evidence, retaining host identity/island without inventing execution. Task1.
2. New-process recovery changes hash order, cached diversity, timestamps or RNG: preserve next-step behavior or fail on a changed environment before dispatch. Task1.
3. A model returns a partial/no-op/outside-marker patch or full code instead of a diff: retain exact failures, bound repair and never change the frozen parent. Task2.
4. Candidate-controlled geometry output is nonfinite, oversized, a symlink or forged metrics: reject it without host execution/unpickling or unintended data access. Task2.
5. A spawned reference worker receives a billed failure, unknown usage or a secret-bearing config: account/stop correctly, keep credentials out of persisted artifacts, and never overspend the common ceiling. Task3.

## Task 1: Host selection, population and recoverable state

**Files:** Create m0/core/composition/openevolve_adapter.py, m0/core/composition/openevolve_policy.py; tests m0/tests/test_openevolve_state.py. Reuse m0/core/openevolve_interop.py; change its versioned public schema only if a wrapper cannot preserve compatibility.

**Interfaces:**
- OpenEvolveAdapter(config: dict, *, seed: int, source_binding: dict).
- register(candidate_id: str, artifact: str, metrics: dict, evidence_ref: str, *, iteration: int, selection: dict | None) -> dict: add a measured program to the real host and return method transitions.
- select(candidate_id: str, eligible_ids: set[str]) -> dict: one host parent, source candidate, inspiration host/source IDs, target island and before/after state references.
- abandon(candidate_id: str, reason: str) -> dict: settle a failed pending proposal without registering a measured program.
- checkpoint_state() -> dict; restore_state(state: dict, original_events: list[dict]) -> None. State is checked against original operations, not trusted as authority.
- OpenEvolvePolicy implements the current observe/select/ideate/absorb protocol and delegates host state; Task2's coordinator owns trusted artifact/evidence binding.

- [ ] Add O1 tests using actual ProgramDatabase: separate feature cells retain elites, cell replacement retains source lineage in method history, and a valid non-incumbent remains selectable. Add O2: actual migration changes destination sampling and migrant selections resolve to original evaluated source candidates.
- [ ] Add a fresh-process continuation test with PYTHONHASHSEED=0: uninterrupted versus restored next parent/inspirations, feature coordinates and migration memberships are identical; no provider calls. Include original diversity/reference/insertion-order regression demonstrated by /tmp/mori-c05-snapshot-probe.py. Changed hash fingerprint and tampered RNG/cache/order/source must fail before selection.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=m0 /usr/local/share/mori27-local/dev/bin/python -m pytest -q m0/tests/test_openevolve_state.py`; confirm failures identify the missing adapter/state behavior.
- [ ] Implement the adapter over real host calls and the existing snapshot envelope. Preserve primary lineage separately from inspirations; track host migrant IDs to original evidence. Scope host RNG handling, capture nondeterministic UUID/time values, and reconstruct with the original values. Preserve cache/reference and insertion state; do not use a bare to_database round trip as recovery.
- [ ] Project eligibility into sampling without deleting original history. Add an explicit test where no eligible host source remains; it must stop without selecting a pruned/exhausted candidate. Any host normalization needed for deterministic restore is versioned and disclosed.
- [ ] Run the focused tests plus existing openevolve interop/frontier tests; commit the independently tested host adapter. Do not register an incomplete runnable profile yet.

## Task 2: Diff construction and true cascade in the public Framework

**Files:** Create m0/core/composition/openevolve_runtime.py and openevolve_construction.py; m0/zoo/circle_packing/{__init__,domain,profile}.py; m0/config/profiles/openevolve_program.json. Modify construction.py, defaults.py and runtime.py only at the required construction/registry/coordinator seams. Tests: m0/tests/test_openevolve_recipe.py and test_circle_packing.py.

**Interfaces consumed:** Task1's adapter methods and immutable selection records.

**Interfaces produced:**
- OpenEvolveCoordinator(owner): select(candidate_id, frontier, budget), materialize(candidate_id), record_evaluated(candidate_id), abandon(candidate_id, reason), restore(checkpoint, original_events). It resolves original proposal code and dev evidence, not model-authored bindings.
- OpenEvolveMaterializer(roles, *, seed_program, max_attempts=2): uses the existing PromptMaterializer attempt loop for mutation and deterministic zero-token seed materialization.
- PromptMaterializer.build_request(plan_value: dict, *, hypothesis: str, attempt: int, feedback: list[str]) -> dict and decode_output(raw: str, plan_value: dict) -> dict are deterministic overridable seams. Defaults preserve existing request bytes/results and accounting. Mutation decoding returns the full patched executable artifact.
- CirclePackingDomain(workspace: Path, *, runner, stage_timeout: float=60): validate_request(request), evaluation_context_for(request), async evaluate(proposal, request) -> EvalResult, restore_evidence(rows). Stage and geometry artifacts are bound to candidate/program/evaluator identities.
- build_profile(*, seed: int, iterations: int, call_token_bound: int, migration_interval: int=50) -> dict. Live composition adds the existing currency bridge and fresh independent seed control in Task3.

- [ ] Write a public Framework fixture that evaluates the original seed, uses a real source-bound SEARCH/REPLACE patch, executes the true geometric evaluator, registers the child in host cells/islands, samples it in a later round and replays with zero external calls. Require primary parent versus inspiration references to stay separate.
- [ ] Add O4 cases: malformed/no-match/identical patch exhausts two attempts and charges both; a partially matching patch follows pinned behavior; deleted markers fail; outside-block edits revert and no-op outcomes fail. Tampering with parent/inspiration code or evidence binding must fail before dispatch. Verify ordinary constructors have identical default manifests/prompt bytes.
- [ ] Add O3 using real geometry: original initial program falls below .5 and executes only stage1; a deterministic valid 26-circle grid above .5 executes stage2. Assert actual invocation counts and measured evaluation costs, including stage2 timeout. Final validation consumes frozen geometry without rerunning the candidate or altering prior search records.
- [ ] Run the new public tests and confirm RED before implementing the seams.
- [ ] Implement seed and diff recipes, using upstream PromptSampler/extract_diffs/apply_diff_blocks/enforce_evolve_blocks. Zero-token seed materialization still produces a normal M7 outcome. Bounded repair consumes the original measured attempt loop; no second generation loop or hidden fallback to full rewrite.
- [ ] Implement isolated stage execution with read-only evaluator source and bounded regular-file JSON outputs. Independently validate finite (26,2)/(26,) geometry, radii, bounds, overlaps and sum. Keep all original pickle handling inside the sandbox. Add forged-score, nonfinite, oversized, symlink and sandbox-attempt tests. Preserve public diagnostics and private artifact bindings separately.
- [ ] Wire the coordinator into the current runtime hooks and registry. Use retained ResearchFrontier and metric_final admission: method host-cell retention is independent of the strict development incumbent; final validity is a frozen-geometry check, not a statistical holdout. Invalid geometry remains a failure and is ineligible for Mori parents; disclose any difference from zero-score upstream retention.
- [ ] Add stop/resume and recorded replay through the public Framework, including migrated sources, one failed patch and cascade early exit. Restore must use original host events. Verify the new named profile's identities match build_profile.
- [ ] Run focused tests, real Linux sandbox cases and the existing complete `make check` with locked dependencies; commit the working offline recipe. Keep real/fixture performance labels distinct.

## Task 3: Paired real runner, evidence and integration

**Files:** Create m0/zoo/circle_packing/{runner,host_reference}.py and README.md; tests m0/tests/test_openevolve_runner.py and test_openevolve_reference.py. Add research/experiments/2026-11-05-openevolve-circle/{export_runs.py,recalculate.py,README.md} and scripts/tests/test_openevolve_export.py. Update current status/spec/navigation after the actual result is known.

**Interfaces consumed:** Task2 profile, domain, original method records and public Framework entry points.

**Interfaces produced:**
- runner.run(output: Path, *, mode: str, seed: int, iterations: int, ledger=None, provider=None, runner=None) -> dict: default fixture mode, explicit live opt-in, immutable source/task/profile/dependency manifest, durable terminal and terminal resume without repeated calls.
- host_reference.run(output: Path, *, frozen_plan: dict, ledger) -> dict: real pinned upstream controller with one worker and injectable metered init_client; no handwritten reference optimizer.
- exporter/recalculator CLI uses original records only and never executes candidates, reads hidden secrets or calls providers.

- [ ] Write RED runner tests: default CLI requires no credential and makes no network call; live source/data/profile/dependency mismatch refuses before payment; terminal resume/replay makes zero provider/evaluator calls.
- [ ] Write RED reference transport tests with a local HTTP server and spawned real host worker: model system/user context is preserved; reserve precedes HTTP; actual billed failure settles; missing usage leaves the original reservation pending and prevents further paid calls; retries are zero. Verify sentinel credentials do not occur in persisted config/log/evidence. Use the original campaign API; no new per-run campaign.
- [ ] Implement the named runner and factory wrapper. Read credentials only inside the provider factory from the existing environment; do not serialize their values into published configs. Preserve the host's real prefetch scheduling despite a single physical worker and disclose its difference from Mori's serial dispatch. All actual attempts, control work and evaluator stages count toward each arm's common total ceiling.
- [ ] Freeze one six-cell plan: seeds0/1/2 × vendor/Mori, first pair included as smoke, six mutation iterations per arm, pilot migration interval2, common model/low/16384, task hashes and60-second stage limits. Derive the common token ceiling from existing conservative provider bounds so protected control plus one main dispatch fit. Before calls, serialize the exact numeric token/evaluation/wall-clock ceilings and verify both arms enforce them. Mori repairs/control do not receive extra budgets. Preserve unrun cells if original campaign residual funds are insufficient.
- [ ] Predeclare the public-range target as valid sum_radii >=2.372379655271936 (90% of pinned README2.635977394746595); report paired live vendor results separately. Missing this range remains an explicit unmet performance status, not a reason to replace failed seeds or hide negative results.
- [ ] Build export/recalculation tests for altered source, selection/migrant binding, cascade bills, geometry identity, unknown usage and missing cells. The reducer preserves the full six-cell denominator, validity/failure counts and null outcomes, plus actual and nominal budgets. Default fixture results never populate the real-result section.
- [ ] Run current offline CLI/sandbox, focused tests and one complete check; perform the one whole-branch independent review and fix substantive findings with failing-then-passing tests. Publish a clean source revision before any real declaration.
- [ ] Execute the first seed pair once using the original cumulative campaign. Verify independent currency, physical geometry and recorded replay before the remaining pairs; freeze all source/dependency changes during paid work. After every search terminates, freeze winners and independently validate final geometry without feeding it back into search.
- [ ] Export and independently recalculate original evidence; publish every outcome and actual source/fidelity/performance gap. Run final exact-head Mac/Linux/MLE checks and verify their artifacts. Merge, verify merged tree, archive and retire the method branch, then proceed to AIRA. Overall Goal remains active.

## Self-review and staging

O1/O2 and restore environment are Task1; O3/O4 and source isolation are Task2; O5, common budgets, real results and integration are Task3. Every Review Focus item has an explicit owning test. Interface names above are shared across tasks. This is a staged plan only: do not execute against or dirty Arbor's frozen worktree. Publish source notes/design/plan together at the next method handoff; apply normal worktree isolation and the already authorized inline workflow.
