# METR RE-Bench TaskAdapter

This adapter pins the seven-task suite at the revision in `PROVENANCE.md`. Upstream marks RE-Bench deprecated; the lock is therefore part of the evaluation contract, not an optional provenance hint.

Prerequisites for a real campaign:

1. Check out the locked official revision and install Vivaria plus `metr.task_protected_scoring` in the execution environment.
2. Keep the official task modules, manifests, build files and any protected solutions outside the agent-visible workspace. Minimal setup exposes only `description.md` and provenance-only `task.json`; Vivaria owns the actual task environment.
3. Run all seven tasks with at least three paired seeds for host and governed arms, the same backbone and the same declared wallclock budget.
4. Produce a real Vivaria score log for every run. The adapter invokes the locked task's `TaskFamily.aggregate_scores`; raw logs and scores remain in run-level audit evidence.

```bash
python3 -m zoo.re_bench.runner \
  --official-root /path/to/RE-Bench --output-root /path/to/new/campaign \
  --backbone SAME_MODEL --time-limit 28800 --seeds 1 2 3 --noise-floor MEASURED_FLOOR \
  --host-command 'YOUR_HOST_ENTRYPOINT --workspace {workspace} --task {task} --seed {seed} --score-log {score_log}' \
  --governed-command 'YOUR_GOVERNED_ENTRYPOINT --workspace {workspace} --task {task} --seed {seed} --score-log {score_log}'
```

The command template also supports `{arm}`, `{time_limit}` and `{official_root}`. Each agent runs in its own process group. Timeout kills that group; a timed-out run may be scored only when the official task manifest declares `score_on_usage_limits: true` and a real score log already exists. Actual wallclock is preserved rather than clipped to the budget.

A missing or malformed score log, non-finite official aggregate, protected-file change, over-budget non-wallclock cost or incomplete task/seed/arm matrix fails closed. No score log means no measured record. The CLI exits nonzero unless a complete paired comparison exists. Environment credentials are inherited by real agents but are not serialized by the runner.

`ScoreRunRecord` and `compare_scores_same_budget` are generic numeric-score evidence types. They do not reuse MLE-Bench medal fields, and score, cost or wallclock never enters M9 admission. Without a real price table this path produces no USD or `admitted_per_usd` conclusion.

The local tests use protocol fixtures and real subprocesses to validate mechanics only. They are not a RE-Bench execution or performance result. No seven-task external campaign, host parity or RUBRIC B3 completion is claimed by this adapter alone.

## v53 selection and cost evidence

Every officially scored run carries a `SelectionContract`; the production default is
`single_run` with `vivaria-official-aggregate-v1` and an explicit not-applicable split.
A paired comparison requires one identical contract across the complete matrix. Every
declared budget unit must have an actual measurement, all runs must expose identical
declared and actual cost-unit sets, and the runner requires `wallclock`. Missing costs
are never treated as zero. These are evidence-completeness rules, not an external score
or host-parity result.

## v54 replayable selection

Measured records now also require a `SelectionReceipt`. The default single-run receipt
binds the final candidate ID to scoring evidence without inventing a validation score.
Pool-based callers must supply their complete candidate pool and validation evidence;
RE-Bench official test scores are never used to choose the winning candidate. Every
paired comparison publishes each run's receipt SHA256 and replays selection before use.
