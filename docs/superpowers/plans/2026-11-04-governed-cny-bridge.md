# Governed external CNY provider bridge implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking. This document authorizes no execution in the currently frozen acceptance source.

**Goal:** Connect the existing protected CNY authority to governed provider invocations, with both admissions before HTTP, durable known-outcome adoption, no automatic retry of ambiguous calls, and offline acceptance through the public Framework.

**Architecture:** Keep `HierarchicalBudget` as the physical authority and `CampaignBudget` as the CNY authority. A task-adapter bridge coordinates them using a frozen call identity and private outcome spool; core exposes typed invocation and recovery hooks without importing CNY pricing. This is an ordered, recoverable protocol between two stores, not an atomic transaction spanning them.

**Tech stack:** Existing Python 3.12, stdlib HTTP/JSON/hashlib/SQLite, X1 journal and checkpoint machinery, pytest, real loopback HTTP fixtures, subprocess/SIGKILL crash tests. No new dependency or provider SDK is required.

**Spec:** [resident control design](../specs/2026-11-04-resident-control-design.md), [CNY authority contract](../specs/2026-11-04-cny-governance-journal.md), [provider-bound investigation](../../../research/2026-11-04-provider-token-bounds.md).

## Global constraints

- Read against clean source `bedc5b31fe737dfd207fa8466f68fecb58c5c294` on 2026-11-04. Paths below are repository-relative to `/home/neekyoung12/.codex/worktrees/resident-governance/mori-27`.
- Existing authorization remains **200 CNY**, on the original campaign authority. Do not create replacement money, reset historical spending, change the campaign ID/policy/prices, or erase failed runs. This window has **no third pilot**.
- This preparation performed no live-ledger reads, migrations, HTTP, credential access, source mutations or tests against the active acceptance tree. Offline implementation requires no additional user approval invented by this plan.
- Spec: “There is no automatic migration in construction, protection or admission.” Keep `enable_governance(expected_policy_sha256, expected_head)` a separate explicit lifecycle operation; only temporary test ledgers are migrated by this implementation's tests.
- Spec: “A start without authoritative completion is unresolved, never an automatic retry.” No retry loop, fallback provider or resubmission with a new call ID may hide that state.
- Spec: “Currency policy stays in its task adapter.” No CNY-to-USD conversion or CNY expression enters `CostVec`, M9 or the seven physical account totals.
- Spec accounts remain exactly `explore`, `exploit`, `reeval`, `control`, `repair`, `handoff`, `overhead`. One physical settlement projects to these accounts; the CNY charge is correlated evidence, not another token charge.
- Preserve schema-1 currency behavior, schema-2 authority history, legacy composed-v6 behavior and current composed-v7-governed fixture serialization. Use explicit new bridge/runtime versions for the new path; no implicit checkpoint conversion.
- Keep full known costs on contract violations. Unknown monetary cost remains pending even when a token subtotal is known. An admitted call cannot be cancelled by `cancel_control`.
- Controls keep fresh semantic sessions and fixed inputs. Sharing authority/transport is allowed; sharing history, consumable usage counters, model state, mutable random state or other-lane feedback is not.
- No claim of IID, immutable hosted-model snapshot, exactly-once external effects, invoice verification, machine power-loss durability, or rubric/release completion follows from these tests.

## Review focus

1. A crash after currency admission but before HTTP can strand capacity: prove zero duplicate requests and retain the pending reservation; do not invent a cancellation API (Tasks 3–4).
2. A settled call with a missing Framework completion needs response content, not merely a usage receipt: preserve and adopt the private outcome without HTTP (Tasks 2–4).
3. Multiple calls or a zero-token response must not escape a frozen ordinal cap: enumerate per-phase obligations and enforce counts independently of measured tokens (Tasks 1, 3).
4. A cheap or failed control must not enlarge main's visible CNY allowance: freeze main currency capacity before control results and test paired different-control-cost runs (Tasks 1, 3, 6).
5. Moving directories, changing returned model or forging a rehashed foreign ordinal must not relabel another run's bill: validate independent identity mapping and retain any unresolved pricing state (Tasks 1, 4–6).

---

## Grounding: current interfaces and concrete gaps

