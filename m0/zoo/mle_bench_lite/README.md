# MLE-Bench Lite TaskAdapter

## S9 configured agent and three-task pilot

For the latest anchor, negative-feedback and population implementation, use
`python -m zoo.mle_bench_lite.pilot` with the shared `composed_agent`
baseline/full variants. The [S9 guide](../../../docs/MLE_COMPOSED_V68.md)
documents the CLI, isolated public-training splits, physical budgets, final
official scoring, and the manual GitHub CPU workflow.

The configured pilot currently supports `spooky-author-identification`,
`leaf-classification` and `nomad2018-predict-transparent-conductors` using
their CSV inputs. It freezes all submissions before official grading and
labels reports as subset pilots. Its local tests and synthetic official-runtime
smoke are not external model measurements or full MLE-Bench scores.

The original 22-task host/governed campaign below retains its strict complete
matrix requirements. Its bundled `governed_agent` uses the legacy M0 path;
that protocol is separate from S9 and is not silently upgraded.

## C04 Arbor adapted recipe

The public `Framework` entry supports a hypothesis tree, construction from the
admitted trunk, source-bound insight propagation, separate admission, and frozen
final evaluation. See the [spec](../../../docs/specs/classic/ARBOR.md),
[algorithm provenance](PROVENANCE.md#c04-arbor-adapted-recipe), and
[nine-cell real results](../../../research/experiments/2026-11-05-arbor-mle/README.md).
The real pilot has 38/44 valid main candidates and nine valid official submissions;
it is not a full MLE-Bench or paper-budget reproduction.

Run from the repository root with the locked dependencies and Linux x86_64
Bubblewrap/seccomp prerequisites. The default uses generated synthetic CSVs and
makes no model calls:

```bash
PYTHONPATH=m0 uv run --project m0 --locked python -m zoo.mle_bench_lite.arbor_runner \
  --mode fixture --output /tmp/arbor-fixture --max-cycles 3
PYTHONPATH=m0 uv run --project m0 --locked python -m zoo.mle_bench_lite.arbor_runner \
  --mode fixture --output /tmp/arbor-fixture --max-cycles 3 --resume
```

For an explicitly paid run, use the CPU pilot environment described in the
[S9 guide](../../../docs/MLE_COMPOSED_V68.md), accepted/prepared competition data,
the existing spending ledger, and the original private anonymization key.
`OPENAI_API_KEY` must already be available to the process; do not paste its value
into commands, reports, or tracked files. This recipe uses `deepseek-flash` with
low reasoning effort and output limit 16384; it does not verify an immutable
provider snapshot. The existing cumulative campaign cap applies, including the
independent initial control; do not create a second campaign for this method.

```bash
PYTHONPATH=m0 python -m zoo.mle_bench_lite.arbor_runner \
  --mode live --task spooky-author-identification \
  --public-root /absolute/path/to/spooky-author-identification/prepared/public \
  --anonymization-key /absolute/path/to/original-private-key \
  --spending-ledger /absolute/path/to/existing-campaign.db \
  --output /absolute/path/to/new-arbor-run \
  --split-seed 7 --search-seed 0 --max-cycles 5 --solution-timeout 120
```

The pilot caps search at five cycles, depth two and three admission calls;
min_samples=4/patience=3 may stop it earlier. The packaged full profile defaults
to 20 cycles. `search_seed` labels repeats/control scheduling; it is not an
applied remote sampling seed. Live records include all failed candidates and one
independent initial control, which is not a budget-matched baseline.

A matrix must declare all tasks/seeds, clean source, dependency/data identities,
and the existing campaign before its first paid call. The command above is a
single explicit run, not the complete predeclared nine-cell protocol. Preserve
source, dependencies, data, options and the private key when using `--resume`;
never resume or replace an existing experiment merely to improve its score.

Only after **all declared searches have stopped**, grade each frozen valid
submission with the official snapshot and prepared identity frozen before search:

```bash
PYTHONPATH=m0 python -m zoo.mle_bench_lite.arbor_grading \
  --output /absolute/path/to/completed-arbor-run \
  --official-root /absolute/path/to/pinned-mle-bench \
  --data-root /absolute/path/to/prepared-data \
  --frozen-prepared-identity /absolute/path/to/official-prepared-identity.json \
  --anonymization-key /absolute/path/to/original-private-key
```

The grader rederives the frozen submission from original predictions and stores
a once-only claim and terminal report. It does not call a model or feed official
scores back to search. Published evidence can be recalculated without credentials:

```bash
python research/experiments/2026-11-05-arbor-mle/recalculate.py \
  research/experiments/2026-11-05-arbor-mle/pilot-v4
```

## Original complete-suite adapter

This adapter covers the official 22-task Low/Lite split at the revision in `PROVENANCE.md`.

```python
from core.tasks.adapter import Workspace
from zoo.mle_bench_lite import MLEBenchLiteAdapter

adapter = MLEBenchLiteAdapter(
    "aerial-cactus-identification",
    official_root="/path/to/mle-bench",
    data_root="/path/to/prepared/data",
)
adapter.setup(Workspace(workspace_path))
print(adapter.eval_contract())
```

Prerequisites:

1. Check out the locked official revision and install its `mlebench` package.
2. Accept the relevant Kaggle rules and prepare the dataset with `mlebench prepare --lite` (or one `-c <competition-id>` task for smoke testing).
3. Keep official grading and prepared private data outside the agent-visible workspace. Minimal protocol setup copies only `description.md`, `sample_submission.csv` and a provenance-only `task.json`; production campaign setup additionally copies prepared public train/test inputs under `data/`, never private answers, graders or leaderboards.
4. Execute all 22 tasks with at least 3 paired seeds for governed and host arms. Use the same backbone and declared physical budget. Record externally measured reports as `BenchmarkRunRecord(measured=True, evidence_refs=(...))` and compare with `compare_same_budget(..., expected_task_ids=set(adapter.task_ids()))`.

## Production paired campaign runner

After all prerequisites are ready, run a fresh evidence directory with real arm entrypoints:

```bash
python3 -m zoo.mle_bench_lite.runner \
  --official-root /path/to/mle-bench --data-root /path/to/prepared/data \
  --output-root /path/to/new/campaign --backbone SAME_MODEL \
  --time-limit 3600 --token-budget 60000 --seeds 1 2 3 --noise-floor MEASURED_FLOOR \
  --host-command 'python3 -m zoo.mle_bench_lite.host_agent --workspace {workspace} --task {task} --seed {seed} --model SAME_MODEL --iterations 10' \
  --governed-command 'python3 -m zoo.mle_bench_lite.governed_agent --workspace {workspace} --task {task} --seed {seed} --model SAME_MODEL --iterations 10'
```

`--preflight-only` validates every requested protected snapshot, public sample and official
private grading registration without executing agents. The campaign runner uses no shell,
starts each agent in a separate process group, enforces the agent wallclock limit and never
serializes inherited environment values. Commands can also use `{task}`, `{arm}`,
`{submission}` and `{time_limit}`. Final official grading is outside the agent time limit.
The runner injects non-secret official/data/manifest/audit paths for the bundled agents.
Set `OPENAI_API_KEY` and optionally `OPENAI_API_BASE` in the parent environment; API keys
are not CLI arguments and are not serialized by the campaign runner.

A `BenchmarkRunRecord(measured=True)` is emitted only from an actual official grading report.
Missing submissions, grading errors and incomplete task/seed/arm matrices remain explicit
failures; partial campaigns and fewer than 22 tasks or 3 seeds never produce a comparison.
The CLI exits nonzero unless a complete measured comparison exists. The bundled host arm
runs the vendored OpenEvolve controller on a generator program containing `SOLUTION_PROMPT`;
the governed arm evolves the same initial prompt through Framework. Both share solution
generation, Bubblewrap execution and official dev validity grading. Generated solutions see
only the workspace and read-only public inputs, with no inherited API credentials. On x86_64,
their direct Popen path uses the shared v56 memfd/`pass_fds` contract to install the same
dangerous-syscall seccomp denylist as detached evaluators; this is not a full allowlist. Host
selection uses dev validity; governed M9 still uses per-item validity flips, never raw scores.

Every real model call writes an independent UUID token-usage receipt. Governed metering
accumulates proposer and solution calls between ledger resets; the OpenEvolve client wrapper
also meters host-evolution calls that do not become incumbents. With `--token-budget`, the
campaign runner independently recomputes each run's usage from receipts and requires exact
agreement with the agent summary, one consistent actual backbone and no overspend before it
can emit a measured record. Missing, zero, malformed, inconsistent or tampered usage fails
closed. The pre-call cap cannot prevent a single response from crossing the budget, so the
runner checks final actual usage as well. These are physical token costs only: no price table
is supplied, no USD cost or `admitted_per_usd` conclusion is produced, and cost never enters M9.

Run the real local calling-chain smoke with `python3 -m pytest -q tests/test_benchmark_agents.py`.
It starts an actual local OpenAI-compatible HTTP service and uses a clearly labelled grading
fixture. This validates both CLI implementations and their isolation/evidence boundaries,
but is not an MLE-Bench execution or performance measurement.

`grade_submission(workspace, visibility, audit_store)` invokes the official grader on demand and writes the complete report only to `audit_store`. `public_report(..., "dev")` exposes only submission validity; `admission` adds above-median feedback without raw score; raw score and medals are reserved for `audit`. `measured_run_record` converts an actual official report plus grading evidence refs into the paired-run schema. These visibility labels are defense-in-depth, not a replacement for process/filesystem isolation.

The included tests are protocol fixtures, not an MLE-Bench execution. No Valid Submission, Above Median, Any Medal, host-parity, or RUBRIC B2 result is claimed until the external runs exist.

## v53 selection and cost evidence

Every measured run carries a `SelectionContract`; the production default is
`single_run` with `mle-official-final-submission-v1` and an explicit not-applicable split.
Paired comparisons reject selection-object, policy or split forks. Actual costs must cover
all declared units, and the complete matrix must have identical declared and actual unit
sets. The runner requires `wallclock`, plus `token` whenever a token budget is declared.
Additional actual units may be reported, but missing units are never zero-filled and no
USD-efficiency conclusion is generated without a real price table.

## v54 replayable selection

Measured records now also require a `SelectionReceipt`. The default single-run receipt
binds the final submission candidate to evidence without fabricating a validation score.
Archive-best or best-single-chain callers must provide the full candidate pool, explicit
validation split and chain-terminal evidence. Official medal/test results never enter
selection replay, and comparison reports include every receipt digest.


## AIDE adapted CSV entry

`PYTHONPATH=m0 python -m zoo.mle_bench_lite.aide_runner --output /tmp/aide-fixture`

The default is an offline, synthetic prior-learning fixture through the public Framework and Linux Bubblewrap sandbox. It has 10 main nodes, three independent drafts, seeded draft/debug/improve selection, task-metric validation, a frozen reporting-only final evaluation, and replay. No model key or Kaggle account is used. `--resume` reuses the original prediction files and does not train or call a provider again after a completed run. Use a fresh output directory for each experiment. The named profile is `config/profiles/aide_mle.json`; the live runner adds the independent initial control and existing CNY campaign bridge.

Live uses the separate CPU environment installed from `scripts/requirements-mle-pilot.lock`, with its interpreter and packages inside the sandbox-visible system tree. Freeze all task/seed cells and official prepared-data identity before calls. Keep the shared anonymization key and existing campaign ledger outside generated workers; do not place credentials in the repository. The runner reads `OPENAI_API_KEY`, never its value from a CLI flag.

```bash
PYTHONPATH=m0 /path/to/mle-environment/bin/python -m zoo.mle_bench_lite.aide_runner \
  --mode live --output /path/to/new-run --task spooky-author-identification \
  --public-root /path/to/mle-data/spooky-author-identification/prepared/public \
  --anonymization-key /path/to/shared-private-anonymization.key \
  --spending-ledger /path/to/original-campaign.db --split-seed 7 --search-seed 0
```

All evaluation requests use split seed 7; search seed affects local policy/control RNG and is not sent as a reproducibility guarantee to the remote model. The pilot uses at most 10 main nodes, output cap 16384, low reasoning effort, and a 120-second candidate timeout. Classification selects maximum negative log loss; regression selects maximum negative mean target RMSLE. It does not use the legacy governance experiment's dev proxy metric. Only CSV features are used; this is not paper-budget or medal-rate reproduction.

`method-report.json`, immutable per-attempt `reports/`, `run-manifest.json`, `composed/x1.jsonl`, generated programs, original predictions, and `submission.csv` retain evidence. All-failed search returns `no_valid_submission` with null final/submission. An unknown provider cost halts and leaves its reservation unresolved. A completed run can be graded later, once, with:

```bash
PYTHONPATH=m0:/path/to/pinned-mle-bench /path/to/mle-environment/bin/python \
  -m zoo.mle_bench_lite.aide_grading --output /path/to/completed-run \
  --official-root /path/to/pinned-mle-bench --data-root /path/to/mle-data \
  --frozen-prepared-identity /path/to/predeclared-official-identity.json \
  --anonymization-key /path/to/shared-private-anonymization.key
```

The identity JSON is the output of the existing `_official_prepared_identity` verifier frozen before search. The grader rechecks official source/prepared checksums, search public CSV hashes, selection and submission; its separate `official/result.json` never changes the winner. Grading failure and interrupted grading are retained without automatic re-execution. The predeclared three-task, three-seed AIDE matrix has completed all nine searches and official grades: 70/90 main candidates and all nine frozen submissions are valid. Original failures, source identities, costs and independent recalculation are published in the [AIDE evidence report](../../../research/experiments/2026-11-05-aide-mle/README.md). This adapted pilot does not establish full-benchmark medal rate or paper-equivalent performance.
