# Physical invocation lifecycle ownership

## Intent and scope

Deepen the physical invocation seam identified in the bedc5b3 A7 review and the 75f397e follow-up work package. Planning, operators and evaluation must obtain measured execution from one private owner. Main/control and governed/ungoverned hierarchical paths use that owner. Flat non-hierarchical accounting is outside this change and retains its existing provider-floor check. This is an engineering refactor toward A7, not full A7 certification.

## Decision

The implementation choice is made under the user's continuing autonomous-development instruction. A callback-only facade would leave callers responsible for terminal/settlement ordering. Moving the whole runtime into a new class would retain broad implicit dependencies. Instead, introduce `InvocationLifecycle(budget, store, settle, *, governance=None)` with planning/operator/evaluation entry points. Its private per-operation state owns start, provider metering, unknown/known distinction, measured floor, settled state and integrity ordering. Domain request construction, executor selection and final identity validation stay with orchestration, which receives an already charged result.

`settle` is the existing physical measurement adapter (`HierarchicalRuntime._settle_physical`): it owns durable wall measurements, unit coverage, actual-node/evaluation normalization and the authoritative settlement. Keeping this real policy adapter also preserves the existing interrupted-wall regression seam. The lifecycle takes no runtime object. Governance supplies its existing meter and post-settlement integrity checks; only the lifecycle pairs them.

## Required behavior

- One start and at most one settlement per invocation; unknown usage retains its reservation.
- Known operator failures retain costs and a failed result; known ordinary planning failures settle then propagate; UsageError remains unresolved.
- A governed operator terminal is persisted before settlement. Provider binding is checked after metering scope exits and costs are settled before integrity/identity rejection.
- Measured executor errors retain their known bill and existing governed failure/integrity events. BaseException process-crash simulation must not be converted into an ordinary failure.
- Preserve v6/v7/v8 identities, event fields/order, existing test sources and all historical verifiers/timeouts. Old supported checkpoints must resume without new provider calls during transcript adoption.
- No new dependencies, public Framework methods, paid calls or live-ledger migration.

## Proof

Direct lifecycle tests use the real hierarchical authority and inspect settled/reserved amounts across all three phases. Existing public Framework suites cover native/worktree, physical units, failed samples, actual SIGKILL, protected currency and recorded replay. Add a cross-commit resume rehearsal from the installed 75f397e wheel. Full project verification and clean same-SHA v73 acceptance remain separate evidence from architecture quality.
