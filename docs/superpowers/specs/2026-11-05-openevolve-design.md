# C05 OpenEvolve integration design draft

Status: active C05 design. Arbor was merged as d026357; the first host adapter is in progress. This document refines the approved sequence without reopening the original cumulative currency budget.

## Outcome and scope

Deliver docs/specs/classic/OPENEVOLVE.md O1–O5 through the existing public Framework, with a named JSON profile, default offline CLI, opt-in live CLI, recoverable original evidence and a real paired upstream/Mori circle-packing pilot. Logical ownership remains policy/operator/budget/frontier/memory/knowledge/execution/evaluation/admission. Use one serial method coordinator, not a second optimization loop. Async quota scheduling remains an explicitly separate fidelity gap, as allowed by the approved C05 spec; no claim of complete upstream scheduling.

Prefer a thin adapter over the actual pinned ProgramDatabase and PromptSampler. A new handwritten MAP-Elites engine would duplicate existing source and weaken the reference claim. Wrapping the whole vendor controller as Mori's runtime would bypass the existing nine-module ownership. The vendor controller is used only as the external reference arm, which is not described as governed Mori execution.

## Frozen source and task

Use vendored OpenEvolve 5153a7d74ee615b7090ec52903629870ecdacdf1, not the latest remote head. The byte audit found all 558 locally tracked files identical to their upstream blobs; 16 executable-mode differences and six absent packaging/image files are documented. Local audit files: /tmp/mori-c05-vendor-audit.json and /tmp/mori-c05-upstream-tree.json.

Task: the original examples/circle_packing initial_program.py and evaluator.py: exactly 26 circles inside the unit square, no overlaps, maximize sum of radii, normalized target 2.635. Original initial program already executed with the existing pilot interpreter inside SandboxRunner: validity 1, sum_radii 0.9597642169962064, zero model calls, no dependency installation. Evidence is external work/openevolve-preflight/preflight-report.json.

Use the actual example's four islands, population 60, archive 25, exploitation .7/exploration .2, elite ratio .3, built-in complexity/diversity features and ten bins. The full reference migration interval is 50. The small pilot explicitly reduces it to two island generations so migration can be observed; keep its .1 rate. Record whether migration actually occurred rather than inferring it from config.

Explicit source/design differences:

- The original phase-one example uses full rewrites. C05 requires diff mutation; enable diff mode and marker enforcement in both paired arms and disclose the adaptation. Do not silently claim the phase-one YAML is unchanged.
- Pinned source applies absolute combined_score thresholds .5/.75. Circle packing has only stage 1 and stage 2, so .75 never invokes a third stage. Old design-bank relative-to-best/three-stage text is not the actual pinned mechanism and is not used for this recipe.
- Upstream accepts partially applied diffs when at least one block matches and rejects no-match/no-change results. Preserve that behavior and report partial application. Enforced outside-block edits are reverted by the upstream helper, with unchanged results rejected.
- Bounded same-parent patch resampling is an explicit Mori adaptation; upstream lacks a max_patch_resamples option. Use at most two constructor calls per proposal. All attempts consume the same arm budget and retain their original responses.
- Embedding novelty, novelty LLM calls, external knowledge and semantic cross-run memory are disabled in both arms. They are not needed for O1–O5.

## Components and contracts

OpenEvolvePolicy and an OpenEvolve adapter/coordinator live under m0/core/composition; task-specific circle execution and reporting live under m0/zoo. Reuse the existing registry, ResearchFrontier, Proposal/EvidenceRecord, InvocationLifecycle, construction audit, original-event store and OpenEvolveDatabaseSnapshot. Existing profiles retain their current manifests and prompt bytes.

The adapter owns the real host database and the host's sampling environment. select(candidate_id, eligible_ids) produces one primary parent, separate inspiration references, target island, the frozen host selection record and source bindings. Sampling uses the real host strategy. Budget/depth eligibility is projected before sampling; no model supplies code or an invented source identity. If the eligible view is empty, stop explicitly rather than sampling an unauthorized parent. The complete history remains retained even when a parent is no longer eligible.

