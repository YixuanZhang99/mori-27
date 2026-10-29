# v64 acceptance: S5 physical hierarchical budgets and fidelity

This version adds the configured Framework runtime's global/direction/candidate
physical budgeting and fidelity group, and separately executes a complete
offline research example. Its scope is atomic reservations across declared
physical dimensions and hierarchy levels, budget views in proposal inputs,
actual evaluation requests with comparable fidelity baselines, and explicit
low-sample stopping rules. Runtime configuration and limits are documented in
the [S5 usage guide](../../../docs/HIERARCHICAL_BUDGET_V64.md). It does not certify external GPU workloads,
production resource enforcement, external model campaigns or benchmark scores.

The new regression group runs `tests/test_hierarchical_budget.py` and
`tests/test_composed_budget.py`. A separate command group executes
`examples/composed_research_offline.py`, also included in `make examples` on
Mac. All 23 v63 command groups and timeouts remain unchanged, including every
S1–S4 feature group, full unfiltered pytest, static axioms, Linux sandbox,
seccomp, process identity and recovery regressions. A complete successful run
contains 34 checks: 25 command groups and 9 historical/source checks. Pytest
continues to enforce `--fail-on-skip --strict-markers`.

The certificate adds `hierarchical_budget_stage_evidence`, requiring both new
groups to pass alongside the entire acceptance. Earlier stage evidence remains
separate. The [alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md)
retains the exact implemented subscopes and unresolved requirements; completing
five stage increments does not certify every clause or production capability.

Run `make check` on Mac and `make accept-linux` on supported Linux x86_64.
The wrapper runs in a disposable copy and requires a new passing certificate
and exactly one matching new journal entry with unchanged source history.
Implementation does not create an initial v64 `LAST_RUN.json` or
`runs/v64.jsonl`. Real execution evidence is stored under a unique
`artifacts/linux-acceptance/<run-id>/` directory.

## Archived v63 evidence provenance

Historical verification requires passing journals through v63, retaining the
rejected-v14 and superseded-recursive-v43 exceptions. Existing v1–v63 verifier
sources and records remain immutable. The newly archived
`verifier/v63/LAST_RUN.json` and `verifier/runs/v63.jsonl` are exact copies from
successful [S4 CI run 40898306157](https://github.com/YixuanZhang99/mori-27/actions/runs/40898306157),
head `41a8dc83340b787fdbfef73dbee2c8759751bbe2`. The artifact name is
`linux-acceptance-41a8dc83340b787fdbfef73dbee2c8759751bbe2`, with acceptance
directory `linux-acceptance/20261029T150737.888658Z-pggl_mpj/`.

Archival independently checked the exact completed/successful Actions run and
artifact workflow head, and verified the downloaded archive digest. The summary
reports exit zero, a fresh passing certificate/journal, unchanged source
history, no timeout and no errors. All 32 checks and 1,307 pytest cases passed.
The single journal entry matches certificate checks and its bytes equal
`new-runs.jsonl`. Absent destinations were created exclusively; no history was
overwritten or rerun against v64 wiring.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v63/LAST_RUN.json` | `04dbad2a62b140e9596a8df9a34c3e58153a446a47a749565046c0a68fa530c2` |
| `verifier/runs/v63.jsonl` | `ba91d5b210d2e9ee2b09e85be5ea4413573150caf0168f69ea92d02340c383d1` |

The tooling suite protects these bytes and all earlier archived evidence. This
archive certifies S4's precise scope at its own commit. S5 is certified only by
a complete successful Linux run at its actual commit; main advances only after
that exact commit passes. Final-stage results are recorded in the CI artifacts
and delivery report, without creating a circular commit solely to record its
own SHA.
