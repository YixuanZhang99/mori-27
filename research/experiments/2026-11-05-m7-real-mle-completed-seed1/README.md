# Real M7 MLE task-subset pilot: seed 1

On 2026-11-05 Asia/Shanghai, source commit `a6b58267b7447fbb1c40e47875d0d2ca5534e37d`
completed all six planned runs and received six valid official grades. This is
a **three-task, one-seed diagnostic subset**, not the complete MLE-Bench Lite
benchmark or evidence of statistical significance. The official grader and
leaderboard snapshot are pinned to [MLE-bench revision
`507f92e`](https://github.com/openai/mle-bench/tree/507f92e1138bb6e40dac5c6ee7a6758e6424bf97).

| Task | Metric (lower is better) | Baseline | Full | Full − baseline |
| --- | --- | ---: | ---: | ---: |
| spooky-author-identification | Multiclass log loss | 0.40538 | 0.42521 | +0.01983 |
| leaf-classification | Multiclass log loss | 1.06263 | 0.26220 | −0.80043 |
| nomad2018-predict-transparent-conductors | Mean of two RMSLE values | 0.06501 | 0.06403 | −0.00098 |

All six submissions were valid. In the pinned official leaderboard snapshot,
the grader marked spooky baseline and both NOMAD submissions above the median;
both NOMAD submissions met at least one medal threshold. These are snapshot
comparisons, not awards from a live competition. The full arm scored better on
two tasks and worse on one; one local seed cannot establish a general effect.

Baseline used greedy selection with draft/reflective operators; full used a
population policy with draft/crossover. Both used M7 configured construction,
Git artifacts, sandboxed execution and resident governance. Because the search
methods differ, this comparison **does not isolate governance benefits**.

The requested and returned provider identifier was `deepseek-flash`; it is a
mutable alias and no immutable model snapshot was verified. Local split seed 1
was used but was not sent to the model provider. Each run allowed three search
iterations, a 3,000,000-token ceiling, a 600-second wall-clock limit and a
120-second candidate limit. All six submissions were frozen before the official
grader was invoked. Total recorded usage was **396,545 tokens**, and the
currency ledger's settled upper bound for this pilot was **2.743624 yuan**.
The original shared campaign's cumulative upper bound, including previous
failed attempts, was **6.771340 yuan** of the authorized 200 yuan; no calls or
reservations remained unresolved. The bound is not a reconciled supplier
invoice.

`results.json` contains the sanitized per-run scores, usage, wall-clock times,
submission hashes and official-report hashes. The private run directories,
task data and provider receipts remain local. After completion, an independent
read-only audit reconstructed all six public-data bundles, checked the
original currency receipts, physical settlement, selected predictions,
submission hashes, recorded replay and official report hashes; it made **zero
external model requests** and left the shared ledger unchanged. The original
failed attempts remain documented in [attempt 1](../2026-11-05-m7-real-mle-attempt-1/)
and [attempt 2](../2026-11-05-m7-real-mle-attempt-2/).

Reproduction requires the pinned official MLE-bench checkout and prepared
competition data, access to the same provider model alias, an explicitly
authorized shared CNY ledger and the frozen M7 profile. The repository's
`zoo.mle_bench_lite.pilot` supports a no-paid-call `--preflight-only` check;
running the full six-slot command makes paid requests and its results can vary.
The original data and credentials are intentionally not included here.