| Current source | Existing useful interface | Bridge gap |
| --- | --- | --- |
| `core/composition/governed.py:GovernedInvocation.meter` | Freezes run/lane/slot/intent/fingerprint/adapter hash; hard per-call token guard; starts ordinal at 0 | Does not expose phase, candidate or account to the provider; accepts no external authority |
| `core/composition/provider.py:MeteredProvider` | Assigns actual-call ordinal; measures known usage once; calls `ContinuationStore.provider_call` | Raw provider cannot safely obtain the wrapper's invocation context; no external recovery hook |
| `core/composition/provider_evidence.py` | Strict receipt shapes, sequential ordinals, physical settlement evidence hash | New receipt shape must be versioned; cannot simply add fields to current v7 receipts |
| `core/composition/recovery.py` | Adopts a matching `composed_provider_completed`; recorded replay forbids invokes | A provider start without that completion immediately raises, even if the independent currency side has settled |
| `zoo/mle_bench_lite/provider.py:BenchmarkProvider` | Exact request format, no retries/redirects, detailed usage, full known bills | Random call UUID, legacy `reserve`, path-derived run identity, no durable response content for adoption; constructor refuses incomplete sidecars |
| `zoo/mle_bench_lite/cny_budget.py` | `quote_call`, `protect_run`, `admit_call`, `settle`, `cancel_control`, `audit_run` | No physical identity knowledge; no cancellation of an admitted call; no portable raw-history audit export |
| `zoo/mle_bench_lite/usage_audit.py` | Compares local start/receipt/completion to independent campaign operations | Assumes one usage directory owns the entire path-hashed currency run; cannot independently audit per-slot directories as one shared run |
| `core/composition/registry.py:build_control` | Fresh providers and isolated workdirs, declaration/runtime binding equality | Must validate an external bridge declaration and per-phase call counts without sharing semantic provider state |
| `core/composition/hierarchical_runtime.py` | Planning, operator and evaluation physical envelopes | Every provider path, including overhead planning and nested evaluator calls, needs the same bridge context; not only proposal generation |

Do not implement this by returning `external_currency=False` from a paid provider or by passing a facade that translates every old `reserve` into `admit_call`. Both conceal missing identity and lifecycle information.

## Bound compatibility and practical limit

The existing default `estimated_utf8_v1` is explicitly `estimate_only`. Its UTF-8 byte count plus 1,024 framing allowance is **not** a hard hosted-tokenizer guarantee. Reject that mode before provider dispatch or protection writes on the external governed path.

For the first supported contract, require `model_capacity_v1` and the frozen service-capacity assumptions already recorded in the repository's provider-bound investigation. With frozen input capacity `I=1,048,576` and configured output allowance `O`, the physical call bound is `I+O` tokens; the CNY bound is exactly `2*I + 8*O` micro-CNY, through `CampaignBudget.quote_call(O)`. For `O=4,096`, those are 1,052,672 tokens and 2,129,920 micro-CNY (2.129920 CNY). These are reservations under the frozen policy, not actual usage or an invoice.

Consequences:

- A current 60,000-token run must refuse before HTTP. Do not silently increase the physical run budget or reduce an already authorized experiment's output/seed/task protocol.
- For a control phase with maximum `n` provider calls, require `n*(I+O)` to fit its configured token reservation, including any other measured token consumption. Currency protection enumerates `n` distinct ordinal obligations. Reject an impossible plan before either authority starts execution.
- `max_tokens` is output capacity, not a total-token quota. The service assumptions and returned detailed usage must cover reasoning/output categories; any breach retains the full bill, invalidates protection and stops both lanes.
- The existing DeepSeek request removes `temperature`, sends `thinking={"type":"enabled"}` and `reasoning_effort="high"`, and does not send a seed. Declare only parameters actually applied. Control seed metadata is not evidence that the service consumed a seed. Keep `immutable_snapshot_verified=false` and `iid_statistically_verified=false`.
- A supplier changing alias behavior, context capacity or billing semantics is a technical compatibility stop. This plan does not re-verify the remote service; its numerical baseline is the pinned local policy/research, not a new current-price claim.

## Versioned identity and module seams

### Identity schema

Introduce a strict immutable `GovernedCallContext` for the external path, `schema_version=1`, containing:

`runtime_id`, `logical_run_id`, `currency_run_id`, `campaign_id`, `policy_sha256`, `physical_plan_ref`, `bridge_plan_ref`, `lane`, `slot_id`, `candidate_id`, `intent_id`, `physical_fingerprint`, `account`, `operation`, `phase`, `ordinal`, `adapter_binding_sha256`, `session_id`, `argument_sha256`.

