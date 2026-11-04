# v69 acceptance: S9 isolation and shared currency admission

This version retains every v68 command group and timeout, including unfiltered
pytest, all S1–S9 groups, Linux security/recovery tests and the offline research
example. It adds `mle_private_order_and_shared_currency_campaign_end_to_end`
with a 480-second timeout, executing `test_mle_isolation.py`,
`test_mle_cny_budget.py`, `test_mle_currency_integration.py` and
`test_mle_provider.py`. A successful run has 39 checks: 30 command groups and
9 historical/source checks. Every internal pytest call enforces
`--fail-on-skip --strict-markers`.

The new certificate field `mle_currency_and_isolation_evidence` requires both
its explicit group and the complete run to pass. It covers private anonymous
row ordering, paired data identity, exact sandbox readiness, pre-dispatch CNY
reservation, restart/refusal, missing sidecar reconciliation, and shared
currency identity through the public Framework and six subprocess pilot runs.
The [operating guide](../../../docs/DEEPSEEK_CAMPAIGN_BUDGET.md) describes the
service and accounting contract.

Local model services and synthetic task data are fixtures. The verifier never
downloads Kaggle data, calls paid providers, certifies an immutable model
snapshot or verifies a supplier invoice. It does not establish a full 22-task
benchmark score, host parity, malicious-owner rollback resistance or a general
parallel campaign pool. Real pilot evidence is recorded separately.

`make accept-linux` runs this verifier in a disposable copy; the source tree
does not contain a fabricated initial v69 certificate or journal. Before main
advances, both full acceptance and the independent pinned official CPU-runtime
smoke must pass on the same commit in CI. Local evidence is useful but does not
replace that remote gate.

## Archived v68 evidence provenance

`verifier/v68/LAST_RUN.json` and `verifier/runs/v68.jsonl` are exact bytes from
successful [CI run 41032740938](https://github.com/YixuanZhang99/mori-27/actions/runs/41032740938),
head `dfe29cb4265fd939a203d587a57b523efbe52c36`. The artifact is
`linux-acceptance-dfe29cb4265fd939a203d587a57b523efbe52c36`, ID `12967906224`,
with acceptance directory `linux-acceptance/20261030T092114.970149Z-4u2qz4gk`.

On 2026-11-04, the completed successful run, artifact head and GitHub-reported
archive digest were checked again. The archive was downloaded again and its
SHA-256 matched `9d444ed17556147a28e401de9e0c89f8123d1fc82907dccf4f3356eb1da5c031`.
The summary, certificate and single new journal entry agree: 38 checks passed,
1,740 pytest cases passed, wrapper elapsed time 976.032 seconds, no timeout or
error, and source history unchanged. `v68.jsonl` equals `new-runs.jsonl` byte
for byte. The archive files were created exclusively; no historical file was
overwritten and v68 was not rerun on the new wiring to manufacture history.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v68/LAST_RUN.json` | `33f864e1c7e36ad7b19ffa461004176b32d9bbe210f90af5aaec4ce52cec457b` |
| `verifier/runs/v68.jsonl` | `f603892915439fc04873a517fce67a7ca1ec92a5bd5932c8e7a3aeb8e8edeea7` |

Tooling verifies these bytes and preserves every earlier version transition.
The archive proves the earlier S9 result at its own SHA, not v69 success.
