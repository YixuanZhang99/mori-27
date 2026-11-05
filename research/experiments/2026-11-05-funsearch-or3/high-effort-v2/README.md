# Superseded high-effort v2 pilot

Source `fd02b5c68dece76be5f4bae09269e3ab41815082`, recipe `funsearch-or3-v2`, seed 0, reasoning_effort=high, output cap 16384. The JSON envelope fix worked: initial main and independent control returned valid programs. Main dev mean 213.9 bins; frozen final held-out mean 210.1 bins. Both match fixed best-fit; no improvement was demonstrated.

All ten mutation attempts ended with finish_reason=length / incomplete_output. Each consumed all 16384 completion tokens as reasoning tokens without producing executable code. Thus successful search candidates = 1/11 and failure rate = 10/11. All 12 calls settled; recorded replay passed. Cost upper bound:1,373,084 micro-CNY (¥1.373084). Original campaign cumulative afterward: ¥20.069044, remaining ¥179.930956, no unresolved reservations.

After six identical truncations, only the batch scheduler was stopped. Seed0 completed its original bound and final evaluation normally. Predeclared v2 seeds 1/2 were not attempted; no three-seed statistics are claimed. This artifact and its costs remain separate from the subsequent low-effort v3 batch.

The provider previously hardcoded high even though the [official thinking guide](https://api-docs.deepseek.com/guides/thinking_mode/) supports `low`/`high`/`max`. V3 exposes a frozen effort parameter and selects low for this small-code pilot. The model alias, output cap, dataset, scoring, node limit and original cumulative campaign remain unchanged. The documented [API](https://api-docs.deepseek.com/api/create-chat-completion/) defaults thinking output allowance to 64K; this 16K/high combination was an experimental constraint, not a model-capacity claim. This observation does not establish that low is more accurate; it motivates checking bounded code generation.

Recalculate from the repository root:

```sh
python research/experiments/2026-11-05-funsearch-or3/recalculate.py \
  research/experiments/2026-11-05-funsearch-or3/high-effort-v2
```

Provider outcomes are matched by response digest to original currency receipts. Program files are evidence for inspection, not commands that recalculation executes. These costs use frozen upper prices, not verified invoices.