- `runtime_id` is `composed-v8-governed-external`; current v7 remains unchanged.
- Preserve the current logical UUID. `currency_run_id` remains the 64-hex `usage_run_id(original_root_usage_dir)`. Persist the mapping once in the bridge manifest; controls share that authority identity while using distinct session IDs and fresh counters. Do not derive each control's currency run from its own directory. Do not silently recompute the mapping after relocation; an explicit relocation protocol is out of the first scope.
- `phase` is `operator`, `evaluation` or `planning`; control calls permit only the first two. The original physical operation (`dev`, `anchor`, etc.) remains separately bound. Derive both from the physical authority, not user-supplied provider options.
- `account` and `candidate_id` come from the frozen physical intent, never from the provider's claim. A read-only budget method checks the intent/fingerprint and started status.
- `session_id = sha256(canonical({logical_run_id,lane,slot_id,adapter_binding_sha256}))`. It identifies fresh session scope, not a mutable state snapshot or proof of stochastic independence.
- `argument_sha256` is the current canonical `args/kwargs` hash. Keep it distinct from `wire_request_sha256`, the SHA-256 of the exact HTTP body bytes. The endpoint identity is in the frozen adapter binding; authorization headers and credentials are excluded.
- `call_id = sha256(canonical({schema_version:1, context:full_context, wire_request_sha256}))`. Its 64 lowercase hex characters satisfy the existing CNY call-ID validator. Persist the prepared request before admission; never generate a replacement UUID on recovery.
- Persist an `external_prepared` authority record binding the full identity, output allowance, physical bound, authority quote, exact wire-body hash, and provider contract digest. The CNY `admit_call` projection remains its **existing exact schema**: `{call_id, request_sha256:wire_request_sha256, phase, ordinal}` plus run/lane/slot/bound arguments. Do not silently extend schema-2 currency events.

The bridge plan binds the physical plan reference, both main/control adapter bindings, currency identity/policy, explicit phase call caps and a fixed main CNY ceiling. Use provider governance declaration schema 2 only for this path, with an `external_currency` object and `phase_call_limits={operator:n,evaluation:m}`. The ordinary schema-1 `external_currency=False` declaration remains byte-compatible. The top-level governance config can stay schema 1 because these declarations/options are already frozen inside component specs; the new runtime manifest binds their full meaning.

For this first bridge, all main/control provider sessions use the same frozen CNY authority and DeepSeek protocol/model, while remaining fresh semantic instances. Require the control operator call cap to be at least 1 and the evaluation cap to be nonnegative. Mixed paid/free control providers and zero-obligation paid plans are explicitly unsupported by this first contract; do not pass an empty list to the existing `protect_run` API. Local evaluations with zero provider calls remain supported.

The currency authority uses the existing `physical_plan_ref` in `protect_run(currency_run_id, physical_plan_ref, obligations)` and `audit_run`; `bridge_plan_ref` is an additional private coordinator binding. This avoids a circular dependency between currency protection, the post-protection main ceiling, and the bridge-plan hash.

The fixed main CNY ceiling is derived once from available campaign capacity **after** protecting all this run's controls (and existing campaign obligations). Store that ceiling in the bridge plan. Main admissions consume only main charges/reservations against it and never gain capacity from a control's savings/cancellation. Global campaign admission remains a second constraint; other runs can cause ordinary main refusal. This is a cap, not a second monetary reservation or a promise of main availability.

### Files and ownership

| Proposed file/change | Responsibility |
| --- | --- |
| New `core/composition/external_provider.py` | Strict context/outcome dataclasses and a small bridge protocol; no pricing, HTTP or CNY import |
| `core/composition/{governance,registry,provider,governed,hierarchical_runtime,runtime}.py` | Versioned preflight, fresh binding, trusted invocation context, lifecycle and stop integration |
| `core/composition/budget.py` | Read-only `invocation_identity(intent_id, *, fingerprint) -> dict`; expose derived candidate/account/operation/status without a second ledger |
| `core/composition/{recovery,provider_evidence}.py` | External outcome adoption, new-version receipt validation, replay routing and exact evidence links |
| New `zoo/mle_bench_lite/provider_protocol.py` | Pure exact wire-body construction and response validation shared by legacy/new providers |
| New `zoo/mle_bench_lite/governed_provider.py` | Fresh `GovernedCNYProvider` sessions, actual request and measured result; cannot fall back to legacy `reserve` |
| New `zoo/mle_bench_lite/governed_currency.py` | `CNYInvocationBridge`: protected plan, deterministic call identity, ordered admissions, private outcome spool, CNY reconciliation and independent audit |
| `zoo/mle_bench_lite/cny_budget.py` | Read-only evidence export and reusable semantic reduction for offline verification; preserve all existing event schemas/bytes |
| New `zoo/mle_bench_lite/governed_currency_audit.py` | Replayable semantic cross-authority audit; shares authority reducers, never trusts copied totals |
| Existing `provider.py`, `usage_audit.py` | Legacy behavior preserved; delegate only pure protocol helpers; existing audits remain separate from the governed aggregator |
| New tests named below | Real public Framework, loopback HTTP, crash cuts, tamper and installed-artifact coverage |

