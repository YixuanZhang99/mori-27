# C03 AIDE Delivery Implementation Plan

> Execution skill: superpowers:executing-plans. Frozen 2026-11-05. Local work starts from the immutable C02 final candidate while CI runs; rebase unpublished commits onto the actual merged main before pushing AIDE.

**Goal:** Public Framework code-tree search with actual draft/debug/improve semantics, consumed L1 journal feedback, and reproducible real MLE results.
**Spec:** docs/specs/classic/AIDE.md, COMMON.md. Source WecoAI/aideml@ad73d227af481bea3de06f884f41b2993dd6453a.
**Constraints:** One active remote method branch. Existing nine modules, M7, CNY and MLE adapters. Original cumulative ¥200 ledger. No new search loop, evaluator or retry campaign. Keep output JSON artifact contract explicit. The entire C03 closes only after public behavior, real evidence and final CI/merge.

### Task 1: Atomic method choice and repairable code-tree history

Files: new m0/core/composition/aide_policy.py and m0/tests/test_aide_recipe.py; existing contracts.py, runtime.py, population_runtime.py, construction_recipes.py, construction.py, defaults.py and core/frontier/research.py only where the new method requires a shared seam.

- [x] First write public Framework failures for three independent roots; later valid-best improve; failed leaf debug; depth/nonleaf/exhausted-scope exclusions; empty construction failure remains a root but is not a debug parent. Use deterministic fixture outcomes, debug_probability=1 for the repair fixture and0 for the improve fixture.
- [x] Add an internal structured selection of parent IDs and operator alongside the legacy list result. Select after budget filtering, validate the named operator and its parent capability before exposing inputs or dispatching. Default methods keep OK/scored-only parents.
- [x] Implement source-matched AIDE policy order and independent RNG. Retain original failed eval_status, no invented score; keep rejected valid/failed tree history with opt-in persisted retention. Do not add an unhandled frontier subclass or overwrite default pruning semantics.
- [x] Add debug/improve recipe kinds. Debug takes one failed artifact; Task 2 adds the selected parent's authorized public feedback and enforces its presence. Improve takes one successful artifact and dev score. Draft stays parentless. ConstructionPlan validates parent count and no fabricated debug comparison.
- [x] Validate resumed history and RNG against original run events; reject configuration/parent/RNG tampering before another provider call. Use existing recorded replay, not a second optimizer or verifier stack. Test default GEPA/FunSearch/greedy behavior and ordinary failed-parent refusal.
- [x] Run focused AIDE selection/recovery plus shared construction/frontier regressions and architecture axioms; commit the coherent task.

### Task 2: Source-bound L1 journal and actual public debugging feedback

Files: m0/core/composition/context.py, runtime.py, defaults.py; zoo/mle_bench_lite/composed_domain.py; new m0/tests/test_aide_delivery.py (Linux inventory) and related memory regression tests.

- [x] Write a real sandbox/public CSV fixture with a recognizable syntax error. Assert the subsequent debug request includes its original artifact and public traceback, then produces valid predictions.
- [x] Add bounded actual stderr to dev-only failure feedback, frozen in domain identity. Keep raw logs in original candidate artifacts; exclude private labels, prediction metadata and final scores from feedback.
- [x] M5 builds one bounded run-scoped journal entry from the authoritative proposal plus public dev evidence and original receipt. Reuse M7 hypothesis_frozen=False so the original materialization retains initial rule intent and effective generated plan; bind the scored proposal's effective hypothesis to the journal. No new docstring parser or extra model call.
- [x] Reuse ContextMemory.write, which already activates newly written validated L1 entries without L2 promotion. Keep writes through StateApplier; reject forged source bindings and journal payloads on restore. Do not add a new activation operation. AIDE absorb must avoid BestFirst's automatic L2 behavior.
- [x] Configure run scope, L1 only, no imports/knowledge, top_k covering the bounded node count and sufficient rendered context capacity. Test an older failed parent after multiple newer entries; missing selected-parent feedback must not silently become generic improve.
- [x] Assert actual later constructor consumption of plan marker, correct dev metric and failed traceback, plus absence of private/final/L2 material. Run memory/context/default-method regressions and actual sandbox fixture; commit.

### Task 3: Named MLE runner, fixed data and complete evidence

Files: dedicated zoo AIDE entry point/profile; reuse/factor composed_agent.py preparation and existing PublicTrainBundle/PublicTrainDomain/submission/grader paths as needed; named config/profiles/aide_mle.json; delivery tests, PROVENANCE and research experiment report.

- [ ] Add default offline fixture CLI and explicit live mode. Freeze source/data/profile/provider before calls; retain failure reports for no valid candidate and unknown usage. Reuse original CNY authority and one independent initial control.
- [ ] Freeze max_nodes10,drafts3,p(debug)=0.5,debug_depth2,output16384,effortlow,execution120s. Data split seed and search seed are distinct: ALL dev/control/final requests and bundle contexts use split_seed; policy/control selection uses search_seed.
- [ ] Use validation-best admission and reporting-only frozen final. Do not inherit layered/calibration gates. Reuse original prediction bytes for final/materialize; no retraining or final-score-driven re-selection. Preserve no_valid_submission and null score when all candidates fail.
- [ ] Prove held-out changes do not affect search; cross-search-seed data contexts remain fixed; resume does not repeat calls/training; recorded replay issues no provider/sandbox/grader requests. Complete one whole-diff review and required repairs before paid delivery.
- [ ] From clean published source, predeclare the task/seed matrix and run spooky seed0 first as its smoke cell if identical protocol is frozen before the call. If smoke exposes an implementation defect, retain its version and costs; do not blend revised protocols or rerun selectively. Continue remaining declared cells only when justified by the observed result.
- [ ] Export original reports, programs, tree choices, frozen submissions, official scores, all failure denominators, runtime and original campaign costs. Distinguish local dev/final scores from official post-selection grading, and adapted matrix from paper/medal reproduction.
- [ ] Final candidate Mac/Linux/MLE checks, merge to main, verify merge tree, archive/retire the method branch. Update current goal/status and proceed to Arbor. Do not mark the entire eight-method Goal complete.

Avoid further broad research before implementation: source decisions and concrete missing seams are already recorded. The next useful action after promoting this plan is the first failing public Framework fixture.

## Verification commands and review focus

Task 1: `uv run --project m0 --locked python -m pytest m0/tests/test_aide_recipe.py m0/tests/test_configured_construction.py m0/tests/test_composed_runtime.py m0/tests/test_funsearch_framework.py -q`. Expected: all pass after the original new-method failures are observed. Task 2 adds aide_delivery and memory/context regressions; Task 3 runs the actual fixture, governance/recovery regressions and full existing CI. Use the configured locked Python environment.

Review focus: failed-parent capability cannot authorize ordinary operators; retained failures never become numerical incumbents; atomic operator/parent choice remains valid after budget masking; checkpoint restoration validates original history; all three evaluation lanes use the frozen data split; generated plan and actual selected-parent traceback are consumed from L1; no final labels/private metadata or extra paid calls on replay.
