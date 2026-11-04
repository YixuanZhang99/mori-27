# Governed external-provider bridge

`composed-v8-governed-external` connects an explicitly registered provider bridge to the existing physical and CNY authorities. It retains `Framework.evolve`, `inspect` and `replay`. V6 remains the legacy path; V7 remains the offline governed path. No checkpoint is silently converted between them.

This implementation has been exercised with temporary ledgers and loopback HTTP. It has not migrated the user's live campaign, made a new real model request, verified an invoice, or established IID sampling or a performance advantage. Current versioned and hosted acceptance status must be checked separately.

## Run the standalone offline example

Install the package and use a new work directory:

```bash
python -m pip install ./m0
python m0/examples/governed_cny_offline.py --workdir /tmp/mori-cny-example
```

The script has no test imports or repository-path modifications. It can be copied outside the checkout after installation. It starts a loopback server, explicitly creates and migrates a new **fixture** ledger, pauses and resumes the same Framework run, then checks recorded replay. It never reads the user's credentials or real ledger.

Expected output includes two completed controls, four loopback requests, zero external-model requests, `fixture_settled_micro_cny: 152`, and successful replay with zero new HTTP requests or ledger events. These amounts describe synthetic usage; they are not real spend. Preserve the selected work directory to inspect its physical journal, private call evidence and fixture SQLite ledger. Use a different empty directory for another example run.

## Assembly and supported contract

The example is the complete configuration reference. A trusted application registers a zero-argument factory:

```python
registry.install_external_bridge(
    "cny_invocation_v1", lambda: CNYInvocationBridge(existing_campaign)
)
```

Each Framework runtime receives a fresh bridge coordinator. Main and control providers use the same frozen campaign policy but distinct semantic sessions. Control factories remain registered explicitly with their schema-2 capability; the main provider must declare the same bridge. Core never imports CNY pricing or HTTP.

The first supported transport is `GovernedCNYProvider`. It sends only its declared DeepSeek request parameters and uses `model_capacity_v1`. The schema-2 sampling declaration is `supplier_unverified`: local input isolation does not prove the remote service's statistical independence. Direct unbound provider calls are rejected. The bridge validates the exact wire body and obtains both physical and monetary admission before calling transport.

The frozen capacity contract reserves 1,048,576 input tokens plus the configured output allowance per possible call. With four output tokens, that is 1,048,580 physical tokens. A 60,000-token run therefore refuses before HTTP; the bridge does not silently raise its budget. Estimated UTF-8 input size is not accepted as a hard bound. These are the repository's frozen service assumptions, not a claim that a future supplier cannot change them.

Control operator/evaluation call counts are declared explicitly. Every external physical intent also has a fixed ordinal ceiling derived from its original token reservation and positive hard call bound, including planning. Zero-token responses do not create extra call slots. Main CNY capacity is frozen before controls execute; cheaper or cancelled controls do not increase it. The shared campaign's global admission remains an additional constraint.

## Lifecycle and failures

The existing CNY ledger requires explicit `enable_governance(expected_policy_sha256, expected_head)` before protection. Constructors and calls never migrate it automatically, reset charges or create replacement funds. The offline example performs that operation only on a new fixture database.

| Evidence at interruption | Behavior |
| --- | --- |
| Proven physical/readiness refusal with no currency admission | Durable known-zero refusal; ordinary exhaustion can drain protected controls |
| Currency admitted, no authoritative response | Keep the pending reservation; block new work; never retry automatically |
| Private response and provider state durable, currency unsettled | Validate and settle the original known bill, restore state and adopt the same result without HTTP |
| Currency settled, Framework completion missing | Cross-check independent authority and private outcome; adopt without charging twice |
| Known priced bound or adapter-identity breach | Preserve the full bill and known physical cost; invalidate protection and stop both lanes |
| Wrong model or incomplete pricing details | Preserve known physical usage but keep monetary usage unresolved; do not price an unknown response as if it matched |
| Ordinary invalid/unfinished content with known valid usage | Retain a failed sample and its bill; no redraw replaces it |

Private response records include the observed adapter binding and declared provider checkpoint state, so a fresh adapter after restart cannot erase a prior change or reset a known stateful sequence. Prepared requests and response content stay in the private run evidence directory, outside candidate worktree mounts. No credentials or authorization headers are included.

The tested fault boundaries include actual SIGKILL around prepared/dispatch/response/outcome publication, plus public Framework recovery between a response and currency settlement. This is process-crash evidence for those cuts, not a claim covering every lifecycle cut, external exactly-once effects or machine power loss.

## Inspection and replay

Inspection recomputes call identities, request hashes, ordinals, physical intent labels, CNY reservations/settlements, private outcomes and control terminals. It distinguishes pending unknown usage from missing settled evidence. A hash-consistent record with another candidate, account or phase still fails semantic validation.

Public `Framework.replay()` first validates and captures the original live authority. Reconstruction then consumes a frozen currency proof and recorded provider/evaluator outcomes without new HTTP or ledger writes. The public workflow is not claimed to run after deleting the original database. `RecordedCurrencyView` separately supports detached read-only proof verification; that narrower capability does not create another public Framework lifecycle.

## Module map

| Module | Responsibility |
| --- | --- |
| `core/composition/external_provider.py` | Immutable run, plan, call and outcome ports; finite identity and call-count contracts |
| `registry.py`, `governed.py`, `provider.py` | Explicit fresh bridge construction, physical context and per-request admission |
| `invocation.py` | Shared planning/operator/evaluation lifecycle: start, metering, known settlement, unresolved retention and integrity ordering |
| `recovery.py`, `provider_evidence.py` | Known-outcome adoption and independent physical receipt links |
| `zoo/mle_bench_lite/provider_protocol.py`, `governed_provider.py` | Exact request bytes, sanitized response parsing and one transport attempt |
| `governed_currency.py` | Frozen monetary capacity, private evidence, dual admission, recovery and cross-record audit |
| `cny_budget.py`, `governed_currency_audit.py` | One SQLite monetary authority; shared live/offline reducer and atomic read-only export |

The broader framework gaps remain listed in [FRAMEWORK_STATUS.md](FRAMEWORK_STATUS.md). This bridge does not close the full benchmark matrix, all original abstractions or RUBRIC v1.0 requirements.