The core module also defines these immutable port values, with strict JSON copying for persisted fields:

- `ExternalRunContext`: `logical_run_id`, `runtime_id`, `workdir`, `physical_plan`, `main_provider_binding`, `control_provider_bindings` (slot-to-binding map), `mode` (`live` or `recorded`), and `recorded_bundle` (null for live). Trusted nonserialized capabilities are `store` and `physical_identity_lookup(intent_id, fingerprint)`; they are handed to the bridge authority, never a control operator or lane store.
- `ExternalPlanBinding`: core fields `schema_version=1`, `runtime_id`, `logical_run_id`, `physical_plan_ref`, `bridge_plan_ref`, and opaque JSON `authority_binding`. The CNY adapter strictly validates that object as `currency_run_id`, `campaign_id`, `policy_sha256`, `phase_call_limits`, `session_ids`, `obligations_sha256`, `main_currency_cap_micro_cny`, and `initial_currency_head`. The initial head is a frozen prefix anchor, not a demand that the campaign's current head never advances. Its serialized adapter-specific portion is opaque to core pricing logic.
- `ExternalCallOutcome`: identity/hash fields below are nonempty validated hashes; `response_sha256`, `usage` and `result` may be null only when the associated state requires it. Refusal before admission has `currency_state=not_admitted` and explicit zero known provider tokens; missing/malformed evidence never implies that state.

Core protocol signatures (private integration port, no new public Framework lifecycle):

- `bind_run(context: ExternalRunContext) -> ExternalPlanBinding` prepares/validates a run's bridge plan and protection; live versus recorded mode is explicit.
- `invoke(context: GovernedCallContext, args: tuple, kwargs: dict) -> str` executes one already physically admitted call; known usage remains available through the existing provider meter.
- `recover(context: GovernedCallContext, argument_sha256: str) -> ExternalCallOutcome` only inspects durable evidence and settles/adopts known outcomes; it never sends HTTP.
- `finish_control(slot_id: str, terminal_ref: str) -> None` releases only unused currency obligations after an authoritative terminal and no pending call.
- `audit() -> dict` validates current live evidence; `replay_bundle() -> dict` supplies a frozen private proof for recorded replay without reopening the live currency authority.

`ExternalCallOutcome` contains `call_id`, `context_sha256`, `wire_request_sha256`, `response_sha256`, `usage` (known validated fields or null), `result` (text or null), `outcome` (`returned`, `known_failed`, `known_refused`, `unknown`), `currency_state` (`not_admitted`, `pending`, `settled`), `integrity_reason` (stable category or null), and `outcome_ref`. A known token total with unknown CNY pricing is not a settled success. Never journal exception bodies, credentials or request headers.

## Ordered protocol and every crash boundary

Preparation and invocation run under the existing per-run coordinator lock. SQLite keeps its existing transaction and one-pending-call rule. Never hold a SQLite transaction while making HTTP, and do not add a second competing campaign lock order.

