# v59 acceptance

This version covers dataset content and evaluation-context binding, shared
process identity writing and recovery, configuration validation before side
effects, complete decision-receipt identity, and isolated replay. Four explicit
regression groups supplement every v58 behavioral group, the complete unfiltered
pytest suite, static axioms, and the historical passing-journal chain through
v58. Rejected v14 and the superseded recursive v43 harness remain the documented
historical exceptions.

The process group includes actual Linux execution of a child whose executable
name contains spaces and a closing parenthesis, durable target identity checks,
owner-loss recovery, and fast child completion. Portable parser, error-handling,
and identity parity tests run on Mac; these cannot certify Linux process control.
The v58 seccomp v2, usage, budget, admission, recovery, and integration groups
remain required without reducing their assertions.

Run `make accept-linux` from the repository root on supported Linux x86_64. The
root wrapper creates an isolated copy, forbids skipped tests, and requires one
fresh matching certificate/journal entry. It copies the active root workflow,
Makefile and wrapper for the CI wiring check. Mac development uses `make check`.

No initial `verifier/v59/LAST_RUN.json` or `verifier/runs/v59.jsonl` is checked in.
Only an actual verifier run can produce these files. The wrapper preserves new
records, console output, `new-runs.jsonl` and `summary.json` under a unique
`artifacts/linux-acceptance/<run-id>/` directory and checks that source history,
including the absence of initial v59 records, remains unchanged.

## Archived v58 evidence provenance

The newly archived `verifier/v58/LAST_RUN.json` and `verifier/runs/v58.jsonl` are
byte-for-byte copies of actual Linux acceptance artifacts from
[GitHub Actions run 40870494602](https://github.com/YixuanZhang99/mori-27/actions/runs/40870494602),
head `594e46dafc4ffff8700f36f2b35d301aa603148b`. The artifact name is
`linux-acceptance-594e46dafc4ffff8700f36f2b35d301aa603148b`, and its acceptance
directory is `linux-acceptance/20261029T120617.949029Z-fuewpt7k/`.

Before archiving, the summary was checked for passing v58 execution, successful
exit, and unchanged source history; the certificate and single new journal entry
were checked for identical passing checks. The full journal and `new-runs.jsonl`
were identical. The destination files did not previously exist and were created
without overwriting historical evidence. Their SHA-256 digests are:

| File | SHA-256 |
| --- | --- |
| `verifier/v58/LAST_RUN.json` | `e11b840bd3ddae8af47e54c90cf14e9673d189800189100c03930edfc6a57794` |
| `verifier/runs/v58.jsonl` | `8a19b059ca9a8ae5d86b943eaf8bf9ebd3529ce05b8268558d725d74d00ec552` |

Existing verifier sources and historical evidence are unchanged. v58 is not
rerun against the new root wiring. These archived records certify their original
commit; v59 requires fresh execution for the current behavior. No external
provider or benchmark campaign, complete syscall allowlist, resource quota, or
hostile-kernel protection is claimed.
