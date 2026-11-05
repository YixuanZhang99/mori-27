# Resident IID-RS and seven-account coverage — design decision

This design follows the existing unified abstraction and RUBRIC C1/C3. It does not close those requirements. The user authorized autonomous development and asked to avoid routine configuration questions. Implementation remains separate from the completed, frozen six-run diagnostic pilot.

## Intent and existing constraints

Keep `Framework.evolve/inspect/replay` as the public execution interface and preserve the six kernel concepts. A configured run must eventually provide resident random-search controls, one cost authority, frozen independent control inputs, protected allocation, recoverable paid invocations, and recomputable evidence. A greedy pilot arm or `dev_baseline` incumbent reevaluation cannot stand in for IID-RS. C4 and the B benchmark criteria remain independent obligations.

Current source: `ComposedRuntime._run` schedules main cycles only; hierarchical intent dictionaries lack seven-account attribution; remaining operator quotes use global/direction/candidate slack. `MeteredProvider` wraps a mutable adapter. `ContinuationStore` is currently tied to durable worktree mode and durably completes successful text calls plus typed known-budget refusals. Other known-cost exception outcomes still need governed adoption. These are the actual integration points, not grounds for a new standalone control runner.

## Three interface designs compared

1. Minimal interface: one optional controls object, private resident scheduling inside the existing runtime, and ledger-owned protected obligations. Small caller burden and no extra public lifecycle; risks leaving main/control call orchestration duplicated.
2. Extensible interface: a common governed propose/evaluate path plus session factories and native/worktree adapters. This concentrates cost, terminal outcome and recovery rules, but exporting every internal port would burden callers.
3. Common caller: an opt-in governance block/profile builder that freezes explicit control requirements and validates all capabilities before calls. Easy to start, but convenience defaults cannot conceal missing bounds, sampling guarantees or monetary protection.

Decision: retain the common caller form, use a private governed invocation implementation shared by main/control, and place holdback/account projections in the existing budget authority. Avoid another runtime inheritance mixin, a second Framework, a second physical ledger, or a replacement main policy. No new public methods are required. A detailed implementation plan must pin the final schema and signatures before coding; the illustrative examples from independent reviews are not accepted API names.

## Mandatory behavior

- An absent opt-in preserves exact existing assembly serialization, manifests, `composed-v6` checkpoints and journal semantics. Enabled runs use a new explicit identity; old runs cannot acquire controls during resume.
- One operation settlement owns each actual physical charge. Global/direction/candidate and seven-account totals are projections, not additive charges. Accounts are exactly explore, exploit, reeval, control, repair, handoff, overhead; unsupported operations remain zero. Classify before invocation, never reclassify failure as repair.
- Main admission and remaining quotes subtract protected control capacity for every configured unit. Holdback is capacity, not fake spending or a permanently open invocation. Converting an obligation to an operation must not double-count or temporarily release it to main.
- Control slots and their sampling distribution, requests, initial artifact, seeds and allowed ContextPack are frozen before main calls. Each draw starts from independent semantic state. Shared transport and supplier authorization are permitted; conversational state, randomness and consumable usage counters must not leak across draws.
- Controls receive no main parents, search memory, adaptive feedback, audit scores, or prior control outcomes. Their candidates/evidence stay outside frontier, admission, parent selection, proxy fitting and memory.
- Schedule an initial sample and fixed resident slots. Ordinary main exhaustion/convergence drains planned controls; an explicit checkpoint pause does not. Unknown costs, integrity failures and actual overruns stop all new paid work. Failed draws remain in the predetermined sample set rather than being retried until favorable results appear.
- Every paid invocation binds run, lane, slot/candidate, intent, account, ordinal, request hash and adapter/session identity. Persist terminal success and known-cost failure before downstream settlement. Adopt proven durable outcomes exactly once; a start without authoritative completion is unresolved, never an automatic retry.
- Inprocess and supported worktree adapters must exercise the same accounting/isolation rules. Do not claim arbitrary inprocess evaluator crash adoption, external exactly-once effects, or power-loss durability from a local journal.
- Inspection recomputes account coverage and control residence from durable evidence. Missing, failed, incomparable or unresolved controls remain explicit. Successful residence is separate from superiority, actual USD efficiency and deterministic remote-model replay.

## Call-bound prerequisite revealed by real usage

The second diagnostic attempt produced 62,830 tokens against a 60,000 limit after valid remaining allocation. A correct quote cannot constrain a service whose actual consumption exceeds it. See [provider bound investigation](../../../research/2026-11-04-provider-token-bounds.md).

Required governance must validate a defensible total-call bound for every claimed hard unit before dispatch. Estimates are permitted only with explicit uncertified status. Unexpected bound violations settle full actual cost to the original account, invalidate the corresponding guarantee and stop new calls; never claim remaining protected capacity is intact merely because its logical counter is positive. Shared CNY authorization must also leave room for planned controls or reject the unsupported formal claim. Currency policy stays in its task adapter.

## Implementation sequence and evidence gates

The provider call-bound/finish-reason contract now has an implementation and full local verification at `c617931`; v71 and a third real attempt remain pending. Use the complete second-attempt failure matrix and preserve the distinction between estimate-only and service-capacity bounds. Then implement seven-account intents and protected capacity in HierarchicalBudget, shared governed invocation/session isolation, resident scheduling, native/worktree recovery, and live audit/reporting. Write a task-level plan before that implementation. Preserve all historical verifiers and regression groups.

Public Framework tests must include uncopyable stateful providers, multi-call hooks, poisoned feedback, main early termination, explicit pause, control failure, unknown cost, admitted-bound violation, rehashed account/slot/context tampering and all relevant start/outcome/settlement/checkpoint crash windows. At least two actual execution adapters must demonstrate the shared interface. Follow independent review and full versioned validation with separate real evidence; fixtures do not close all formal runs or benchmark criteria.
