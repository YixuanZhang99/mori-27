# v62 acceptance: S3 scoped context and local knowledge feedback

This version adds the configured runtime's scoped memory and local knowledge
feedback group. Its scope is actual ContextPack consumption in candidate
generation, local source opening with separate ground/audit lanes, benchmark
knowledge isolation, and logical run/context state through checkpoint and
independent replay. Exact runtime options and remaining limitations are
documented in the [S3 usage guide](../../../docs/CONTEXT_FEEDBACK_V62.md) and
recorded alongside implementation evidence in the alignment checklist.

The explicit group runs `tests/test_composed_context.py`,
`tests/test_composition_context.py`, and `tests/test_composition_knowledge.py`.
Every v61 command group and timeout is preserved, including S1 composition,
S2 evaluation contracts, complete unfiltered pytest, static axioms, and real
Linux process/sandbox/seccomp and recovery tests. A complete successful run
contains 31 checks: 22 command groups plus 9 historical/source checks. All
internal pytest runs enforce `--fail-on-skip --strict-markers`.

The certificate adds `context_feedback_stage_evidence` and retains the S1/S2
stage evidence separately. It does not certify external network knowledge
services, semantic retrieval quality, real provider campaigns, external
benchmarks, S4 three-layer admission or S5 hierarchical budgets. Unfinished S1
population/worktree/HITL/event-bus integration remains visible in the
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md).

Run `make accept-linux` on supported Linux x86_64. Mac development uses
`make check`. The wrapper executes in a disposable copy and requires a fresh
matching passing certificate plus exactly one new journal entry while checking
unchanged source history. Implementation does not create initial v62
`LAST_RUN.json` or `runs/v62.jsonl`; actual execution saves evidence under a
unique `artifacts/linux-acceptance/<run-id>/` directory.

## Archived v61 evidence provenance

Historical verification requires passing journals through v61, preserving the
rejected-v14 and superseded-recursive-v43 exceptions. Existing v1–v61 verifier
sources and evidence are immutable. The newly archived
`verifier/v61/LAST_RUN.json` and `verifier/runs/v61.jsonl` are exact copies from
successful [S2 CI run 40891610362](https://github.com/YixuanZhang99/mori-27/actions/runs/40891610362),
head `babe764c7b2bb83d5fdb0151316a8677d21052d7`. The artifact name is
`linux-acceptance-babe764c7b2bb83d5fdb0151316a8677d21052d7`, with acceptance
directory `linux-acceptance/20261029T142735.737452Z-iyrrqn3y/`.

Archival independently checked the exact Actions head, completed status and
success conclusion. The summary reports exit zero, a fresh passing certificate
and journal, unchanged source history, no timeout and no errors. All 30 checks
passed; the single journal entry matches the certificate checks, and journal
bytes equal `new-runs.jsonl`. Absent destinations were created exclusively.
No history was overwritten or rerun against v62 wiring.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v61/LAST_RUN.json` | `57b70a0cffcfd8962c11bb03d124fb0176fe0628f7771a7f9b57e82ecddccc5b` |
| `verifier/runs/v61.jsonl` | `dea8ac41d8b5c3721aae17ba624183cd979acb82c3ece5509e90f57a11fd8244` |

The tooling suite protects these bytes and all earlier archived evidence. This
archive certifies the precise S2 scope at its own commit; S3 certification
remains pending until the actual S3 commit passes its complete Linux run.
