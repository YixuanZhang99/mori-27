# Superseded v1 format-conflict attempt

Source: `f151dba809e93206945dcedde738a14693cf7e4f`; recipe `funsearch-or3-v1`. Seed 0 completed 11 search attempts: zero valid programs, 11 construction failures, no held-out score. Seven search calls returned invalid outer JSON; four ended at the output cap (`finish_reason=length`, `incomplete_output`). The independent initial control also returned invalid outer JSON. The saved provider outcome metadata is matched by response digest to the currency receipts. Recorded replay passed; replay confirms the recorded failure history, not benchmark success.

The adapter instructed the model to return one Python function, while M7 required an outer JSON object with `artifact` and `hypothesis`. Model responses followed the function-only wording. This conflict is corrected in v2 by scoping the function restriction to the artifact field and explicitly instructing the JSON envelope; the strict parser remains unchanged.

After five identical search-format failures, only the batch scheduler was suspended to prevent additional seeds. Seed 0 continued through its original bound, settled all 12 calls, and wrote its final report. The stopped scheduler was then terminated. Predeclared v1 seeds 1/2 were **not attempted** because of the diagnosed implementation defect. They are neither successful runs nor silently excluded completed runs. No three-seed v1 statistics are claimed.

This batch's frozen-price upper cost is 971870 micro-CNY (¥0.971870), included in the unchanged original ¥200 campaign. Campaign cumulative upper cost afterward: ¥18.695960. No pending usage or reservations remained. These are ledger upper prices, not invoice verification.

Recalculate from the repository root:

```sh
python research/experiments/2026-11-05-funsearch-or3/recalculate.py \
  research/experiments/2026-11-05-funsearch-or3/format-conflict-v1
```

All original program responses remain in `seed-0/x1.jsonl.gz`; none became a valid selected program. This record remains separate from the corrected v2 pilot and its future scores.
