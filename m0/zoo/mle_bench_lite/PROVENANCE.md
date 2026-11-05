# MLE-Bench Lite provenance

- Upstream: https://github.com/openai/mle-bench
- Locked revision: `507f92e1138bb6e40dac5c6ee7a6758e6424bf97` (upstream `main` observed 2026-10-26)
- Split: `experiments/splits/low.txt`, 22 competitions
- Split SHA-256: `590270f007fa96b4060f59f3861500159c73ca50f7f30ff6bd38303c236c799b`
- Protocol: upstream `README.md#benchmarking`; at least 3 seeds, Any Medal mean ± SEM, with valid-submission reporting
- Code license: MIT. Kaggle datasets and competition rules retain their own terms and require separate acceptance.
- `assets/snapshot_manifest.json` locks the split plus each Lite task's config, grader, checksums, leaderboard and description hashes (111 files total).
- Upstream announced on 2026-04-24 that new public leaderboard submissions are paused. Local official grading remains the comparison path; no new leaderboard standing is claimed.

No prepared Kaggle data, private answers, external grading report, benchmark score, or hosted run is bundled here. Obtain the official snapshot at the revision above, accept the relevant competition rules, and run `mlebench prepare --lite` before execution.


## C03 AIDE adapted recipe

Algorithm reference: WecoAI/aideml, revision `ad73d227af481bea3de06f884f41b2993dd6453a` (`aide/agent.py`, `aide/journal.py`, `aide/utils/config.yaml`). The implementation reuses MORI's nine modules and source-bound M7 construction; no upstream optimizer loop is embedded. See `docs/specs/classic/AIDE.md` for exact ordering and deviations. Pilot deviations include three roots, ten total main nodes, debug depth two, independent Python RNG, one fixed local validation split, trusted CSV loss instead of model-reviewed metrics, and one isolated initial control. Provider sampling is not reproducible. The existing pinned MLE-Bench source/data adapter supplies post-selection official grading; labels and grader reports do not enter search. The separately declared nine-cell real matrix and official scores are archived in [the AIDE report](../../../research/experiments/2026-11-05-aide-mle/README.md); this does not establish full-suite or paper-budget reproduction.


## C04 Arbor adapted recipe

Algorithm reference: [RUC-NLPIR/Arbor](https://github.com/RUC-NLPIR/Arbor/tree/a633f56f2601387402194481e846e3375e822afa), revision `a633f56f2601387402194481e846e3375e822afa`. Source decisions and file-level references are recorded in [the source notes](../../../docs/superpowers/specs/2026-11-05-arbor-source-notes.md) and [C04 spec](../../../docs/specs/classic/ARBOR.md). MORI implements Observe → Ideate → Select → Dispatch → Backpropagate → Decide through its existing nine modules; it does not embed a second upstream optimizer loop.

The real recipe is `arbor-mle-v4`, fidelity `adapted`, with runtime source `aeeb6fd471d9b1532d8dcd495e6479983b367efc`. Differences include bounded tree/cycle limits, incremental source-bound summaries and a run-local global prior, fixed dev/admission/final splits, strict independent admission with a three-call cap, two attempts under one frozen hypothesis, CSV-only tasks, and no knowledge/cross-run imports. One fresh initial control is included in the original cumulative currency ledger, but is not a budget-matched search baseline. The mutable `deepseek-flash` alias is not an immutable verified model snapshot; remote sampling seeds are not applied.

[The complete nine-cell report](../../../research/experiments/2026-11-05-arbor-mle/README.md) preserves all failures, official scores, generated programs, six-stage records, source-bound insights, admission decisions and original currency receipts. It reaches the small real-pilot milestone, not full MLE-Bench or paper-budget replication. Three earlier failed matrices are retained separately. The official grader/data revision remains the pinned MLE-Bench revision above, and official scoring occurs only after all searches and final selections are frozen.
