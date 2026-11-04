# M7 Configured Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make configured M7 construct, freeze, recover and evaluate real artifacts under role/hypothesis/projected-context contracts, through Framework and both native/Git backends.

**Architecture:** M2 emits recipes. A private CandidateExecution module materializes once inside the existing candidate-production operator envelope and evaluates immutable artifacts separately. Native content storage and Git publication are actual adapters; the existing physical and CNY authorities retain admission and settlement ownership.

**Tech Stack:** Python 3.12, existing pytest/uv, canonical JSON, actual temporary Git/worktrees, existing continuation/provider/currency machinery. No new runtime dependency.

**Spec:** docs/superpowers/specs/2026-11-04-m7-execution-design.md

## Global Constraints

- Preserve original alignment/RUBRIC and all old tests/verifier commands/timeouts. No paid supplier calls, live campaign migration or main merge.
- New v9 family is explicit; old v6/v7/v8 readers retain their meaning. Candidate production uses one physical operator intent, one node, zero evaluations, continuous provider ordinals.
- Only already retrieved authorized ContextPack content may be projected. Excluded content must not reenter through ideation/strategy/skills.
- Known failures retain measured costs; unknown aggregate usage retains the whole reservation. No replacement call for ambiguous completion.
- Every split evaluates the same frozen artifact. No generation/repair on admission/final, baseline refresh or recorded replay.
- M7-03 parallel dispatch, full A7 and real research effectiveness remain original open requirements.

## Review Focus

- A policy that copies every supplied value must not smuggle excluded retrieval content into the hypothesis (Task 3).
- A response with valid usage but malformed output, changed frozen hypothesis or local validation failure must remain charged; a later unknown repair must not erase known provider evidence or release reserve (Tasks 1, 2, 5).
- A crash after provider completion or Git commit but before the parent completion marker must adopt original work without a replacement call/commit (Tasks 2, 4, 5).
- Native evaluator plus default Git artifact isolation must work without command-domain requirements; native execution must not be labelled sandboxed (Task 4).
- Control sessions must use frozen input and separate construction state while future physical/CNY obligations remain protected (Tasks 3, 5).

### Task 1: Strict construction contract and actual prompt materializer

**Files:** Create `m0/core/composition/construction.py`, `m0/tests/test_construction.py`; update `m0/CONTEXT.md` vocabulary.

**Interfaces:** `RoleDefinition(name, version, instructions)` is immutable. `ConstructionPlan.create(candidate, recipe, spec, context_pack, *, roles)` freezes canonical input; recipe keys are `kind`, `task_desc`, `parent_artifacts`, `instructions`, `comparison`, with explicit strict validation. Existing `ExecutorSpec` is used, no competing spec type. `project_context(pack, fields, *, expected_ref)` returns detached selected data with original identity and provenance. `PromptMaterializer(roles, *, max_attempts=1, validator=None)` exposes async `construct(plan, provider) -> ConstructionResult`. Result binds final candidate/artifact, original/effective hypotheses, role/spec/projection/plan references, attempts and measured aggregate construction cost/coverage. Failure with known bill uses existing OperatorFailure; unknown usage propagates UsageError.

- [ ] Write tests proving changed role changes provider input and artifact; exact projection/no source mutation; unknown/duplicate/summary fields reject before call; frozen candidate/spec conflict before call; output hypothesis change known-cost failure; free hypothesis persisted; strict JSON and bounded validation repair; unknown second call retains prior observations and raises UsageError; no extra eval count.
- [ ] Run `env TMPDIR=/dev/shm PYTHONPATH=m0 /usr/local/share/mori27-local/dev/bin/python -m pytest -q m0/tests/test_construction.py`. Expected: RED because new module/behavior absent.
- [ ] Implement the private module. Permit selectable fields memory/grounding/query; default is explicit memory/grounding. Each retry gets same frozen plan and only deterministic local feedback. Consume current provider usage immediately after each call before decoding. Never reset governance ordinals or nest meters.
- [ ] Run the same test command plus `m0/tests/test_composition_context.py m0/tests/test_composed_context.py`. Expected: GREEN, no historical source changes.
- [ ] Commit tested construction core. This task alone is not public M7 completion.

