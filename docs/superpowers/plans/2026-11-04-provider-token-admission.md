# Provider token admission implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Preserve the live pilot's frozen source and campaign ledger.

**Goal:** Prevent predictably unaffordable MLE requests, retain completion/usage evidence, and end ordinary provider budget exhaustion without discarding an admitted candidate.

**Architecture:** The benchmark adapter owns a versioned admission policy. It keeps a full requested output allowance and checks input plus output before reservation/HTTP. A typed, known-cost operator stop travels through the existing Framework settlement path. The adapter never claims a local estimate is an API hard bound.

**Tech Stack:** Python standard library, pytest, existing Framework, loopback HTTP and SQLite campaign ledger.

**Spec:** `research/2026-11-04-provider-token-bounds.md`; prerequisite for `docs/superpowers/specs/2026-11-04-resident-control-design.md`.

## Global constraints

- Preserve all historical tests, acceptance verifiers and evidence, including failed real runs.
- Do not modify frozen attempt 2, restart it or reset the shared CNY 200 campaign.
- Generic OpenAI-compatible provider behavior remains the legacy output-only admission contract unless a supported policy is explicitly selected; new policies require DeepSeek's frozen campaign metadata.
- DeepSeek defaults to `estimated_utf8_v1`: input envelope = UTF-8 prompt bytes + 1024 framing allowance. It is explicitly an estimate, not a proven hosted tokenizer bound. Full configured completion allowance is required; do not lower it near exhaustion and spend on predictable truncation.
- Explicit `model_capacity_v1` uses campaign context capacity plus full output allowance as a conservative total bound under the frozen service limits. This intentionally refuses a 60,000-token run. No budget is raised silently.
- Measured charges and unknown usage keep existing settlement rules. An input-envelope breach invalidates admission evidence and blocks subsequent HTTP while preserving known costs. Length termination is a known-cost failed candidate, not unknown billing.
- Do not add tokenizer dependencies or run downloaded reference code.

## Review focus

- Input-heavy Unicode prompts must be measured in UTF-8 bytes, with no paid request on refusal.
- Known drift, overrun and malformed usage must not become a zero-cost graceful stop.
- Resume must reject changed policies and a persisted envelope breach before HTTP.
- Search stops must settle physical/node costs, retain the last admitted candidate and replay without extra calls.
- Completion reason must survive rejected content without storing response text or secrets.

### Task 1: Adapter admission and evidence

Files: `m0/zoo/mle_bench_lite/provider.py`, new `token_admission.py`, `usage_audit.py`, `m0/tests/test_mle_provider.py`.

Interfaces: `BenchmarkProvider(..., token_admission: str | None = None)`; `core.llm.ProviderBudgetExhausted(ValueError)` denotes a pre-dispatch budget refusal for the current call. `token_admission` binding contains mode, guarantee level and policy parameters; start and receipt retain the same per-call quote (used/remaining/input/output/total). New receipt `finish_reason` is a whitelisted enum or null.

- [x] RED: Loopback response establishes 45,787 prior tokens; remaining 14,213 refuses another 16,384-output request before ledger reservation/HTTP. Assert prior receipts and charges unchanged, current usage zero.
- [x] RED: Unicode/input-heavy refusal, strict capacity refusal, persisted reason on length termination, policy-change restart rejection, measured input drift remains charged and audit incomplete.
- [x] Implement deterministic policy/quote and audit validation; no raw prompts saved. Legacy receipts remain readable without fabricated new evidence.
- [x] GREEN: Run provider/currency/audit tests and retain their existing overrun/unknown regressions.

### Task 2: Settled stop through public Framework

Files: `m0/core/llm.py`, `composition/contracts.py`, `defaults.py`, `population.py`, `hierarchical_runtime.py`, `runtime.py`, `m0/tests/test_mle_currency_integration.py`, `test_composed_budget.py`.

Interfaces: `OperatorBudgetExhausted(OperatorFailure)` carries the existing CostVec/coverage contract; the standard prompt and crossover operators translate only typed provider exhaustion. Both runtime budget paths settle known cost before a durable `composed_cycle_aborted` stop. Ordinary failures continue their original evidence path.

- [x] RED: Both MLE arms produce a valid first candidate then refuse a later request with insufficient input-plus-full-output capacity; assert submission materializes, only affordable HTTP calls occur, stop reason is durable, physical tokens match receipts, no unresolved money and replay makes no request.
- [x] RED: Nonhierarchical public Framework typed stop preserves an admitted candidate and settles prior usage; ordinary operator error behavior remains covered by existing tests.
- [x] Implement typed propagation and settled stop; do not fabricate candidate evidence for the refused invocation.
- [x] GREEN: Run composed/hierarchical/MLE regression groups.

### Task 3: Verification and evidence checkpoint

- [x] Run `UV_PROJECT_ENVIRONMENT=/usr/local/share/mori27-local/dev UV_PYTHON=/usr/bin/python3.12 UV_OFFLINE=1 make test-linux examples axioms tooling build verify-import`.
- [x] Review changes against the frozen policy and real failure sequence; fix findings with regressions.
- [x] Document actual local verification and limitations. Commit implementation and tests together after checks; preserve local rollback bundle. Do not claim v71 acceptance or a new real pilot until independently executed.
- [x] Audit attempt 2 after its existing process terminates, retain all six outcomes and cumulative campaign costs. Update stale local source metadata only after launcher exit.

## Execution record

- Adapter: 8 new regressions failed before implementation; provider/currency group then passed 76 tests.
- Public stop: 4 regressions failed before runtime handling; composed/hierarchical/currency group passed 116 tests.
- Independent review: 3 Important issues reproduced before fixing; final targeted group passed 115 tests. Known-refusal recovery now also modifies `m0/core/composition/recovery.py`, covered by `m0/tests/test_composed_recovery.py`.
- Final stable-source pipeline: 1,836 pytest cases and 60 tooling tests passed, plus all examples/axioms/build/import checks, exit 0, source fingerprint unchanged. Earlier full run passed 1,833 cases but is retained only as diagnostic evidence because review edits overlapped it.
- Attempt 2: audited all 6 terminal runs; 3 valid/graded, 3 total-token failures. Same cumulative CNY200 ledger; settled upper bound 3.242064, pending 0.
- Minor coverage deferred: dedicated crossover-refusal and custom multi-call operator-stop cases. No new formal acceptance or third real attempt is claimed.
