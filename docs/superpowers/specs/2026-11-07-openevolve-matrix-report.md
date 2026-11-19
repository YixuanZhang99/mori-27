# OpenEvolve six-cell evidence report

This refines O5 of `2026-11-05-openevolve-design.md`. It does not change the
frozen pilot, authorize another cell, or substitute a partial result for the
requested three paired seeds.

The report must preserve all six declared cells and three pair slots at one
independently supplied campaign head and plan reference. It must distinguish
the head-relative absence of a claim from a claimed but unresolved outcome,
a verified contained failure, a verified timeout, and an independently audited
final geometry snapshot. Cleanup of a lost supervisor is unresolved. A missing
outcome or run must not become a zero score or zero cost.

Each verified terminal must bind the original plan, cell clock and ledger claim
to the unique supervisor start, containment verification, finish record and
matching wrapper result. A timeout requires matching timeout evidence; elapsed
wall time, a nonzero exit, missing result, a lost process or cleanup alone are
not timeout evidence. Conflicting evidence is rejected, not silently reduced.

Per-run accounting comes from recorded currency evidence pinned to the same
campaign head. Report settled upper bound, pending, outstanding, reserved and
breaches separately; unknown values remain null and no invoice is implied.
Use the existing independent pair geometry and replay audits for successful
snapshots. A result may be called an audited final snapshot only within those
audits' actual scope; it does not by itself certify the complete reference
database transition, paper-budget reproduction or a benchmark performance
claim. Pair differences are present only when both comparable snapshots are
independently verified. Never accept a caller-supplied score or status as
proof, omit a failed cell, or average only successful cells.

The implementation should reuse `snapshot_matrix`, `RecordedCurrencyView`,
`RecordedCellClock` and the existing supervised pair audits. Generalize the
read-only reconstruction currently limited to seed 0; keep recording the
first-pair ledger event separate from report generation. Introduce a read-only
contained-terminal verifier for failure and timeout rather than weakening the
existing successful-result verifier. Preserve the existing later-seed gate:
neither this report nor a partial first-pair audit authorizes new paid work.

Acceptance requires tests for all six fixed cells and all three pair slots;
valid final snapshots and their pair differences; genuine contained failures
and timeouts; missing, lost, interrupted and cleanup-only evidence; pending
currency; and no-claim cells. Tampered results, scores, geometry, identities,
seeds, runs, source evidence, mismatched result and finish records, distinct
campaigns and plans, stale or same-sequence/different-hash heads must fail
closed. Verify no report operation invokes a model, runs a candidate, changes
the ledger, or asserts full-matrix performance from incomplete evidence.
