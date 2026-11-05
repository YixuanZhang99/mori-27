# v70: remaining physical reservations and cooperative journal snapshots

This version preserves every v69 command group and exact timeout. It adds:

- `remaining_physical_reservation_and_mle_usage_end_to_end` (480 seconds): hierarchical budget, composed budget/recovery and MLE currency integration tests, including the real-pilot 13,394-token usage shape served by a local fixture.
- `cooperating_process_journal_snapshot_consistency` (120 seconds): paused interprocess appends, concurrent read/write serialization, iteration without retained locks, persistent corruption refusal and the original partial-start SIGKILL recovery tests.

A successful run has 41 checks: 32 command groups and 9 historical/source checks. Every pytest command keeps strict markers and fail-on-skip enforcement. The new `remaining_reservation_evidence` and `journal_snapshot_evidence` fields require their respective group and the entire run to pass.

The monetary policy remains separate from physical reservation allocation. Numeric operator quotes are admission floors; remaining allocation is opt-in and reconstructed from the event-prefix state. True overruns and unknown usage still stop new operations. Fractional quote conversion does not exceed available headroom. The journal fix coordinates cooperating Mac/Linux processes, uses memory proportional to the captured journal prefix, and releases locks before caller iteration. It does not claim Windows execution, malicious-writer protection, fsync durability, atomic recovery after a partial-write crash, or a subscription protocol.

No paid service or official benchmark campaign is executed by this verifier. The [first real pilot report](../../../research/experiments/2026-11-04-deepseek-pilot-attempt-1/README.md) records two valid official submissions and four failures separately; it neither certifies this repair nor establishes benchmark superiority. No initial v70 certificate or journal is supplied. `make accept-linux` creates fresh evidence in a disposable copy; main still requires same-SHA hosted CI.

## Archived v69 provenance

The v69 certificate and journal are exact local Linux acceptance output from clean commit `5fa85d3ab7c4f643550ecaa2223a65231d7f7a86`, run `20261104T072440.444943Z-8arao2_1`. The before/after source commit and clean status matched; historical source evidence stayed unchanged. The wrapper completed in 874.524 seconds, all 39 checks passed, and its single new journal entry matched the certificate. The test suite reported 1,794 passing tests. This is **local** evidence; same-SHA remote CI was unavailable and is not implied.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v69/LAST_RUN.json` | `1b4ab41c4cdb631bb85b3884d7b99bea4f7085ae9a3a3048239f9665dc7d0e1e` |
| `verifier/runs/v69.jsonl` | `19f70b2b97fe3e83ac9798aeef636ca97d82eb4edf8fb989a7a140e0dcfc10d6` |

[v69-provenance.json](v69-provenance.json) also records the source archive and original wrapper artifact hashes. Archive files were created exclusively, after rechecking the original outputs. Historical verifier source was not edited or rerun to manufacture success. Transition tests enforce the exact archive hashes, matching certificate/journal, all prior command groups and the new unfiltered groups.