| Last durable boundary | Dispatch/recovery rule |
| --- | --- |
| No plan protection | Validate configuration and hard bounds; zero HTTP. Construction never migrates the ledger. |
| Physical controls protected, CNY protection absent/refused | No execution. Reconcile/retry the same plan protection only; no fresh physical spending. |
| CNY controls protected, bridge-ready manifest absent | Validate exact frozen plan and both authorities, adopt protection idempotently, finish ready record. A different plan fails. |
| Physical operation reserved, not started | Existing physical release is legal; no CNY call admitted, zero HTTP. |
| Physical started / provider-start present, no `external_prepared` | For this versioned bridge, prove no currency call exists and no dispatch path could precede preparation; record a known zero-cost refusal for this ordinal. If evidence is missing/corrupt rather than demonstrably absent, stop unresolved. Do not retry the draw. |
| Prepared identity durable, currency admission absent | Same no-dispatch proof permits a known zero-cost refusal on recovery. During the original uninterrupted call, currency admission may proceed. |
| Currency `governed_reserve` committed, local admitted record absent | Adopt the reservation identity for audit, **do not dispatch on recovery**. With no authoritative outcome, it stays pending; both lanes stop. |
| Both admissions and local dispatch-intent durable, HTTP not known to have completed | Stop unresolved. The marker does not prove whether the service processed a request. No automatic retry, timeout cancellation or zero-cost assumption. |
| HTTP response arrived only in RAM | Lost on crash: unresolved; no retry. A successful service call cannot be reconstructed from a client-side guess. |
| Private validated response outcome durable, CNY pending | Revalidate request/model/usage/bounds, settle the known valid-priced response idempotently, then publish/adopt the Framework completion. No HTTP. Wrong/missing model or missing component usage leaves currency pending while retaining known token evidence. |
| CNY settlement committed, local/provider completion absent | Verify the durable outcome against independent settlement and adopt it; never charge or dispatch again. A currency settlement alone lacks response content and cannot fabricate a successful proposal. |
| Framework provider completion durable, physical operation settlement absent | Existing continuation replays the known outcome into the original physical intent/account; settle once, including known failure. |
| Physical settlement committed, checkpoint absent | Reconstruct the same journal prefix and checkpoint; zero new provider calls. |
| Control terminal durable, unused currency obligations not cancelled | Verify terminal evidence; call existing idempotent `cancel_control` only for untouched obligations. Settled and admitted charges remain. This also releases unused ordinal capacity after a successful phase used fewer calls than its maximum. |
| Currency cancellation committed, local completion projection/checkpoint absent | Adopt the identical cancellation and terminal. Never release a started/pending physical or currency call. |
| Known bound or identity breach at any point | Preserve all trustworthy usage, settle full correctly priced currency and known physical charges, invalidate protection, stop both lanes. Never report pending controls as completed. |

Persist the sanitized response outcome **before** currency settlement and before returning content. The new private spool must retain response text because existing usage receipts intentionally omit it. Use exclusive or atomic file creation, content hashes, file flush/fsync and parent-directory synchronization where publication requires it; the scope remains tested process crashes, not arbitrary hardware power loss. Keep the spool outside candidate-accessible worktree mounts. A partial/invalid outcome is not a completion.

An admitted/no-outcome reservation can remain stuck even when the request never reached the server. This is a deliberate consequence of current `admit_call` semantics. Reliable supplier lookup/idempotency or a separately designed proven-no-dispatch release protocol would be needed to improve availability; neither is assumed here.

## Implementation tasks

### Task 1: Freeze external capability, identity and finite call coverage

**Files:** Create `core/composition/external_provider.py`; modify `governance.py`, `registry.py`, `budget.py`; test `m0/tests/test_governed_external_contract.py`.

**Interfaces:** Produce the strict run-context, plan-binding and call-context/outcome types and `HierarchicalBudget.invocation_identity(intent_id, *, fingerprint) -> dict`. External declaration schema 2 admits only the registered bridge capability and explicit per-control phase call caps; legacy schema 1 remains unchanged.

- [ ] Write failing tests: `test_estimate_only_external_provider_rejected_without_side_effects`, `test_capacity_bound_does_not_fit_60000_tokens`, `test_ordinal_identity_binds_phase_account_candidate_and_wire_request`, `test_zero_token_calls_still_consume_finite_ordinal`, and `test_existing_v7_binding_and_serialization_are_unchanged`.
- [ ] Run `PYTHONPATH=m0 python -m pytest -q m0/tests/test_governed_external_contract.py`; confirm the missing external contract, not an unrelated fixture, causes failure.
- [ ] Implement the strict immutable types, canonical identity rules above, physical-authority lookup, and preflight multiplication of phase call caps by hard bounds. No production HTTP or authority migration belongs here.
- [ ] Run that file plus existing `test_governed_config.py`, `test_governed_sessions.py`, `test_governed_budget.py`; all pass without weakening legacy tests.
- [ ] Review and commit this independently testable contract change.