The coordinator verifies selected artifacts against original evaluated proposals, constructs the upstream prompt from authorized dev metrics/artifacts, and binds primary lineage separately from inspiration references. It registers every valid method candidate with the actual host archive even if the global delivery incumbent is not improved. MAP-Elites cell replacement, island membership and migration are method events, not M9 delivery verdicts. Historical artifacts/lineage remain in the Framework evidence archive after host population eviction. The pinned host migration creates new UUID-named Program copies with parent_id pointing to the source program; those copies are not fresh evaluated Framework candidates. Keep an explicit host-program-ID to original candidate/evidence mapping. Sampling a migrant resolves to its source artifact and source candidate for budget eligibility and Framework ancestry, while preserving the selected host ID and destination island in the method receipt. Never invent a new physical evaluation or discard migrants because their UUID is absent from ResearchFrontier.

Initial state is the frozen original seed program, evaluated through the same M7/domain path. Use a deterministic seed construction recipe/materializer with a zero-token receipt rather than asking the model to regenerate the upstream seed. Mutation thereafter uses the source-bound primary parent and upstream PromptSampler. An independent initial control executes the frozen seed in a fresh domain/session and its measured evaluation cost is part of Mori's total budget; it is not a second unreported budget.

Extend PromptMaterializer only with a deterministic prompt/decode seam that keeps the existing attempt loop, metering and original-call recovery. The OpenEvolve materializer reuses upstream extract_diffs, apply_diff_blocks and enforce_evolve_blocks. Its explicitly versioned wire format describes diffs; it must not inherit an instruction demanding a complete program. The decoder returns the full patched program as the executable artifact. A malformed or no-op patch can consume the second allowed attempt against the same fixed parent; it cannot change the selected parent, frozen hypothesis or scope. Record matched-block counts, repair feedback and every failed attempt. A seed path makes no provider call and cannot silently become a generation call.

Concrete class decomposition and helper names are builder choices. No new main loop, currency campaign, general-purpose scheduler or certificate subsystem is part of this work.

## Host state and recovery

The current interop snapshot is not enough for continuation: it omits RNG, program insertion order, diversity_reference_set and diversity_cache. A read-only 15-program probe restored identical RNG yet changed an existing program's diversity from 30.5 to 120.5; see /tmp/mori-c05-snapshot-probe.py/.log. Snapshot construction also reseeds the process-global RNG.

The runtime adapter must preserve the additional state and reconstruct/verify it against original host-operation events. Original candidate code, metrics, timestamps and insertion order come from authenticated run evidence, not an editable checkpoint. Persist host-generated migration UUIDs and timestamps and feed those exact recorded values into host reconstruction; fresh UUID/time generation during replay would change membership and tie breaking. Include the host RNG state, reference codes/cache values and deterministic environment binding. Python hash(code) and set iteration influence the host: freeze PYTHONHASHSEED in the named runner, record a process hash fingerprint, and refuse continuation under a different fingerprint. Rebuild sets in original operation order; a newly constructed set from a sorted snapshot is insufficient evidence of next-step equivalence. Any scoped host RNG/time handling must restore unrelated process state; there is only one serial coordinator in this delivery.

Required proof: uninterrupted and stopped/resumed executions in separate processes with the frozen hash environment must choose the same next parent/inspirations, produce the same feature coordinates and migration memberships, and consume no repeated external calls. Tampered RNG, cache/reference data, program order or original source bindings must be rejected. Builder may choose journal reconstruction versus an augmented snapshot internally, but must pass this semantic equivalence test, not just compare serialized DB fields. Recorded replay consumes original calls and evaluates no programs.

## Evaluation, admission and artifacts

Use the actual two evaluator stages inside the existing SandboxRunner. Each stage is a distinct measured execution with its own timeout and receipt; stage 2 is invoked only if stage 1 meets the pinned absolute .5 threshold. Set the same outer 60-second stage limit for both arms; disclose that it is stricter than the example evaluator's inner 600-second subprocess allowance. No stage-2 invocation or charge is allowed after early exit.

Keep evaluator source in the read-only sandbox data tree. Candidate execution and the original evaluator's pickle transport stay inside the sandbox. The host receives only bounded regular-file JSON geometry/metrics and independently validates finite arrays, exact shapes, unit-square containment, nonnegative radii, pairwise nonoverlap and the computed sum. Never unpickle on the host or trust a candidate-supplied score. Capture geometry for every executed stage; final selection freezes its geometry/artifact before an independent final validity check. This deterministic mathematical task has no hidden-label holdout; do not describe the final geometry check as a separate statistical test set.

