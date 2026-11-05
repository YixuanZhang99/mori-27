# Second real M7 MLE pilot attempt

This is an incomplete, failed pilot, not an official benchmark score. It ran on
2026-11-05 Asia/Shanghai from commit `fc50a81daf9287b631baaee216149eaf7da38ee6`
using the mutable `deepseek-flash` API alias. Both local v74 acceptance and the
matching GitHub Actions run completed successfully before dispatch. The frozen
plan covered three tasks, baseline/full arms, and one seed (six slots).

The first slot, `spooky-author-identification` baseline, produced an admitted
candidate but stopped before materializing an official submission. Its five
model calls included one response terminated at the output-length limit. The
framework recorded that call as a billed failure with no candidate artifact.
An independent receipt audit rejected all non-null response integrity reasons,
including this known, settled failure, so the agent exited unsuccessfully and
the remaining five slots were blocked before execution. No official grading
occurred. The failed attempt and private evidence remain intact.

The cumulative campaign settled upper bound increased from 3.583228 to
4.027716 yuan, a 0.444488 yuan increment under the original 200 yuan cap.
There were no outstanding reservations or unresolved calls afterward. These
amounts are ledger upper bounds, not independently reconciled invoices.

After diagnosing the failure, the revised independent audit was run against the
original receipts and verified all five calls and the 0.444488 yuan bound. A
synthetic six-slot fixture reproduces the truncated-response case. This later
audit does not retroactively turn the failed run into a completed pilot or a
benchmark result; a new source-bound run and official grading are still needed.