### Task 2: Factor exact wire protocol and durable response outcomes

**Files:** Create `zoo/mle_bench_lite/{provider_protocol,governed_provider}.py`; minimally modify legacy `provider.py`; test `m0/tests/test_governed_cny_provider.py` and existing `test_mle_provider.py`.

**Interfaces:** Pure `build_request(prompt: str, binding: dict) -> bytes`; `parse_response(raw: bytes, binding: dict) -> ParsedProviderResponse` must retain known usage even if content/model is invalid. Define immutable `ParsedProviderResponse` in `provider_protocol.py` with `response_sha256`, `returned_model`, `usage`, `result`, `finish_reason`, and `integrity_reason` (optional fields are explicit null); the bridge adds invocation identity to construct `ExternalCallOutcome`. `GovernedCNYProvider` creates fresh semantic state and accepts only the bridge's trusted call context; direct unbound calls refuse before HTTP.

- [ ] Write failing tests for byte-identical legacy DeepSeek requests, no ignored temperature/seed claims, deterministic call ID, no credential/prompt/headers in public evidence, durable response-text adoption, wrong model retaining tokens but pending CNY, malformed content with a known bill, and total-only usage without fabricated components.
- [ ] Run the new test file and confirm RED.
- [ ] Implement pure protocol extraction and the fresh provider; do not subclass into legacy random-ID/reserve behavior. Use a private response spool, no redirects/retries, and existing loopback-only HTTP exception.
- [ ] Run new tests plus all `test_mle_provider.py` and `test_mle_currency_integration.py`. Old wire bodies, legacy reserve/settle semantics and audit coverage must remain identical.
- [ ] Review and commit. This deliverable is still externally disabled until Task 3's dual admission is complete.

### Task 3: Connect both authorities before dispatch

**Files:** Create `zoo/mle_bench_lite/governed_currency.py`; modify core `provider.py`, `governed.py`, `hierarchical_runtime.py`, `runtime.py`; test `m0/tests/test_governed_cny_bridge.py`.

**Interfaces:** Produce `CNYInvocationBridge.bind_run`, `invoke`, `finish_control`, and the frozen `ExternalPlanBinding`. Use existing `CampaignBudget.quote_call/protect_run/admit_call/settle/cancel_control/audit_run` without changing their event schema. Core obtains the physical context, then passes it to the bridge.

- [ ] Write RED tests with loopback `observe_dispatch`: at every received request, the exact physical intent is started, the matching CNY call is pending, both protected plans match, and both binding hashes match the bytes received.
- [ ] Add paired tests with identical main behavior but cheap versus expensive control usage; main's frozen currency cap and public budget remain identical. Add main/control contention, two framework runs sharing one temporary campaign, multiple operator calls, provider-backed planning, and nested evaluator calls.
- [ ] Implement protection readiness and the ordered per-call protocol. Enforce all phase ordinal limits; use one currency-run mapping and private aggregate spool while every session keeps its own consumable usage state. Main and controls always use `admit_call`; legacy `reserve` must never appear for bridge requests.
- [ ] Distinguish ordinary pre-dispatch budget refusal from unknown authority state/integrity failure. Ordinary main refusal drains controls; unknown costs or bound/model/identity violations stop both lanes. Preserve original account attribution.
- [ ] Run the new bridge file plus `test_governed_runtime.py`, `test_governed_worktree.py`, `test_governed_currency.py` and the previous tasks' tests. Confirm zero non-loopback requests.
- [ ] Review and commit this first fully guarded mock-server invocation path.

### Task 4: Reconcile all crash cuts without duplicate effects

**Files:** Modify `core/composition/{recovery,provider_evidence}.py` and `governed_currency.py`; test `m0/tests/test_governed_cny_recovery.py`.

**Interfaces:** Implement `recover(context, argument_sha256) -> ExternalCallOutcome` and versioned receipt parsing. Existing v7 receipt dictionaries and recovery branches remain unchanged. Core consults the hook only for the explicit external runtime and never invokes it from ordinary recorded replay.

