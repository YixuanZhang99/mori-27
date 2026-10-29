# v61 acceptance: S2 configured evaluation contracts

This version adds the S2 evaluation-contract group to the configured Framework
runtime. Its certification scope is canonical evaluation transport, candidate
artifact and evaluation-context binding, explicit legacy-adapter cost/failure
evidence, public/private projections with restricted admission inputs, and
preservation of evaluation evidence in checkpoints and replay.
The group runs `tests/test_evaluation_contract.py` and
`tests/test_composed_evaluation.py` through the active test environment.

Every v60 command group and timeout is preserved, including the S1 registry,
default-component and public-runtime tests, the complete unfiltered pytest
suite, static axioms, real Linux process/sandbox/seccomp checks, and historical
recovery regressions. A successful complete run contains 30 checks: 21 command
groups and 9 historical/source checks. Tests remain subject to
`--fail-on-skip --strict-markers`.

The certificate adds `evaluation_contract_stage_evidence` and retains the S1
composition evidence separately. S2 certification does not remove the legacy
M0 interface or certify every component outside the configured runtime. It
does not close the S1 population, worktree, HITL or event-bus integration gaps.
S3 memory/knowledge feedback, S4 three-layer admission, and S5 hierarchical
budgets retain their own completion flags and acceptance requirements. See the
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md) for the precise
requirements and recorded coverage. No real external provider or benchmark
campaign is inferred from offline protocol tests.

The [S2 usage and compatibility guide](../../../docs/EVALUATION_CONTRACT_V61.md)
documents native domains, measurement coverage, private evidence, and the
explicit refusal to resume unbound S1 `composed-v1` checkpoints as v2 runs.

Run `make accept-linux` on supported Linux x86_64. Mac development uses
`make check`. The wrapper runs in a disposable copy, requires a fresh matching
certificate and exactly one new passing journal entry, and verifies unchanged
source history. No initial v61 `LAST_RUN.json` or `runs/v61.jsonl` is created or
committed as part of implementation. Actual execution writes evidence under a
unique `artifacts/linux-acceptance/<run-id>/` directory.

## Archived v60 evidence provenance

Historical verification now requires passing journals through v60, with the
existing rejected-v14 and superseded-recursive-v43 exceptions preserved.
The v1–v60 verifier sources and existing records remain unchanged. The newly
archived `verifier/v60/LAST_RUN.json` and `verifier/runs/v60.jsonl` are exact
copies from successful [S1 CI run 40889093796](https://github.com/YixuanZhang99/mori-27/actions/runs/40889093796),
head `06491ce5639dd33f7f89bc8e1288f881b54ecb8c`. The artifact is named
`linux-acceptance-06491ce5639dd33f7f89bc8e1288f881b54ecb8c`; its acceptance
directory is `linux-acceptance/20261029T141222.361011Z-7phfd9sj/`.

Before archiving, the Actions head, completed status and success conclusion
were checked. The artifact summary reports exit zero, fresh passing certificate
and journal, unchanged source history, no timeout and no errors. All 29
certificate checks passed. The single journal entry matches those checks, and
the journal bytes equal `new-runs.jsonl`. Absent destinations were created
exclusively; no old file was overwritten and v60 was not rerun against v61
wiring. The tooling suite protects these exact bytes and the earlier v58/v59
archives independently.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v60/LAST_RUN.json` | `23bab6054fe40f3823946dba1dfcd70b48b144d1f8326b19beb11881a9f8cf03` |
| `verifier/runs/v60.jsonl` | `578d795426ec5bfa0aaca90aca1533747da4cf1b7cb16960488538090182dc64` |

The v60 archive certifies its S1 commit and precise scope only. v61 success
remains pending until the actual S2 commit passes its own full Linux run.
