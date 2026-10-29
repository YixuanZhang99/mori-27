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
