# FunSearch OR3 pilot

This is an adapted FunSearch program-search recipe. Its specification is
[C02](../../../docs/specs/classic/FUNSEARCH.md). It is not a reproduction of the
original paper's scale or scores.

Reference: [google-deepmind/funsearch at cc53f274237d7ab05c19df939edbc1f9616a7c19](https://github.com/google-deepmind/funsearch/tree/cc53f274237d7ab05c19df939edbc1f9616a7c19).
The reference notebook hash and sorted-ID 10/10 OR3 split hashes are fixed in C02.
The development cases have already been inspected; they are not unseen data.

The public Framework owns construction, evaluation, budget, final selection and
replay. Two FunSearch islands use signature clusters, length preference and
versioned examples. Valid programs remain available independently of global
incumbent promotion. Island resets replace active members while retaining history.
Ordered draws and complete island state are reconstructed from original events
when restoring, rather than trusting checkpoint RNG state.

Only `priority(item, bins)` may change. The worker receives the current item and
remaining capacities of eligible bins; `np` is available. A trusted parent scores
negative used-bin count. Generated programs run in the existing Linux x86_64
Bubblewrap/seccomp sandbox, with no dataset files, network or process creation.
Both development and final evaluation use this boundary.

## Run

Execution requires Linux x86_64, Bubblewrap and the repository's locked environment.
The default is a small synthetic offline fixture, using the real sandbox:

```sh
uv run --project m0 --locked python -m zoo.funsearch_binpacking.runner \
  --mode fixture --max-proposals 2 --output /tmp/funsearch-fixture
```

Prepare a new dataset directory from the hash-pinned upstream notebook:

```sh
uv run --project m0 --locked python \
  research/experiments/2026-11-05-funsearch-population/prepare_or3.py \
  /path/to/bin_packing.ipynb /path/to/new-or3-data
```

Live mode requires a clean Git checkout, the exact official split and the
**existing shared campaign ledger**. It reads `OPENAI_API_KEY`; do not place the
key in a command or report. Do not create another budget for this method.

```sh
uv run --project m0 --locked python -m zoo.funsearch_binpacking.runner \
  --mode live --manifest /path/to/new-or3-data/manifest.json \
  --spending-ledger /path/to/existing-campaign.db --seed 0 \
  --max-proposals 10 --max-completion-tokens 16384 --reasoning-effort low --timeout 30 \
  --output /path/to/new-funsearch-run
```

The declared pilot uses seeds 0/1/2, at most ten proposals after the initial
program, and 30 seconds per complete partition evaluation. Generation calls and
one independent initial control share the original cumulative CNY authority.
Program evaluation makes no model calls. The control uses development only and
is not a budget-matched comparison.

The fixed best-fit reference is evaluated separately before search, also checking
sandbox availability before paid requests. Neither reference score enters model
inputs. Its official dev/held-out means are 213.9/210.1 bins; these are reference
values, not model discoveries. The main winner is frozen using dev mean before
its held-out evaluation. Held-out scores never update search or choose a winner.

## Recovery and evidence

`run-manifest.json` freezes source, data, profile, provider and the reference
report hash before any model request. `method-report.json` includes attempted,
successful and failed program counts, original result, baseline and replay status.
`profile.json` and the existing journal preserve method decisions and usage.
All failures remain visible; failed or partial evaluations have no complete score.
An execution or replay error writes an incomplete report and exits nonzero.
It includes the error type, completed evidence, actual final state, unresolved
provider bindings and the campaign snapshot when available. Unknown usage is
never retried or reported as free. Search statistics distinguish completed
failures from incomplete attempts; failure rate counts both as unsuccessful.

Use the same original source commit and exact arguments with `--resume`.
`--resume --final-only` requires an existing frozen winner record, performs only
unfinished terminal evaluation, and returns the recorded result if already done.
It refuses an unfrozen search. Completed replay/resume makes no model or sandbox
requests. A change in source, data or configuration is rejected.

Adaptations: two islands; small proposal budget; independent Python RNG; resets
after every five successful registrations including initialization instead of a
wall-clock schedule; M7 generates the initial program; editing is restricted to
one function. Cluster sampling uses the final sorted case's score, while global
selection uses development mean. These objectives are reported separately.

The current recipe is `funsearch-or3-v3`. Version 1 exposed conflicting output
instructions in its first real seed: all 11 constructions failed before scoring.
Its other two planned seeds were not started after diagnosis. The full v1 record
and cost remain in the experiment archive. Version 2 explicitly requires the M7
JSON envelope and scopes the one-function restriction to its artifact field.
The strict parser, data, search budget and scorer are unchanged.

The v2 high-effort attempt produced a valid initial program but all ten mutations
used the complete 16384 output allowance on reasoning and were truncated. Its
scores and costs remain archived separately. V3 selects `--reasoning-effort low`
for both main and control. The governed provider's default remains high for other
callers; effort is included in the manifest, actual wire request, pre-dispatch
validation and independent currency replay. The original token/currency bounds
are unchanged. The CLI accepts low/high/max and rejects changing it on resume.

V3 seeds 0/1/2 completed with 10/11, 11/11 and 10/11 valid candidates. All three
frozen held-out results are 210.1 bins, equal to best-fit; seed 0 improved only
on development (213.8 versus 213.9). All recorded replays and independent result
recalculations passed. See the [full report](../../../research/experiments/2026-11-05-funsearch-or3/README.md)
for failures, original records and the total batch upper cost of CNY 1.098926.
This demonstrates a runnable adapted recipe, not a held-out gain or paper reproduction.
