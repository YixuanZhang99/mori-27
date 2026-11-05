# Arbor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full declared Arbor hypothesis/insight/gate mechanism through Framework, then deliver a reproducible real pilot and merge it.

**Architecture:** Add one method policy and a driver-owned coordinator; retain the existing loop, metered invocation, M5 context projection, M7 construction, hierarchical budget and layered gate. Extend only the source-bound planning, aggregate memory and explicit execution-base seams needed for the declared mechanism.

**Tech Stack:** Existing Python >=3.11, JSON profiles, locked dependencies, pytest, Git artifact backend and Linux SandboxRunner.

**Spec:** `docs/superpowers/specs/2026-11-05-arbor-design.md`, current `docs/specs/classic/ARBOR.md` and COMMON. Offline implementation may proceed in the separate detached checkout; publish the method branch only after AIDE merges. Plan path `docs/superpowers/plans/2026-11-05-arbor-delivery.md`.

## Global Constraints

- Do not edit frozen AIDE source while session 9324 runs. Use separate detached source 40b1e88 for offline work; rebase onto actual merged main before publishing, with one active method branch.
- Keep public Framework.from_profile/evolve/inspect/replay. No second optimization loop, provider ledger or evaluator.
- User already authorized implementation, push and merge after gates. Use native inline execution and one whole-branch independent review.
- Upstream revision a633f56f2601387402194481e846e3375e822afa; fidelity adapted; report declared deviations and real failures.
- Default method 20 cycles, depth 2. Live pilot 5 cycles, depth 2, margin 0, admission call_budget 3; split_seed 7; search seeds 0/1/2; three named MLE tasks.
- Preserve M7 selection-view redaction. All textual feedback goes through explicit M5 projection; no raw admission score/feedback or final result in planning/memory.
- Current trunk is the executable base; skeleton ancestry and reference edges are distinct. No failed/unevaluated parent is silently treated as valid code.
- Original cumulative CNY campaign, max ¥200; no credential contents copied/printed. All ideation, synthesis, construction and control calls are metered.
- AIDE/GEPA/FunSearch defaults and recorded behavior remain unchanged.

## Review Focus

1. Pending idea outlives a trunk change: dispatch must use current authorized trunk, preserve its hypothesis parent and evidence refs (Task 1).
2. Model invents aggregate provenance or splices a different root summary into a checkpoint: reject before another paid call (Task 2).
3. Gate rejection text/score or final data enters planning through derived memory: preserve only the allowed verdict and prove final independence (Task 2).
4. Format repair replaces hypothesis, or a non-trunk artifact is supplied under a valid hypothesis ID: reject the result and retain charges (Task 1).
5. Planning or synthesis reaches budget/unknown settlement after partial work: no fabricated completed cycle, no free retry, retain missing-cell denominator (Task 3).

---

### Task 1: Executable hypothesis planning and trunk-bound construction

**Files:** Create `m0/core/composition/arbor_policy.py`, `m0/core/composition/arbor_runtime.py`, `m0/tests/test_arbor_recipe.py`; modify `runtime.py`, `hierarchical_runtime.py`, `defaults.py`, `construction.py`, `construction_recipes.py` in composition. Add `m0/config/profiles/arbor_mle.json` with provisional offline wiring; live remains unavailable until Task 3.

**Interfaces:**
- `arbor_options(options: dict) -> None`: validate max_cycles 1..20, max_tree_depth=2 for pilot, seed>=0, max_new_ideas 1..3, pending capacity <=3*max_cycles.
- `ArborPolicy(context, llm, *, max_cycles=20, max_tree_depth=2, seed=0, max_new_ideas=3)` implements existing observe/select/ideate/absorb/checkpoint hooks. It does not own a loop.
- `ArborCoordinator.prepare_observation(state: dict, context: dict) -> dict` adds only driver-verified projected planning material; `selection(candidate_id: str, cycle: int, context: dict) -> dict` records chosen hypothesis, skeleton parents, references and current execution base.
- `HypothesisRecipeOperator.recipe(request: OperatorRequest) -> dict` produces kind `hypothesis_refine`, with `hypothesis_binding` from coordinator, never model-selected artifact bytes.

- [x] Add public Framework RED tests: `test_arbor_ideates_before_selecting_and_dispatches_one_pending_hypothesis`, `test_pending_idea_uses_new_trunk_without_changing_skeleton_parent`, `test_reference_edges_do_not_change_depth`, `test_invalid_or_exhausted_parent_is_not_dispatched`.
  Assert generated options exist before selection; only selected hypothesis becomes one candidate; unselected pending survives; current trunk base hash matches prior gate; selected ID and fixed hypothesis match construction; max depth excludes depth-3 dispatch.
