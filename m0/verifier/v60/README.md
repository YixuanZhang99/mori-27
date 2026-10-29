# v60 acceptance: S1 module composition

This version certifies the first implementation stage of the unified abstraction
alignment plan: module registration, default adapters, validated composition,
and configured execution through the Framework runtime. The explicit group runs
`test_composition_registry.py`, `test_composition_defaults.py`, and
`test_composed_runtime.py`. Every v59 command group and timeout is preserved,
including the complete unfiltered pytest suite, static axioms, real Linux
process/sandbox/seccomp checks, and recovery regressions.

Stage S1 is not completion of the whole abstraction. S2 unified evaluation
contracts, S3 memory and knowledge feedback, S4 three-layer admission, and S5
hierarchical budget control retain separate implementation and acceptance
requirements. Their completion flags in this certificate remain false. Refer to
[`docs/ABSTRACTION_ALIGNMENT.md`](../../../docs/ABSTRACTION_ALIGNMENT.md) for the
frozen baseline, stable requirement IDs, stage boundaries, and acceptance rules.

Run `make accept-linux` from the repository root on supported Linux x86_64.
Mac development runs `make check`. The wrapper creates a disposable copy,
requires a fresh matching passing certificate and exactly one new journal entry,
rejects skipped tests, and checks that source history remains unchanged. No
initial v60 `LAST_RUN.json` or `runs/v60.jsonl` is committed. Actual execution
produces evidence under a unique `artifacts/linux-acceptance/<run-id>/` directory.

## Archived v59 evidence provenance

The newly archived `verifier/v59/LAST_RUN.json` and `verifier/runs/v59.jsonl`
are byte-for-byte copies from successful
[GitHub Actions run 40879734092](https://github.com/YixuanZhang99/mori-27/actions/runs/40879734092),
head `b45654fe22a2db87f64e12f0142ba39bbd603216`. The artifact is named
`linux-acceptance-b45654fe22a2db87f64e12f0142ba39bbd603216`, and the acceptance
directory is `linux-acceptance/20261029T131221.959462Z-d2kswojc/`.

Before archiving, the Actions run was checked for the exact head and successful
completion; the local baseline also matched that head. The summary confirmed
exit code zero, passing fresh evidence, and unchanged source history. All 28
certificate checks passed. The single new journal entry matched the certificate,
and the full journal matched `new-runs.jsonl`. The destination files were absent
and created exclusively, without overwriting any history.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v59/LAST_RUN.json` | `7796343856f3706e8f50d8320f89856b98711fd57999d4cb6ffa5e74a94f679c` |
| `verifier/runs/v59.jsonl` | `24e18504243a1e3c2c7f7fbadd6c45f17a38de22b92fe2422203e6044197a275` |

The v1–v59 verifier sources and earlier evidence remain unchanged. Historical
verification requires passing journals through v59, retaining the documented
rejected v14 and superseded recursive v43 exceptions. v59 is not rerun against
new root wiring, and its certificate only certifies its original commit.

This stage adds no real external provider campaign, external benchmark scores,
host parity, high-cost evaluation performance, machine-power-loss, complete
syscall allowlist, non-x86_64 seccomp, or complete resource-isolation claim.