Public dev metrics and bounded diagnostics can enter the next upstream prompt through the existing context projection. The separate final check cannot feed back into search. Method grid/island retention and the governed final incumbent remain separately reported. The builder should use the current configured admission rule compatible with these deterministic per-item geometry checks, explicitly recording any departure from the host's best-program selection. No semantic synthesis calls are added.

## Paired pilot and reporting

Use the real upstream OpenEvolve controller as the external arm, single worker, with its LLMModelConfig.init_client seam. Preserve original system/user message roles. Reuse the existing metered-host factory pattern, but reserve and settle against the original campaign before/after every actual request; unknown usage remains unresolved and stops further calls. Provider retries are zero. Do not launch another paid optimizer or proxy implementation. All reference-arm outputs still pass the same isolated task evaluator and frozen final geometry validation.

For Mori mutations, opt into the versioned `openevolve_v1` provider message mode: send the bound upstream system message as system and its user message as the start of user, followed by the frozen diff instruction and any measured repair feedback. This suffix is a disclosed adaptation. The private, version-2 prepared currency record retains the original constructor argument, its invocation digest and the exact canonical wire body; replay rederives the body from that argument and the frozen provider mode. Version-1 records and the default single-user transport remain unchanged. Reject mode, argument or wire drift before dispatch; never persist the API key in these records. The mode alone is not a live-pilot readiness claim: the host reference, common physical limits and complete construction/currency audit are separate prerequisites.

Freeze a six-cell plan (seeds 0/1/2 × vendor/Mori), with the first seed pair included as smoke. Both arms start with the same original program and use the same model alias, low reasoning effort, 16384 output allowance, evaluator hashes, feature/island/migration settings, outer time limits and total physical-resource ceilings. Use six mutation iterations for the pilot. Mori repair attempts and independent control costs share its one total ceiling; they are not extra allowances. Derive a feasible identical token ceiling from the existing provider's conservative invocation bound, including protected control plus one main dispatch; record this nominal ceiling separately from actual token usage. Before launch, freeze the exact computed numeric ceiling, evaluator-call ceiling and wall-clock ceiling in the matrix. The original cumulative ¥200 campaign is the ultimate hard limit and is never reset; insufficient residual funds leave later cells explicitly unrun.

The pinned circle README reports sum_radii 2.635977394746595 after a much larger multi-phase search. Predeclare the public-range criterion as at least 90% of that value (2.372379655271936) with valid geometry; do not call this paper-budget reproduction. Also report each matched-budget vendor/Mori pair, actual cost and validity. A small pilot that misses the public range is still delivered as a negative result, with the public-range status remaining unmet. Preserve null outcomes, failures and all six declared cells; never substitute seeds or average only the successful subset while hiding the denominator.

The first seed pair must finish and pass independent cost/geometry/replay audits before the remaining pairs. Search freezes before final validation. Export original candidate/source/patch/cell/migration/stage/cost records, with a standalone recalculator that performs no provider calls or candidate execution. Default offline examples use the actual geometric evaluator and deterministic patch fixtures; they are not benchmark evidence.

## Acceptance and integration

- O1: two feature cells retain distinct elites; replacement leaves original lineage and source records intact. A valid non-incumbent remains eligible for host sampling.
- O2: an actual migration changes destination-island sampling membership and survives original-event restoration.
- O3: below-threshold stage 1 triggers no stage 2 call/charge; a qualifying program runs stage 2 and accounts both physical operations. Same rules in the reference arm.
- O4: invalid/no-op/outside-marker patches exhaust the fixed two-attempt allowance, preserving parent identity and every billed failure; partial matching follows the pinned behavior.
- O5: real pinned vendor and public Framework arms run the same frozen circle task under the predeclared common ceilings; publish all six outcomes and performance/fidelity gaps.
- Named profile + current offline/live commands, actual sandbox run, resumed continuation and zero-call replay, original evidence reduction, focused tests and existing complete merge checks.
- One whole-branch review and final exact-head Mac/Linux/MLE gates, then merge, archive the method branch and retire it before AIRA. Do not label the overall eight-method Goal complete at this point.

## Builder check

A fresh read-only builder check (/root/openevolve_design_builder_check) returned “nothing important left”. Subsequent pinned-source inspection made migrant UUID/source-candidate mapping and recorded timestamp/UUID reconstruction explicit above. These refine the existing lineage/recovery requirements without expanding scope. Implementation begins after Arbor delivery.
