# v66 acceptance: S7 configured worktree execution and recovery

This version adds an explicit configured-runtime group for real Git worktree
commands, process identity writing and verification, and recovery through the
public Framework entry point. The [S7 guide](../../../docs/WORKTREE_RECOVERY_V66.md)
describes the contract and platform limits. The
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md) records each
implemented sub-scope separately from remaining abstract requirements.

The new group executes `tests/test_composed_worktree_executor.py`,
`tests/test_process_identity_writer.py`,
`tests/test_composed_worktree_framework.py`, and
`tests/test_composed_recovery.py`, with a 480-second timeout. Every v65 command
and timeout remains unchanged, including full unfiltered pytest, the complete
offline research example, S1–S6 groups, static axioms and real Linux
sandbox/seccomp/process regressions. A complete successful run contains 36
checks: 27 command groups and 9 historical/source checks. Every internal pytest
command enforces `--fail-on-skip --strict-markers`.

The certificate adds `worktree_recovery_stage_evidence`; certification requires
the new group and the entire acceptance run to pass. It does not claim
Mac/Linux security equivalence, distributed execution, population assembly or
external benchmark completion. Earlier stage evidence retains its historical
scope. Run `make check` on Mac and `make accept-linux` on supported Linux
x86_64. The wrapper requires fresh passing evidence at the exact candidate
commit before main advances. Implementation creates no initial v66
`LAST_RUN.json` or `runs/v66.jsonl`.

## Archived v65 evidence provenance

Historical journals are required through v65, retaining rejected-v14 and
superseded-recursive-v43 exceptions. Existing v1–v65 verifier sources and
records remain immutable. Newly archived `verifier/v65/LAST_RUN.json` and
`verifier/runs/v65.jsonl` are exact copies from successful
[S6 CI run 40911722972](https://github.com/YixuanZhang99/mori-27/actions/runs/40911722972),
head `62a73631800bdf17eff0e5342fda0212a5303a50`. The artifact is
`linux-acceptance-62a73631800bdf17eff0e5342fda0212a5303a50`, with acceptance
directory `linux-acceptance/20261029T162745.526158Z-0yv_v922/`.

Archival independently verified the completed successful Actions job and exact
artifact workflow head, the downloaded ZIP SHA-256
`9eabe0b083a6e7ab5d1c479fd9894a22df8cbc363bcabfdfc0cc9c477e608444`,
and the summary/certificate/journal identities. The summary reports exit zero,
a fresh passing certificate/journal, unchanged source history, no timeout and
no errors. All 35 checks and 1,477 pytest cases passed in 529.923 seconds. The
single journal entry matches the certificate checks; its bytes equal
`new-runs.jsonl`. Absent archive targets were created exclusively, preserving
all existing history. Old verifier source was not rerun against new wiring.
Main was advanced without force only after this exact-commit evidence passed.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v65/LAST_RUN.json` | `b4f2c5a9c41213039a4ed7f94059edccef7d22ac5da83d0662bb613fdce6bba2` |
| `verifier/runs/v65.jsonl` | `e6dcca23ad745518490b114b5b1249c81cf211d995d7dd366446821078273943` |

Tooling protects these exact bytes and every earlier verified archive. This is
S6 evidence at its own commit, not a successful S7 execution claim.
