"""Governed Framework arm evolving the same MLE solution prompt as the host."""
from __future__ import annotations

import argparse
import json

from core.eval.types import EvalResult, ItemResult
from core.loop import Framework, LoopConfig
from zoo.mle_bench_lite.agent_common import (
    INITIAL_PROMPT, add_common_arguments, runtime_from_args)


class GenesisAnchoredLLM:
    """Seed genesis from the declared artifact; later draft/improve calls use the LLM."""

    def __init__(self, llm, initial_prompt: str):
        self.llm = llm
        self.initial_prompt = initial_prompt
        self.genesis_pending = True

    @property
    def last_usage(self):
        return self.llm.last_usage

    @last_usage.setter
    def last_usage(self, value):
        self.llm.last_usage = value

    def __call__(self, prompt: str) -> str:
        if self.genesis_pending and prompt.startswith("[draft "):
            self.genesis_pending = False
            return self.initial_prompt
        return self.llm(prompt)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--intent-cost", type=int, default=1_000)
    args = parser.parse_args(argv)
    if args.token_budget < 2_000 or not 0 < args.intent_cost < args.token_budget:
        raise ValueError("token budget must cover genesis, improvement and the control reserve")
    runtime = runtime_from_args(args)
    llm = GenesisAnchoredLLM(runtime.llm, INITIAL_PROMPT.strip())

    def evaluator(candidate_id: str, head_sha: str, prompt: str) -> EvalResult:
        outcome = runtime.evaluate_prompt(candidate_id, prompt)
        valid = bool(outcome["valid_submission"])
        return EvalResult(
            candidate_id=candidate_id, head_sha=head_sha,
            items=[ItemResult("official_dev_submission", int(valid))],
            combined_score=float(valid),
            public={"dev/valid_submission": valid},
            text_feedback=outcome["text_feedback"],
            evaluator_version=outcome["evaluator_version"])

    config = LoopConfig(
        total_budget=args.token_budget, intent_cost=args.intent_cost,
        reeval_floor=min(1_000, args.token_budget // 2),
        max_generations=args.iterations, checkpoint_enabled=True)
    framework = Framework(
        llm, evaluator, config, str(runtime.artifacts / "governed"),
        improve_impl="llm_reflective")
    task_desc = (
        f"MLE task {runtime.task_id}, seed {runtime.seed}. Evolve the shared solution "
        "prompt using official dev validity feedback; never request private answers or scores.")
    result = framework.evolve(task_desc)
    summary = runtime.finalize(result["best_prompt"], "governed", {
        "iterations": args.iterations,
        "accepted_candidates": len(result["accepted_candidate_ids"]),
        "generations": result["generations"],
        "token_spent": result["ledger"]["spent"],
        "generator_representation": "prompt only; shared generator skeleton frozen"})
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
