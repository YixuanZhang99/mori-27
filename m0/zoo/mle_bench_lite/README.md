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