- [ ] Write parameterized subprocess/SIGKILL tests for every row of the crash table that publishes state. Use explicit synchronization files/pipes after the real fsync/SQLite commit, not a guessed sleep. Record server request counts outside the killed process.
- [ ] Assert each cut's exact currency pending/settled state, physical status, known token subtotal, allowed/no resume, and unchanged server request count on repeated recovery. Include response stored before currency settlement and currency settlement before Framework completion.
- [ ] Implement adoption and known-zero refusal only where the protocol plus independently audited absence proves no request could have started. All ambiguous cases remain blocked. No deletion/release of admitted CNY calls.
- [ ] Run the new recovery file with `--basetemp=/dev/shm/mori-cny-bridge-recovery`, plus existing native/worktree/durable-flush recovery tests. Include at least one run with normal filesystem publication to verify the spool's durability path separately from tmpfs timing.
- [ ] Review and commit after an independent crash-state review. Any unsupported arbitrary native evaluator side effect remains explicitly outside the certificate.

### Task 5: Independent cross-authority audit and offline replay

**Files:** Create `zoo/mle_bench_lite/governed_currency_audit.py`; extend `cny_budget.py` with read-only export and shared semantic reduction; modify bridge audit/replay and core inspect/replay routing; test `m0/tests/test_governed_cny_audit.py`.

**Interfaces:** `CampaignBudget.export_governance_evidence(run_id, plan_ref) -> dict` returns the exact policy, complete event prefix and head needed to recompute shared campaign capacity at a single transaction snapshot. `verify_governance_evidence(bundle: dict) -> dict` shares the authority reducer; `RecordedCurrencyView` has no live-ledger writer/HTTP capability. `CNYInvocationBridge.audit/replay_bundle` implements the core port.

- [ ] Write RED tests: rehashed wrong run/lane/slot/phase/ordinal/account/candidate/wire hash; missing/extra currency calls; deleted local outcomes; changed provider/model; substituted ledger; changed fixed main cap; duplicate physical settlement; cancellation after admission. Recompute hashes in tamper cases so semantic checks do the work.
- [ ] Add a completed public Framework replay with network and live `CampaignBudget` construction monkeypatched to fail. Assert `external_calls=0`, identical recorded outcome/receipt identities, no new charges, and byte-identical original ledger/spool. Unknown outcomes must refuse replay rather than create evidence.
- [ ] Implement snapshot export, pure reduction and exact many-record joins. Only actually admitted calls require a CNY reservation; a separately verified pre-admission zero-cost refusal must have no CNY call row and can still have a Framework start/completion pair. A missing row for an allegedly admitted call is an integrity failure. Keep full campaign evidence private because validating shared capacity requires the relevant prior/foreign run events, not just a self-reported total for this run. Do not expose it through control views or public model context.
- [ ] Verify live audit rereads both authorities, whereas recorded replay verifies a frozen proof and states its original head. Neither proves the live supplier invoice or malicious-owner rollback resistance. A recorded proof is not a current-live-campaign balance.
- [ ] Run the new audit file plus existing currency semantic-forgery, governed receipt, replay and journal-snapshot tests; review and commit.

### Task 6: Public end-to-end acceptance and honest capability gate

**Files:** New `m0/tests/test_governed_cny_framework.py`; update `docs/GOVERNED_CONTROLS.md` and a new bridge guide/example using temporary fixture ledger only. Add a **new** verifier version after the active accepted version; preserve every historical command/time budget and exact authentic archives.

**Interfaces:** Existing `Framework.from_profile/evolve/inspect/replay` only. Registry composition supplies separate fresh main/control providers and the shared authority bridge. No standalone alternate experiment runner.

- [ ] Write failing public tests for native plus real git-worktree execution, schedule `[0,1,2]`, explicit pause/resume, ordinary main exhaustion with remaining controls drained, failed control retained, and known integrity/unknown costs stopping both lanes. Use a real loopback server and temporary ledger explicitly initialized to the frozen 200-CNY policy for fixture purposes only.
- [ ] Exercise a multi-call main operator and a control phase with declared maximum 2 but actual 1; unused control capacity stays held until terminal cancellation and never increases main's frozen cap. Exercise provider-backed evaluation as well as a zero-provider local evaluator.
- [ ] Add an installed-wheel smoke test invoked outside the repository and a copied example; no test-module imports, no credentials, no non-loopback access. The example creates only a temporary **fixture** ledger and says so prominently.
- [ ] Run all new files and the existing full provider/currency/governed regression groups. Then run ordinary examples, tooling, axioms and package/import checks. Do not run concurrent full acceptance jobs.
- [ ] Commit, freeze the exact SHA and run complete additive versioned acceptance. Certificate fields may say the bridge and mock-server protocol are implemented/tested; keep real supplier invocation, invoice verification, IID, immutable model snapshot and formal benchmark/release fields false.
- [ ] Keep migration/live use as a separate follow-up against the unchanged original 200-CNY authorization. This implementation does not schedule a third pilot or replace real evidence with fixture results.

