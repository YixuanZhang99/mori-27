# v67 acceptance: S8 configured population selection and crossover

This version adds one explicit group for bounded population membership,
authoritative sampling, two-parent text crossover, and recovery through the
public Framework. The [S8 guide](../../../docs/POPULATION_RUNTIME_V67.md) gives
the configuration and limits; the
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md) distinguishes
implemented sub-scopes from remaining design requirements.

The new group runs `tests/test_population_frontier.py`,
`tests/test_population_components.py`, and `tests/test_composed_population.py`
with a 480-second timeout. Every v66 command group and timeout is unchanged,
including S1–S7, full unfiltered pytest, the complete offline research example,
static axioms and real Linux security/process recovery regressions. A complete
successful run contains 37 checks: 28 command groups and 9 historical/source
checks. Internal pytest always enforces `--fail-on-skip --strict-markers`.

The certificate adds `population_stage_evidence`; its own group and the whole
run must pass before certification. Elite retention does not certify novelty
or MAP-Elites selection, and text crossover does not prove code signatures.
There is no external benchmark campaign claim. Earlier stage evidence keeps
its original scope. Run `make check` on Mac and `make accept-linux` on supported
Linux x86_64. The wrapper requires fresh passing evidence at the exact commit
before main advances; implementation creates no initial v67 certificate or
journal.

## Archived v66 evidence provenance

Historical journals are required through v66, retaining rejected-v14 and
superseded-recursive-v43 exceptions. Existing v1–v66 verifier sources and
records remain immutable. Newly archived `verifier/v66/LAST_RUN.json` and
`verifier/runs/v66.jsonl` are exact copies from successful
[S7 CI run 40992561406](https://github.com/YixuanZhang99/mori-27/actions/runs/40992561406),
head `fb8a0f7e703c2300b95149536837cd2569e3f1e7`. The artifact is
`linux-acceptance-fb8a0f7e703c2300b95149536837cd2569e3f1e7`, with acceptance
directory `linux-acceptance/20261030T023547.041213Z-5jsq277a/`.

Archival independently verified the completed successful Actions job and exact
artifact workflow head, the downloaded ZIP SHA-256
`25dac54e551f08284b6b14bf4bd2b4ff0ff06be7be16f4d295f094a2491c478f`,
and the summary/certificate/journal identities. The summary reports exit zero,
a fresh passing certificate/journal, unchanged source history, no timeout and
no errors. All 36 checks and 1,552 pytest cases passed in 815.844 seconds. The
single journal entry matches the certificate checks and its bytes equal
`new-runs.jsonl`. Absent archive targets were created exclusively; no existing
history was overwritten. Old verifier source was not rerun against v67 wiring.
Main advanced without force only after this exact-commit evidence was verified.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v66/LAST_RUN.json` | `bd5db5f0038dc326b33f5ff6fef9a70142b76580a5ceb9569344164a647d35e6` |
| `verifier/runs/v66.jsonl` | `cdcbc1a420d1899b23c8d4d1b0f8843747de76da925515e9e47ae7e5f90f778d` |

Tooling protects these exact bytes and earlier archives. This records S7's
actual result at its own commit and does not certify S8.