### Task 2: Durable materialization and frozen native artifacts

**Files:** Create `m0/core/composition/execution.py`, `m0/core/composition/artifacts.py`, `m0/tests/test_materialization_recovery.py`; modify continuation support only where required.

**Interfaces:** `CandidateExecution(materializer, artifact_backend, store, provider, evaluator)` exposes async `materialize(plan, *, operation) -> Materialization`, and async `evaluate(materialization, request, *, operation) -> EvidenceRecord`. `Materialization` has strict versioned encode/decode and immutable artifact ref/content digest, ConstructionResult, exact operation identity and terminal outcome reference. `NativeArtifactBackend` publishes/loads bound immutable bytes. These methods do not reserve/settle budget; production/evaluation lifecycle owners do so once.

- [ ] Write real-store tests for complete materialization adoption, changed plan/operation/artifact rejection, publication tampering, no regeneration during reevaluation, provider-completed suffix adoption, unresolved native start, recorded replay with explosive provider/evaluator, and strict failure cost evidence.
- [ ] Run `pytest -q m0/tests/test_materialization_recovery.py` with the Task 1 environment. Expected: RED.
- [ ] Implement terminal persistence before settlement, exact continuation consumption, immutable publication and deterministic reconstruction only from certified original outcomes. Use existing provider recovery, not a replacement journal for calls. Result adoption restores provider state as required.
- [ ] Run Task 1+2 test files plus existing composed/governed recovery tests. Expected: GREEN.
- [ ] Commit durable native artifact lifecycle.

### Task 3: Public v9 composition, recipes and isolated controls

**Files:** Modify `contracts.py`, `registry.py`, `defaults.py`, `strategies.py`, `population.py`, `runtime.py`, `hierarchical_runtime.py`, `population_runtime.py`, `proxy_runtime.py`, `governed.py`, `governance.py`, `invocation.py`; create `m0/tests/test_configured_construction.py` and `m0/tests/test_construction_controls.py`.

**Interfaces:** New assembly schema 2 requires `execution={schema_version:1, spec:{role,hypothesis_frozen,context_projection,hypothesis?}, constructor:{name,options}}`; schema 1 is unchanged. Registry adds explicitly registered `constructor` factories and declarations. Resolve role before dispatch using constructor role definitions. New built-in recipe operators replace generation only in v9; prebuilt legacy path is explicit. Runtime identities are composed-v9-m7, composed-v9-m7-governed and composed-v9-m7-governed-external. External v9 remains rejected before calls until Task 5.

- [ ] Add public Framework tests for native generation, role/projection behavior, echo-policy excluded sentinel isolation, static instruction preservation, free hypothesis frontier attribution, frozen mismatch typed failure, one-node/no-eval failure, same artifact across dev/baseline/calibration/admission/final, pause/resume and zero-call recorded replay.
- [ ] Add control tests with different main/control input sentinels and fresh provider/constructor/domain/executor instances, frozen parentless controls and protected operator budgets.
- [ ] Run new tests. Expected: RED from unsupported schema/new path.
- [ ] Integrate M2 recipes and M7 materialization within one existing InvocationLifecycle.operator envelope. Freeze build inputs after projecting M5, including before ideation. Evaluation only receives a Materialization reference. Persist references in checkpoint and exact new runtime manifest; no reinterpretation of old records. Old profiles/readers remain unchanged.
- [ ] Run new files plus existing context, skills, population, layered, governance and budget tests, then full project checks. Expected: all GREEN.
- [ ] Commit public v9 native path and record limitations honestly until Task 4/5.

