# v63 acceptance: S4 layered admission and isolated final audit

This version adds an explicit layered-admission group for native domains in
the configured Framework runtime. Its scope is distinct dev/admission/final
evaluation identities, a hard admission-call limit, independent per-evaluation
token reservations, reproducible comparison receipts, and a frozen final
selection whose audit evidence does not enter search or memory feedback.
The default metric profile retains its declared dev-only compatibility path.

The new group runs `tests/test_layered_admission.py` and
`tests/test_composed_admission.py`. All 22 v62 command groups and their timeouts
remain unchanged, including S1/S2/S3 and full unfiltered pytest, static axioms,
real Linux sandbox/seccomp/process tests and recovery regressions. A complete
successful run contains 32 checks: 23 command groups and 9 historical/source
checks. Pytest rejects skips and xfail through
`--fail-on-skip --strict-markers`.

The certificate adds `layered_admission_stage_evidence` separately from prior
stage evidence. It does not claim top-k selection, HITL integration, S5
hierarchical budgets, external provider campaigns or external benchmark
scores. Unsupported modes must be rejected explicitly. The
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md) retains all
remaining S1/S2/S3 requirements alongside S4's precise implemented scope.

Run `make accept-linux` on supported Linux x86_64; Mac development uses
`make check`. Acceptance runs in a disposable copy and requires matching new
certificate/journal evidence with unchanged historical sources. Implementation
does not create initial v63 `LAST_RUN.json` or `runs/v63.jsonl`. Actual run
evidence is saved under a unique `artifacts/linux-acceptance/<run-id>/` path.

## Archived v62 evidence provenance

Historical verification requires passing journals through v62, retaining the
rejected-v14 and superseded-recursive-v43 exceptions. Existing v1–v62 verifier
sources and records remain immutable. The newly archived
`verifier/v62/LAST_RUN.json` and `verifier/runs/v62.jsonl` are exact copies from
successful [S3 CI run 40894739044](https://github.com/YixuanZhang99/mori-27/actions/runs/40894739044),
head `ccb91c86c4b8dc05d52fb3f09c3fd6cfc13d8891`. The artifact name is
`linux-acceptance-ccb91c86c4b8dc05d52fb3f09c3fd6cfc13d8891`, with acceptance
directory `linux-acceptance/20261029T144626.619184Z-9goats1k/`.

Archival checked the Actions job's successful completed status and artifact's
exact workflow head independently. The summary reports exit zero, a fresh
passing certificate/journal, unchanged source history, no timeout and no
errors. All 31 checks and 1,252 pytest cases passed. The single journal entry
matches the certificate checks, and its bytes equal `new-runs.jsonl`. Absent
destinations were created exclusively; no history was overwritten or rerun
against v63 wiring.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v62/LAST_RUN.json` | `6cdf8f58a833a814c17a15d7c05619fb82c3ef72f2026e9a9fadf1479786a154` |
| `verifier/runs/v62.jsonl` | `17efa48878f855facf04ed25c4ef6e46499ef9e1e9407f1977ee3376e1adefb8` |

The tooling suite protects these bytes and all earlier archived evidence. This
archive certifies S3's precise scope at its own commit. S4 remains pending
until the actual S4 commit passes its complete Linux run.
