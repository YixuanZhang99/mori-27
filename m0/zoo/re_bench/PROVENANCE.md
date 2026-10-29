# METR RE-Bench provenance

- Upstream: https://github.com/METR/RE-Bench
- Locked revision: `a0cc6d4a91b20f84ebef505d5c72358f88b3b389`
- Maintenance state: upstream marks RE-Bench deprecated; this adapter uses a pinned snapshot rather than assuming ongoing task maintenance.
- Suite: `suite_manifest.yaml`, seven task families: `ai_rd_fix_embedding`, `ai_rd_nanogpt_chat_rl`, `ai_rd_optimize_llm_foundry`, `ai_rd_restricted_mlm`, `ai_rd_rust_codecontests_inference`, `ai_rd_small_scaling_law`, and `ai_rd_triton_cumsum`.
- Suite SHA-256: `0f6205a46c61a26e7476e498a4199b7d2a3ee4abf53c27dbb7f3640ddcd008ff`.
- Official runner and scoring: Vivaria; per-task `TaskFamily.aggregate_scores` consumes the real score log. Per-task `score_on_usage_limits` controls whether an existing log may be scored after timeout.
- `assets/snapshot_manifest.json` locks the suite plus each task's manifest, task module, README, build steps and requirements: 36 files total.
- Code license: MIT. Upstream requests reasonable protection of benchmark solutions; no `official_solution.zip`, protected answer or external score log is bundled here.

No official task environment, Vivaria installation, external campaign, numeric result or hosted run is included. Obtain the official snapshot at the locked revision and satisfy its task-specific infrastructure requirements before execution.