### Task 4: Real Git publication, native/command evaluation and default profile

**Files:** Extend `artifacts.py`, `execution.py`, `worktree.py`, `command_domain.py`, `defaults.py`; create `m0/tests/test_construction_worktree.py` and `m0/tests/test_construction_worktree_framework.py`; add a standalone public example.

**Interfaces:** `GitArtifactBackend` publishes one protected-base artifact commit with a durable publication plan and verifies content/protected manifests. Evaluation consumes that commit without changing allocated EvalRequest. Worktree evaluation scratch and output logs do not redefine artifact identity. New recommended `execution_profile()` emits schema 2, hierarchical budget, checkpoints and Git artifact isolation; no base_repo means an explicitly managed empty artifact repo inside the run directory. Native domains can evaluate Git-published text without requiring CommandDomain.

- [ ] Write actual Git tests showing generation once, final commit reused across splits, native evaluator with Git publication, protected path/symlink rejection, changed commit/content binding rejection, SIGKILL after provider terminal and after commit plan/publication, and no duplicate calls/commit effects on resume.
- [ ] Run new tests. Expected: RED.
- [ ] Implement Git backend and command evaluation binding, preserving original sandbox/process adoption. Check out exact blobs without user hooks/filters. Complete native and command adapters through Framework.
- [ ] Run new tests and all prior worktree/governance tests. Expected: GREEN. Installed example must run outside checkout using a temporary repo, with independent artifact digest assertions.
- [ ] Commit the default new execution profile; document old profile as compatibility and leave any broader default migration requirement explicit.

### Task 5: External currency v9 compatibility and full recovery audit

**Files:** Modify `external_provider.py`, `provider_evidence.py`, `governance_audit.py`, the governed currency adapter/audit under `zoo/mle_bench_lite`; create `m0/tests/test_construction_currency.py` and loopback examples.

**Interfaces:** v9 external binding explicitly records candidate-production envelope and materialization references while retaining operator/evaluation physical baskets and phase call caps. Frozen CNY policy identity includes exact v9 runtime/config. Same schema may be retained only if authoritative meanings and reducers remain unchanged; otherwise version the changed contract and retain old decoder.

- [ ] Add loopback tests for build+repair ordinals, main/control call caps and future obligations, known first/unknown second response, frozen-hypothesis rejection charged once, terminal provider adoption before materialization, no double physical/currency charge, replay no HTTP/ledger writes, tampered construction binding rejected.
- [ ] Run new tests. Expected: RED from explicit v9 external rejection.
- [ ] Extend bridge and independent audit with concrete v9 support; use fresh fixture ledgers only. Keep live campaign untouched and third pilot deferred.
- [ ] Run all construction files and original v8 external/currency/recovery suites, then full project checks. Expected: GREEN, original compatibility unmodified.
- [ ] Commit complete protected construction path.

### Task 6: Independent review, acceptance and public evidence

**Files:** New v74 verifier preserving all v73 commands/history; tooling transition tests; documentation/module map, original alignment increment, examples and public evidence summaries.

- [ ] Add capability checks that exercise complete public M7 path (including installed artifact, native/Git, controls, currency and crash cuts); historical checks remain intact. Observe transition tests RED then GREEN.
- [ ] Run full axioms/Linux/examples/tooling/build/import, install wheel independently and run example outside checkout. Expected: all GREEN with frozen source hashes.
- [ ] Obtain one fresh whole-branch review; classify by real user effect. Fix Important/Critical findings in one RED→GREEN pass and rerun required full checks. Preserve rulings and any deferred minors.
- [ ] Commit, run clean same-SHA acceptance, push verified branch and draft PR, independently inspect hosted artifacts, preserve rollback bundle. No main merge without all original platform gates.
- [ ] Report M7-01 scope and remaining requirements precisely. M7-03 concurrent dispatch, full A7, real benchmark success and complete framework are not implied.