- [x] Run `PYTHONPATH=m0 <dev-python> -m pytest -q m0/tests/test_arbor_recipe.py`; expected missing Arbor registration/contracts, not dependency failure.
- [x] Implement strict generation schema from spec. Host assigns hypothesis IDs; selection references one new index or existing pending ID. Preserve pending options/refs in checkpoints and original events. Validate again at dispatch. Invalid JSON/unknown parent/forged ref fails explicitly, with original provider usage retained.
- [x] Add explicit pre-observe M5 retrieval for the configured Arbor policy within existing planning reservation. Ordinary methods retain previous context order. Do not relax ConfiguredExecution.selection_view redaction or give planner a domain object.
- [x] Implement trunk-base binding and `hypothesis_refine` validation. Candidate.parents remains hypothesis skeleton. This recipe's artifact list is exactly the authorized current trunk (or empty before first accepted trunk). All other recipe parent rules stay unchanged. Attach reference edges through driver after targets exist.
- [x] Add `test_changed_hypothesis_repair_is_rejected_with_cost`, `test_same_hypothesis_format_repair_keeps_identity`, and `test_forged_trunk_binding_fails_before_construction`. Use existing max_attempts=2 constructor capability and assert no evaluation of rejected output.
- [x] Run Task 1 tests plus `test_configured_construction.py`, `test_research_frontier.py`, `test_aide_recipe.py`, and `test_composition_registry.py`. Confirm no model/training on recorded replay and no invented numeric score for pending hypotheses.
- [x] Commit the tested Task 1 deliverable. Do not claim complete Arbor before Task 2/3.

### Task 2: Incremental insight propagation and isolated admission

**Files:** Extend `arbor_runtime.py`, `arbor_policy.py`, `context.py`, `runtime.py`, `hierarchical_runtime.py`; modify `m0/zoo/mle_bench_lite/composed_domain.py`; add `m0/core/composition/tree_insight.py`, `m0/tests/test_arbor_memory.py`, `m0/tests/test_arbor_admission.py`, `m0/tests/test_arbor_restore.py`; extend `test_arbor_recipe.py` and existing MLE composition tests.

**Interfaces:**
- `ArborCoordinator.backpropagate(proposal, public_evidence, context, *, cycle: int, llm) -> list[StateMutation]`: called within the existing reserved absorption envelope; one leaf insight and parent-to-root updates consume old summary plus new source evidence.
- `ContextMemory.prepare_tree_insight(*, target_id: str, source_refs: list[str], previous_ref: str | None, body: dict, cycle: int, synthesis_ref: str) -> list[StateMutation]`: driver-only derived binding, verifies original run/context sources, immutable version and content. No ordinary-policy authorization changes.
- `ArborCoordinator.commit_decision(candidate_id: str, decision)`: derives only candidate_id/admit/receipt_id for subsequent planning. Actual admission controller remains authoritative for trunk.
- `ArborCoordinator.restore(checkpoint: dict, original_events) -> None`: rebuild selected hypothesis/base, aggregate source closure, verdicts and pending consumption from existing events. A checkpoint claim alone is insufficient.

- [x] Add public RED tests `test_leaf_failure_updates_ancestors_and_global_prior_then_changes_next_prompt` and `test_second_child_preserves_first_child_sources`. Assert actual model inputs include old summary/new dev evidence, root and ancestors differ as appropriate, source closure stays complete, superseded summaries are retained but not retrieved.
- [x] Add `test_insight_ablation_changes_actual_ideation`, with paired fixture providers whose hypothesis output depends on the observed source-bound lesson. Assert a different input and selected hypothesis; merely writing a file is insufficient.
- [x] Implement trusted `tree_insight` derived binding in ContextMemory. Keep existing same-candidate dev provenance constraints for ordinary lessons. Derivation may combine known dev/derived sources, with canonical acyclic source closure. Trust cannot exceed weakest source; interpretations are L2, never claimed verified science. Global prior stays run-scoped, not cross-run global memory.
- [x] Implement synthesis within existing invocation accounting; leaf and each ancestor/root update has distinct input/output and source refs. Serial application only after complete validation. Bounded summary text and planned worst-case provider call count must match reservation; do not use a raw llm call outside the metered envelope.
- [x] Extend task_metric PublicTrainDomain to expose admission context explicitly while preserving proxy defaults; dev/admission/final reuse the exact frozen prediction artifact. Run `test_all_held_out_evaluations_reuse_the_one_materialized_artifact` and actual synthetic PublicTrainDomain coverage.
- [x] Add `test_high_dev_low_admission_keeps_trunk_and_only_exports_verdict`, `test_tie_and_margin_reject`, `test_gate_call_cap_counts_baseline_and_failures`, and `test_final_changes_do_not_change_search_or_memory`. Assert no raw gate score/reason/label in planner/absorber context; final freeze cannot change selection.
- [x] Add `test_tampered_aggregate_or_pending_checkpoint_rejected_before_provider` and one completed-cycle continuation/replay test, including mixed successful/failed leaves and unconsumed pending ideas. Use existing journal/checkpoint machinery, not a new recovery system.
- [x] Run Arbor tests, `test_composition_context.py`, `test_layered_admission.py`, `test_configured_construction.py`, `test_mle_composed.py`; then one existing full local check. Commit when requirements pass.