## Bounded follow-up sequence and genuine unknowns

Execute Tasks 1–2 first as a small offline review unit. Tasks 3–4 are the critical ordered-admission/recovery unit and should not be exposed as a paid capability before their crash matrix passes. Tasks 5–6 make the capability independently auditable and usable through the public API. This is follow-up implementation work, not a promise to deliver a trustworthy paid bridge in the remaining current acceptance window.

Technical blockers/limits, with dispositions:

1. **No hard bound for the existing 60,000-token estimate-mode experiment.** Known, not a missing implementation detail: capacity mode cannot fit. Offline bridge work proceeds; that exact paid protocol remains ineligible for the formal governed path. A verified tighter serving/tokenizer contract or a separately changed experiment design is needed; do not silently alter budgets.
2. **Remote idempotency/status lookup is not established.** No source used here documents a supplier operation key that proves no charge after a timeout. Therefore admitted/no-outcome calls remain pending. This limits availability, not the offline safety implementation.
3. **Hosted alias and sampling contract can differ from local declarations.** Current manifest already says immutable snapshot unverified and temperature ignored in DeepSeek mode. Mock-server tests cannot establish remote IID or guarantee future alias semantics; keep those claims false and fail on observed model/bound drift.
4. **Current usage audit is directory-scoped; bridge ownership is run-scoped.** This is concrete implementation work in Tasks 1 and 5, not something to waive by merging control histories into one mutable provider. Relocation must fail explicitly until a separate mapping migration is designed.
5. **Independent stores cannot provide cross-authority atomic commit.** The documented ordered protocol, known-outcome reconciliation and conservative stranded reservations are the supported semantics. A release/compensation protocol for provably unstarted admitted calls would require a separate authority design; do not slip one into `cancel_control`.
6. **Actual campaign state is intentionally unknown in this preparation.** No balance, pending-call state, schema migration status or available control capacity was read. Real migration requires the existing anchored/quiescent lifecycle and verified rehearsal stated in the authority spec; offline work does not require that live state.

## Self-review and evidence status

The plan covers each resident spec requirement relevant to the bridge: fixed independent sessions, finite full-call bounds, seven-account attribution, protected future currency, fixed main visibility, both admissions before HTTP, known-failure charging, unresolved stops, native/worktree entry points, all publication/settlement crash cuts, exact replay, and independently recomputed evidence. It deliberately does not close remote IID, benchmark superiority, invoices or arbitrary native side-effect recovery.

Identity projection is explicit: raw logical UUID is never passed where the CNY API requires a 64-hex run ID; the `sha256:` plan prefix is preserved; argument and wire hashes are distinct; main/control ordinal budgets are not inferred from observed response tokens; new receipt fields are versioned; currency events retain their current exact schema. Plan generation ran no acceptance or bridge tests and supplies no passing certificate.


## Implementation refinements during public-path verification

- A bridge is registered as a zero-argument factory. Each runtime/replay gets a fresh authority coordinator; existing campaign capacity is shared through its ledger, not through mutable run context.
- ExternalRunContext additionally carries a nonserialized read-only map of raw provider sessions.
- ExternalCallOutcome includes required detached `provider_state`; a durable post-call state is adopted before continuing after a missing Framework completion. The private response also stores the observed adapter-binding digest.
- A positive schema-2 token bound determines a frozen per-intent ordinal ceiling `reserved_token // hard_call_bound`, including planning. Explicit operator/evaluation caps also apply. Zero actual usage cannot permit unbounded calls. Schema-1 zero-bound compatibility remains unchanged.
- Core physical refusals and provider readiness refusals require independently proven zero-admission records; missing evidence is never treated as free usage.
- Public Framework replay validates and captures the live authority before reconstruction. Reconstruction uses frozen proof without HTTP or new ledger events; detached whole-Framework replay after deleting the live database is not claimed.
- The standalone offline example exercises a temporary fixture ledger and loopback HTTP only. No live campaign migration or third pilot occurred. Whole-project/versioned results must be taken from their actual terminal records, not inferred from targeted passes.
