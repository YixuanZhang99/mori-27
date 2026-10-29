"""Offline GSM8K-style end-to-end run through Framework.evolve.

All framework/evaluator/metering code is real; only the two LLM endpoints are
deterministic scripts so CI needs no credentials or network.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import Framework, LoopConfig
from core.tasks.gsm8k import GSM8KEvaluator

ITEMS = [
    {"question": "Tom has 2 apples and buys 3. How many?", "gold": 5.0},
    {"question": "A box holds 6 pens. Two boxes hold how many?", "gold": 12.0},
    {"question": "10 minus 4 equals?", "gold": 6.0},
    {"question": "Three times 7 equals?", "gold": 21.0},
]
ANSWERS = {"apples": 5, "pens": 12, "minus": 6, "times": 21}


class OfflineSolver:
    """Solves every item only when the candidate prompt requests reasoning."""
    def __init__(self):
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt: str) -> str:
        self.last_usage = {"total_tokens": 10}
        if "Show your reasoning step by step" not in prompt:
            return "The answer is unclear."
        for key, answer in ANSWERS.items():
            if key in prompt:
                return f"Reasoning steps omitted.\n#### {answer}"
        return "#### 0"


class OfflineProposer:
    """Reflective proposer: turns failure feedback into an instruction edit."""
    def __init__(self):
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt: str) -> str:
        self.last_usage = {"total_tokens": 20}
        if prompt.startswith("[draft"):
            return "Answer the question."
        current = prompt.split("CURRENT PROMPT:\n", 1)[1].split("\n\nSCORE:", 1)[0]
        if "Failed examples" in prompt and "Show your reasoning step by step" not in current:
            return current + "\nShow your reasoning step by step."
        return current


def run(workdir: str = "/tmp/m0_gsm8k", generations: int = 4) -> dict:
    evaluator = GSM8KEvaluator(ITEMS, OfflineSolver())
    fw = Framework(OfflineProposer(), evaluator,
                   LoopConfig(total_budget=5_000, intent_cost=500,
                              reeval_floor=100, baseline_every=2,
                              max_generations=generations),
                   workdir)
    return fw.evolve("Offline GSM8K-style prompt evolution")


if __name__ == "__main__":
    out = run(workdir=tempfile.mkdtemp(prefix="m0_gsm8k_"))
    print("best_prompt:", out["best_prompt"])
    print("best_score:", out["best_score"])
    print("main_scores:", out["main_scores"])
    print("baseline_scores:", out["baseline_scores"])
    print("C1/C2 audit =", out["governance_audit"]["passed"])
    print("ledger:", out["ledger"])
