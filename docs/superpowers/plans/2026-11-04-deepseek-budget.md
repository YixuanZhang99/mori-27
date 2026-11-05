# DeepSeek campaign budget implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task. The user authorized autonomous implementation and the cumulative CNY 200 pilot; do not request another routine design approval.

**Goal:** Run the authorized six-run DeepSeek pilot through a shared, durable CNY admission controller, preserving failures and authentic evidence.

**Architecture:** Keep monetary service policy in `zoo/mle_bench_lite`, outside the six-concept core. Use SQLite transactions with synchronous durable commits for a serial campaign's append-only reservation/settlement journal; verify its hash chain and independently stored head on each access. Explicit creation is separate from opening, and a frozen campaign identity binds providers and resumes.

**Tech Stack:** Python 3.12 standard-library SQLite, existing HTTP provider and pytest fixtures.

**Spec:** `research/2026-11-04-deepseek-pilot.md`, existing S9 evidence/isolation contract, user authorization of cumulative CNY 200.

## Decisions and boundaries

- SQLite provides atomic check/reserve across processes and crash recovery; a handwritten JSONL journal would require a second transaction protocol. No new external dependency.
- Store integer micro-CNY. Frozen peak upper bound: input 2 and output 8 micro-CNY/token. Ignore cache discounts in the admission bound; preserve validated cache/reasoning details for evidence. Never report this bound as an actual invoice.
- Reserve `1048576*2 + output_allowance*8` before HTTP. Reject new operations while any reservation is unresolved. This is intentionally serial, matching the pilot; it is not certification of a general parallel pool.
- No implicit ledger creation/reset during provider or agent startup. Missing, corrupt, replaced or internally inconsistent state fails closed. Trusted-owner malicious rollback of the entire ledger remains outside the local integrity guarantee.
- Keep paid generation disabled until provider, agent, pilot and independent audit agree on this contract. A standalone ledger is not sufficient launch evidence.
- Freeze thinking enabled/high and send `max_tokens` for DeepSeek. Preserve the existing generic OpenAI-compatible fixture path. Use the documented alias and record that immutable model weights are not verified.
- No raw prompts, completions, secrets or auth headers in monetary records. Candidate processes cannot access the ledger or credential files.
- Pricing identity precedes monetary settlement: a missing/different DeepSeek response alias preserves known token receipts but retains the full unresolved reservation. Its price cannot be assumed to equal Flash. Content and finish-reason failures under the correct model still settle before rejection.

## Review focus

Unknown response across a fresh output directory must still block spending; simultaneous reserve attempts must not exceed admission; missing prompt/completion counts must not become zero; truncated/empty responses must retain costs; resume with a different campaign must fail before HTTP.

### Task 1: Persistent campaign admission

Files: new `m0/zoo/mle_bench_lite/cny_budget.py`, `m0/tests/test_mle_cny_budget.py`.

Interface: `CampaignBudget.create(path, limit_micro_cny=200000000)` explicitly creates; `CampaignBudget(path)` only opens. `reserve(call_id, request_sha256, output_allowance, run_id=...)` commits before dispatch; `settle(call_id, usage, response_sha256)` records a validated known upper bound; `snapshot()` and `manifest_binding()` report state and immutable identity. Providers derive a persistent run ID from the canonical usage-directory path; audits use it to find calls even when local sidecars are missing.

- [x] Write and observe failing tests for shared lifetime, conservative reservation, exhaustion, unknown restart, atomic concurrent reservation, corrupt/deleted journal records, missing files and invalid usage.
- [x] Implement the transactional ledger and strict usage validation. Reopen and replay all records on every operation.
- [x] Run the focused tests and retain literal, independently calculated expectations.

### Task 2: Provider protocol and accounting

Files: `provider.py`, `test_mle_provider.py`.

- [x] Add local HTTP tests proving DeepSeek wire fields, zero requests on budget refusal, missing usage blocking another run, and known charges retained on truncated output.
- [x] Add explicit DeepSeek format, shared ledger binding, request-before-reserve validation, durable reservation before HTTP, usage receipt and monetary settlement before content validation.
- [x] Preserve cache/reasoning details, response identity/fingerprint, and reject non-stop completion. Keep no retries and redirect refusal.
- [x] Verify the existing generic provider tests as well as new budget tests.

### Task 3: Real pilot integration and reporting

Files: `composed_agent.py`, `pilot.py`, `usage_audit.py`, CLI/local runner, relevant tests and S9 docs.

