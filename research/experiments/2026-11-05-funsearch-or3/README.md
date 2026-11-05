# FunSearch OR3 pilot evidence

Status: v1 exposed an output-format conflict in real seed 0; its complete [failure record](format-conflict-v1/README.md) is retained. V2 fixed the format but its ten mutation attempts all exhausted the high-effort output cap; its [complete record](high-effort-v2/README.md) is also retained. V3 low-effort three-seed validation is pending. This directory does not claim a benchmark gain.

Frozen protocol: [C02 specification](../../../docs/specs/classic/FUNSEARCH.md). Seeds 0/1/2, two islands, initial construction plus at most ten proposals, output cap 16384, explicit low reasoning effort for v3, 30-second partition timeout, and the original cumulative CNY campaign. The fixed best-fit reference is separate from model search. The initial independent control is a sanity check, not a budget-matched comparator.

Once the predeclared attempts finish, export all of them, including failures:

```bash
python research/experiments/2026-11-05-funsearch-or3/export_runs.py \
  --runs /absolute/seed-0 /absolute/seed-1 /absolute/seed-2 \
  --ledger /absolute/original-campaign.db --output /absolute/new-export-directory
python research/experiments/2026-11-05-funsearch-or3/recalculate.py /absolute/new-export-directory
```

Export reads the existing ledger in SQLite read-only mode. Neither command loads keys, calls a model, nor executes generated programs. Raw journals, frozen manifests, baseline bytes, original method reports, currency receipts, all generated programs, selected programs, and per-case bin counts are retained. Independent recalculation checks coverage, split bindings, score means, the development winner, and the frozen campaign's upper-price arithmetic. It checks consistency of the exported records; runtime replay and source provenance remain separately reported evidence.

Pending usage remains unknown cost with its reservation retained. Incomplete search attempts enter the failure denominator. Failed or skipped final evaluations have no score. No cross-seed mean is emitted by these scripts. Published real scores and source revisions will be added after the pilot; fixture scores are not benchmark results.
