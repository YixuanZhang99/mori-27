# GEPA GSM8K pilot

This is an adapted single-component GEPA recipe, not a paper-score reproduction.
Its acceptance specification is [C01](../../../docs/specs/classic/GEPA.md).

- Reference: [gepa-ai/gepa, 3d34469165f0d604df3b48f1d5c776e9080f3da0](https://github.com/gepa-ai/gepa/tree/3d34469165f0d604df3b48f1d5c776e9080f3da0).
- Strict child-over-parent improvement follows `strategies/acceptance.py`.
- Epoch shuffling follows `strategies/batch_sampler.py`; this pilot requires equal full batches and uses its own seeded random stream. No upstream code is vendored.
- Validation winner coverage reuses MORI's `InstanceFrontier`, including deterministic insertion-order tie handling. `PopulationFrontier` retains valid candidates independently of incumbent promotion; its capacity covers every possible proposal.
- Source data: [openai/grade-school-math, 3101c7d5072418e28b9008a6636bde82a006892c](https://github.com/openai/grade-school-math/tree/3101c7d5072418e28b9008a6636bde82a006892c), MIT license. Dataset files stay outside source control; their frozen manifest records hashes and original-row IDs.

The standard pilot has train 64, validation 64 and final test 128, batch 8,
seeds 0/1/2, at most 10 reflective proposals per seed. The initial prompt is
constructed by M7. Merge and perfect-parent skipping are disabled. Only strict
training improvement triggers full validation. Final test follows immutable
selection and never updates search state or memory.

Live mode includes one independent initial random-search control, evaluated on
validation. This is a one-sample IID-RS sanity check, **not a budget-matched
comparison or a final-test baseline**. A full benchmark comparison remains a
separate delivery requirement.

Prepare public data from the pinned repository's `grade_school_math/data/train.jsonl`
and `test.jsonl` (place both in one source directory):

```sh
uv run --project m0 --locked python -m zoo.gepa_gsm8k.prepare_data \
  --source-dir /path/to/official-jsonl --output /path/to/new-pilot-data
```

The command verifies both upstream hashes before writing any output and assigns
IDs before taking the train/validation/test slices.

Run from the repository root with the locked environment:

```sh
uv run --project m0 --locked python -m zoo.gepa_gsm8k.runner \
  --mode fixture --max-proposals 2 --output /tmp/gepa-fixture

# OPENAI_API_KEY is read from the already configured local environment.
# Supply the existing shared campaign ledger, never create a new budget here.
uv run --project m0 --locked python -m zoo.gepa_gsm8k.runner \
  --mode live --manifest /path/to/pilot/manifest.json \
  --spending-ledger /path/to/existing-campaign.db \
  --seed 0 --max-proposals 10 --max-completion-tokens 16384 --output /path/to/new-gepa-run
```

`method-report.json`, `profile.json`, the existing execution journal and its
checkpoint contain results and provenance. Fixture results are synthetic. Live
model aliases and unverified immutable versions remain explicitly identified
by the existing provider audit. Every solver, reflection and control request
uses the same cumulative CNY authority. Replay consumes recorded outcomes.
`--resume` restores the same run; extending a search after final selection is
frozen is rejected.

Evaluation contracts declare aggregate solver usage as `total_only`; detailed
input/output usage remains in the governed provider's currency receipts. Token
reservations use that provider's declared call bound. Same-plan recovery can
settle a durably saved response without repeating the request; a new run cannot
start while the shared campaign has unresolved calls.

Observed live runs and failures are preserved in the [GSM8K report](../../../research/experiments/2026-11-05-gepa-gsm8k/README.md). A 4,096-token allowance produced a reasoning-only truncated response in the first smoke; subsequent attempts used an explicitly frozen 16,384-token allowance. A failed response stops that evaluation and does not receive a full-set accuracy. A single-attempt M7 constructor can also reject malformed model output; failed controls remain visible. Increasing the allowance is not a guarantee of completion.

Fixture mode can run from an installed package or an isolated source copy without Git, recording null source fields. Live mode continues to require a clean Git checkout before any provider dispatch.