- [x] Freeze the same request settings and campaign identity in every arm's spec, command, contract, resume check and final report. Set both arms' output cap to 16384 to allow reasoning plus code.
- [x] Require explicit existing ledger configuration for the official DeepSeek endpoint. Validate its location outside candidate-visible mounts and output roots.
- [x] Cross-check monetary journal with request/response receipt hashes and complete run call sets; report settled upper bound, unresolved reservations, and unverified invoice/snapshot status on successes and failures.
- [x] Test public Framework execution, all six-run propagation and a fresh-output attempt after unresolved usage.

### Task 4: Acceptance and authorized execution

- [x] Add v69 retaining all v68 commands and authentic archived v68 CI evidence; run full Linux acceptance, build and immutable import verification.
- [x] Obtain independent review and resolve confirmed issues; commit and create local backup.
- [ ] Push the verified branch when the original remote becomes writable; require same-SHA remote CI before advancing main.
- [x] Create exactly one real campaign ledger for this authorization; freeze parameters and run zero-model preflight.
- [ ] Complete the six-run real pilot. All smoke/retries share this ledger; unknown usage requires reconciliation, never automatic resending.
- [ ] Preserve failure evidence and actual results without unsupported superiority or full-benchmark claims. Revisit the broader alignment backlog after real usage feedback.

## Incremental validation record

2026-11-04: ledger availability regression failed first, then 19 ledger tests passed. DeepSeek HTTP contract failed before implementation; ledger/provider group then passed 49 cases. Independent review reproduced acceptance of the wrong first response alias; the new `deepseek-pro` regression failed before repair. The repaired five-file MLE group passed 149 tests, including wrong/missing alias, unknown response across new directories, and durable reservation visible at actual HTTP dispatch. Independent follow-up review confirmed all three bad identities refuse same-directory restart as well. A separate process terminated with `os._exit(17)` after reserve; reopening retained 2,228,224 micro-CNY and refused a new request.

The prior isolation-repair baseline completed all 1,750 Linux tests without skips (478.20 seconds). That result predates this increment and is not its full-suite evidence. This increment's architecture checks, 52 tooling tests, build and 1,020-file immutable import verification passed. Its full Linux suite and examples have been launched and remain pending; inspect `outputs/cny-provider-linux-tests.log` in the local chat workspace before committing. No real campaign ledger or paid model request has been created. Task 3 is still required before launching the real pilot.

Subsequent progress: the ledger/provider intermediate tree completed 1,781 Linux tests (363.16 seconds) and four examples. Integration then added public Framework HTTP execution, six actual child-process runs sharing one ledger, independent receipt reconciliation, fresh-output refusal after unknown usage, and allowlisted currency export. The integration/provider/pilot group passed 100 tests. Independent review exposed missing reverse coverage: deleting a whole local call or crashing after reserve but before started could hide that call in per-run audit. Added failing regressions, then persistent run identity and bidirectional call-set reconciliation; the final ledger/provider/integration group passed 66 tests. An independent mixed success-plus-crash reproduction confirmed 120 known tokens, 360 settled micro-CNY, 2,129,920 reserved micro-CNY, incomplete costs and refusal of both restart paths. The 7 cloud-wrapper tests passed. Final integrated full Linux/tests/examples/axioms/tooling/build/import checks are running in `outputs/cny-integrated-validation.log`; do not substitute the intermediate 1,781-test result for this final state. No paid model request has been made.

Final integrated checks completed successfully: 1,794 Linux tests without skips (368.09 seconds), four offline examples, 11 architecture axioms, 56 tooling tests, wheel/sdist build and 1,020-file immutable import verification. v69 now retains all 29 v68 command groups and exact timeouts, adds one explicit isolation/currency group, and archives the authentic v68 CI bytes. Transition tests were observed failing before implementation and then passed; independent review found no important transition issue. A clean local commit and full v69 execution are the next gate. No initial v69 certificate is fabricated and no real campaign ledger or paid generation exists yet.

Later execution record, 2026-11-04: clean source commit `5fa85d3ab7c4f643550ecaa2223a65231d7f7a86` passed full v69 in 874.524 seconds, with all 39 checks, a fresh passing certificate and exactly one matching journal entry. Source commit, clean tree and historical verifier files remained unchanged. This is local Linux evidence, not same-SHA hosted CI. The local chat workspace retains `outputs/v69-verified-evidence.json`, the original acceptance artifacts and a verified Git bundle. The official three-task runtime smoke also passed. The documented DeepSeek price/capacity policy was rechecked against official pages before spending.

The sole real CNY 200 ledger was initialized, production preflight reported `ready=true` with no missing requirements, and the six-run pilot started from a read-only archive of that exact commit (1,194 file hashes checked). The first external response produced a validated usage receipt and settled monetary upper bound. Execution is still in progress; neither six successful submissions nor benchmark superiority is claimed. Working-tree documentation changes do not change the frozen running source. No credential contents enter these records.
