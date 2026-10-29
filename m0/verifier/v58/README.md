# v58 acceptance

This version covers admission evidence validation, physical usage accounting,
budget ledger integrity and the seccomp v2 x32 guards. It retains every v57
behavioral regression group, the complete unfiltered pytest suite, static axioms,
and the historical passing-journal chain through v57. Rejected v14 and the
superseded recursive v43 harness remain the documented historical exceptions.

The seccomp source criterion intentionally changes from policy v1 to v2. The
current suite checks the canonical bytecode using a portable BPF interpreter,
then observes real EPERM for x32-tagged numbers and the legacy 512..547 range
through both direct-prctl and Bubblewrap/memfd delivery on Linux x86_64. Existing
native-call, environment, executor and crash-recovery tests remain required.
The legacy ABI behavior is described in [Linux seccomp(2)](https://man7.org/linux/man-pages/man2/seccomp.2.html).

Run `make accept-linux` from the repository root on supported Linux x86_64. The
root wrapper creates an isolated copy, runs this verifier with skipped tests
forbidden, and requires one fresh matching certificate/journal entry. It also
copies the active root workflow, Makefile and wrapper for the CI wiring check.
Historical verifier source and evidence remain unchanged; v57 is not rerun with
its obsolete policy-v1 assertion.

No initial `LAST_RUN.json` or `verifier/runs/v58.jsonl` is checked in. Those files
must be produced by an actual run. Under the root wrapper, records are retained
in the unique `artifacts/linux-acceptance/<run-id>/` directory along with console
output, `new-runs.jsonl` and `summary.json`. Absence of source v58 records is
included in the wrapper's source-history integrity check.

Mac development runs the portable suite with `make check`. It does not certify
Linux seccomp execution. The v2 policy still supplies a dangerous-syscall denylist,
not a complete syscall allowlist or protection against a hostile kernel. Existing
completed v1 results remain historical evidence. Recovery of an unfinished stale
policy execution is blocked, verified process identities are stopped, and the
original evidence and budget reservation remain available for reconciliation.
Upgrading the code does not retroactively install v2 in a running process.
