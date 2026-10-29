"""Real OpenEvolve host arm for the shared MLE solution-prompt generator."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDORED_OPENEVOLVE = ROOT / "vendor/openevolve"
if str(VENDORED_OPENEVOLVE) not in sys.path:
    sys.path.insert(0, str(VENDORED_OPENEVOLVE))

from openevolve.api import run_evolution
from openevolve.config import Config, LLMModelConfig

from zoo.mle_bench_lite.agent_common import (
    INITIAL_GENERATOR, add_common_arguments, export_runtime_environment,
    extract_generator_prompt, metered_host_llm, runtime_from_args)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    args = parser.parse_args(argv)
    runtime = runtime_from_args(args)
    export_runtime_environment(args, runtime)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required; it is never accepted as a logged CLI argument")
    model = LLMModelConfig(
        name=runtime.llm.model, api_base=runtime.llm.base_url, api_key=api_key,
        system_message="Improve the generator while preserving SOLUTION_PROMPT and evolve markers.",
        temperature=0.0, max_tokens=4096, timeout=max(30, int(runtime.solution_timeout)),
        retries=1, retry_delay=1, random_seed=args.seed,
        init_client=metered_host_llm)
    config = Config()
    config.llm.models = [model]
    config.llm.evaluator_models = [model]
    config.diff_based_evolution = False
    config.enforce_evolve_blocks = True
    config.max_code_length = 50_000
    config.max_iterations = args.iterations
    config.random_seed = args.seed
    config.log_level = "WARNING"
    config.evaluator.cascade_evaluation = False
    config.evaluator.parallel_evaluations = 1
    config.evaluator.max_retries = 0
    config.evaluator.timeout = max(120, int(runtime.solution_timeout * 3))
    config.evaluator.enable_artifacts = False
    config.database.num_islands = 1
    config.database.random_seed = args.seed
    config.database.feature_dimensions = ["score"]
    output_dir = runtime.artifacts / "openevolve"
    result = run_evolution(
        INITIAL_GENERATOR, Path(__file__).with_name("host_evaluator.py"),
        config=config, iterations=args.iterations, output_dir=str(output_dir),
        cleanup=False)
    if result.best_code is None:
        raise RuntimeError("OpenEvolve returned no evaluated generator")
    prompt = extract_generator_prompt(result.best_code)
    summary = runtime.finalize(prompt, "host", {
        "iterations": args.iterations,
        "host_best_dev_validity": float(result.metrics.get("dev_valid_submission", 0.0)),
        "generator_representation": "full generator program with SOLUTION_PROMPT"})
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