### Task 3: Named runner, predeclared real matrix, evidence and merge

**Files:** Create `m0/zoo/mle_bench_lite/arbor_runner.py`, `arbor_grading.py`, `m0/tests/test_arbor_runner.py`; finalize `arbor_mle.json`. Reuse existing shared MLE bundle/domain/provider/currency/audit helpers; only extract a shared helper from AIDE if both callers need it and its original behavior is covered. Add export/recalc under `research/experiments/2026-11-05-arbor-mle`, with root tooling tests in `scripts/tests/`.

**Interfaces:**
- `build_profile(*, split_seed=7, search_seed=0, call_token_bound: int, max_cycles=20) -> dict`: full defaults; runner pilot explicitly sets 5. Sets tree depth 2, frozen hypothesis, 2 constructor attempts, gate cap 3, and existing convergence rule min_samples=4/patience=3/min_improvement=0.
- `run(*, output, public_root, task_id, split_seed=7, search_seed=0, max_cycles=5, live=False, resume=False, ledger=None, anonymization_key_path=None, provider=None, runner=None) -> dict`: Framework orchestration only; trusted provider/runner injection is test-only.
- `grade_selected(...) -> dict`: pin official revision/data, independently rederive selected submission from original predictions, reuse durable once-only grade claim pattern. Arbor final uses layered final freeze/receipt, not AIDE's metric_final event names.

- [ ] RED tests for exact profile/default-vs-pilot distinction, immutable split across search seeds, fresh isolated initial control, all-failed/null result, planning budget exhaustion, incomplete/unknown fees and replay without external calls.
- [ ] Implement offline fixture provider that respects planner/absorber/constructor schemas and trains only on synthetic public inputs. Copying AIDE FixtureProvider unchanged would violate frozen hypotheses; fixture must return the actual requested hypothesis.
- [ ] Wire live provider phase-call bounds: operator up to 2 attempts; planning reserves up to 4 calls per envelope: leaf + two ancestors + virtual global prior at depth 2; ideation uses a separate existing envelope. Reserve each existing planning envelope conservatively, settle actual calls, no evaluation model calls. Include fresh control reservation in global totals.
- [ ] Add meaningful synthetic Linux run with at least one successful full dev/admission/final sequence, one gate rejection and fixed artifact reuse. Keep failure fixtures separate from benchmark results. Verify CNY receipts and existing physical ledger audits cover planning and synthesis as well as construction.
- [ ] Complete one whole-branch fresh independent code review, fix verified findings, run required local checks and offline default CLI/resume. Push draft PR; no repeated per-task review loop.
- [ ] Before first paid call, freeze clean source, profiles, datasets, provider/campaign identity, all nine cells and dependency hashes. Smoke is spooky seed 0, explicitly included in matrix. Keep source/env unchanged through the matrix. Stop remaining cells on integrity/replay/unknown accounting failure; do not replace failures or shrink denominator.
- [ ] Complete declared search cells through the same process; poll a live handle, never restart on observation timeout. Official grading starts only after searches end; process each frozen valid submission once.
- [ ] Export original records, pending/selected hypotheses, aggregate sources, six-stage trace, gate/trunk decisions, exact submitted programs, official score and all failures. Independently recalculate selection/trunk, counts and fees. Separate dev/admission/local final/official values; no unsupported gain/medal-rate claim. Include method_id/reference_revision/recipe_revision/fidelity/deviations.
- [ ] Update ARBOR spec, CURRENT_GOAL, FRAMEWORK_STATUS, README and provenance with actual commands/results/gaps. Run final exact-head Mac/Linux/MLE gates; merge with explicit head, verify merged tree, archive and retire method branch. Goal stays active for OpenEvolve → AIRA → LoongFlow → R&D-Agent.

## Self-review

R1 → Task 1 event/selection/execution tests; R2 → Task 1 repair and base binding; R3 → Task 2 layered rejection/cap tests; R4/R5 → Task 2 actual synthesis/consumption/ablation; R6 → Task 2 and Task 3 frozen final/official lane. All nine modules map to these tasks; knowledge intentionally off per approved benchmark spec. All five Review Focus cases have explicit tests above.

Offline work starts on detached source 40b1e88 while AIDE remains frozen. Recheck and rebase onto actual merged main before publishing or paid Arbor calls.
