# v68 acceptance: S9 configured MLE evaluation and paired subset pilot

This version adds an explicit group for MLE-Bench Lite development evaluation,
anchor calibration, negative feedback, population search and paired pilot
orchestration through the configured Framework. The [S9 guide](../../../docs/MLE_COMPOSED_V68.md)
describes data boundaries and pilot interpretation; the
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md) records scope and
the exact-commit acceptance gate.

The new group runs `tests/test_mle_composed.py`, `tests/test_mle_provider.py`
and `tests/test_mle_pilot.py`
with a 480-second timeout. Every v67 command group and timeout is retained,
including the complete unfiltered pytest run, all prior composition stages,
the offline research example and real Linux security/recovery regressions.
A complete successful run contains 38 checks: 29 command groups and 9
historical/source checks. All internal pytest calls enforce
`--fail-on-skip --strict-markers`.

The certificate adds `mle_composed_stage_evidence`; its own group and the
whole run must pass before certification. CI uses protocol fixtures and local
model services. It does not download Kaggle datasets, call paid external
models, produce an official MLE-Bench score or certify host parity. Actual
pilots have separate evidence and never become 22-task results merely by
passing this verifier.

The same CI workflow also has an independent `mle-cloud-runtime` job. It
installs the hash-locked CPU dependencies, hydrates the pinned official Git
LFS objects, and executes all three official CSV graders on synthetic data
with network access disabled. Its `mle-runtime-<SHA>` artifact is separate
from these 38 checks. Both CI jobs must pass before the commit advances main.

Mac uses `make check`; supported Linux x86_64 uses `make accept-linux`.
Main advances only after the same commit has fresh successful CI evidence.
No initial v68 certificate or journal is fabricated in the source tree.

## Archived v67 evidence provenance

Historical journals are required through v67, retaining rejected-v14 and
superseded-recursive-v43 exceptions. Existing v1–v67 verifier source and
historical records remain unchanged. Newly archived
`verifier/v67/LAST_RUN.json` and `verifier/runs/v67.jsonl` are exact copies
from successful [S8 CI run 40994318799](https://github.com/YixuanZhang99/mori-27/actions/runs/40994318799),
head `49be71ec079f1412a4a8e74086064c4db121c363`. Its artifact is
`linux-acceptance-49be71ec079f1412a4a8e74086064c4db121c363`, artifact ID
`12951450684`, with acceptance directory
`linux-acceptance/20261030T025420.293270Z-_svb09o5`.

The downloaded ZIP SHA-256 is
`afe65a8437c429d813f2cec6339650382cfbddc9eacfda95d014fff693a52ae4`.
The completed successful Actions run and artifact head were verified when
S8 advanced main. Archival rechecked the summary, fresh certificate and
single new journal entry: all 37 checks and 1,632 pytest cases passed in
868.971 seconds, source history was unchanged, and there was no timeout or
error. The journal equals `new-runs.jsonl` byte for byte. Archive targets
were created exclusively; no earlier record was overwritten and the old
verifier was not rerun on v68 wiring.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v67/LAST_RUN.json` | `7c3586bca97082fce0ca25f027a5f26b7cd8f4977c3f4bcbd972a4ef0165c37f` |
| `verifier/runs/v67.jsonl` | `f4d8a6d1de90b84c40d57399e5c6597bdb5f927385c5609980ae55562ee79da4` |

Tooling protects these exact bytes and all previous version transitions.
This archive records S8's result at its own commit and does not certify S9.
