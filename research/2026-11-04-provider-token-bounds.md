# Provider token bounds after the second MLE attempt

Status: investigation and implementation rationale; new admission code passed final local verification, not a successful formal budget claim. The completed second attempt remains frozen at `aedede3c2b78a5c2b57074c70d510af710f5af4e`.

## Observed failure and source cause

The completed spooky baseline run used 5 calls and 62,830 tokens against its 60,000-token limit. Four candidates had been evaluated before the last response exceeded the limit by 2,830; the actual cost was retained and the run was classified failed. The leaf/full record subsequently reported 62,856 tokens over 4 calls. The final six-run campaign also found nomad/baseline at 63,502 tokens. Three other runs were officially graded. See the [complete failed/successful matrix](experiments/2026-11-04-deepseek-pilot-attempt-2/README.md); no complete baseline/full pair survived.

`zoo/mle_bench_lite/provider.py:BenchmarkProvider.__call__` currently sets output allowance to `min(max_completion_tokens, token_budget - used)` and sends it as DeepSeek `max_tokens`. This does not subtract input consumption. The response is charged before the actual total is checked, which correctly preserves costs but cannot prevent the overrun. The physical remaining-reservation repair fixed the earlier arbitrary 12,000-per-call mismatch; it did not establish a pre-request input bound. v70 explicitly does not certify that bound.

## Primary-source evidence, checked 2026-11-04

DeepSeek describes character-to-token ratios as approximate and treats returned usage as the actual measurement. It publishes an offline tokenizer example, but the page does not establish exact HTTP serving equivalence for every request: [Token usage](https://api-docs.deepseek.com/quick_start/token_usage/).

The chat API defines `max_tokens` as an output limit; input plus generation must fit the model context. Its `finish_reason` distinguishes normal completion from length termination. The model metadata documents a context capacity of 1,048,576 tokens and output maximum of 393,216: [Chat API](https://api-docs.deepseek.com/api/create-chat-completion/), [model metadata](https://api-docs.deepseek.com/api/list-models/). An output limit alone is not a total-request quota.

The official model repository supplies tokenizer and standalone prompt encoding, including the thinking effort prefix. The reference files were downloaded without credentials for read-only analysis at revision `314113f8a7dadb388215396ba5fbee2c610a04d6`: [pinned encoding reference](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/314113f8a7dadb388215396ba5fbee2c610a04d6/encoding/README.md). The inspected tokenizer uses BPE, an empty normalization sequence and byte-level pretokenization. No downloaded code was executed or added as a production dependency. Its format is useful evidence, not proof that the current hosted alias has identical unreported framing.

## Decision for the next implementation

Separate a measured cost, an estimate, and an enforceable call bound. A formal physical-budget claim requires a declared adapter bound covering input, permitted output, framing and any additional billed categories. A conservative documented capacity bound can qualify under its explicit service contract; it may be too large for a 60,000-token run. An offline reference estimate or a percentage margin must never be labeled an exact API bound.

A practical estimated mode may subtract a named, versioned input estimate before choosing output allowance, record the estimation policy, preserve known charges and stop on drift/overrun. It must remain explicitly uncertified for a hard total-token bound. Do not silently increase the current run budget, shrink a completed failure matrix or turn an estimated quote into a successful formal certificate.

A main overrun can consume protected control capacity despite correct reservation arithmetic. Preserve the main account attribution, record the protection breach, stop further paid calls, and report controls incomplete where applicable. A separate CNY conservative reservation still protects the authorized monetary limit under its frozen billing assumptions; it does not prove the smaller token limit. Formal control scheduling must also account for shared monetary capacity.

Before another experiment, implement and test the chosen call-bound contract, persist finish reason and bound/estimate provenance in usage evidence, and distinguish ordinary pre-call budget refusal from a charged integrity failure. Reuse the existing 200 CNY campaign without reset. The full remaining-budget, unknown-usage and genuine overrun regressions must remain.

## Download provenance

- `tokenizer.json`: SHA-256 `c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b`; 6367257 bytes.
- `tokenizer_config.json`: SHA-256 `6ac8c8dc065ed118161d02dd532749ae3f52c243deac27872134fae2f50d8547`; 801 bytes.
- `encoding/README.md`: SHA-256 `a34a5ca98c65e5b5b2bedd693cc2e18e732fe50192723fb6937ae07219c23739`; 12164 bytes.
- `encoding/encoding.py`: SHA-256 `13231c592e958fb39e2af6001dae69d90e7a36b265702b9b390236fb387599e2`; 37962 bytes.

## Implemented policy under verification

The new DeepSeek default `estimated_utf8_v1` uses UTF-8 prompt bytes plus a fixed 1,024 framing allowance and requires the entire configured output allowance before dispatch. This deliberately conservative engineering envelope is labelled `estimate_only`; 1,024 is a chosen allowance, not a service-documented framing bound. Drift invalidates admission evidence while retaining all measured charges. The explicit `model_capacity_v1` reserves the frozen input capacity plus output allowance under the existing service assumptions; it refuses the current 60,000-token run. Neither mode changes the authorized run or campaign budget.

Start and usage receipts record matching admission quotes and whitelisted completion reasons, without raw prompts. The independent campaign journal supplies the true preceding per-run usage, so a rehashed local quote cannot certify a fabricated earlier balance. Typed pre-dispatch capacity refusal propagates as a known-cost stop through standard operators and both configured budget paths; earlier admitted candidates remain available. Durable continuation records and replays the typed refusal after a previous checkpoint, while unknown invocations remain non-retryable. This is not a general solution for every provider exception or arbitrary native process-crash window.

The third real attempt and versioned acceptance are still pending. Local regression results cannot replace those external measurements. Resident controls and seven-account governance remain separate unfinished deliverables.

## Local verification on the final implementation

The complete `make test-linux examples axioms tooling build verify-import` pipeline passed on an unchanged file fingerprint: 1,836 pytest cases (373.13 s), 60 tooling tests, examples, static axioms, wheel build and import verification. Total pipeline time was 376.032 s. The log SHA-256 is `db81bcaddd0c0530355f1dd03fc66bf576d31d563c922119e23802be7fa898e9`. This is local validation, not a v71 certificate or same-SHA hosted CI.

A fresh reviewer found three Important defects: a fabricated prior-balance quote, missing durable refusal completion, and prior overrun classified as ordinary exhaustion. All three reproduced RED before the fixes; their final targeted group passed 115 tests. Dedicated crossover-refusal and custom multi-call operator-stop regressions remain deferred minor coverage items. The public full-arm/cost tests do not certify arbitrary third-party operator implementations.
