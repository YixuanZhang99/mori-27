"""Toy GEPA-shaped load: deterministic per-item scoring + a mock reflective LLM.

12 items; items 0-3 solvable by the base prompt, items 4-11 each require a
specific hint string in the prompt. The evaluator returns per-item binary
verdicts plus text_feedback naming one missing hint (the GEPA lifeline).
The mock LLM's reflective improve appends that hint — so real improvement is
possible, while the IID-RS baseline (draft only) stays flat by construction.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.loop import Framework, LoopConfig

HINTS = [f"hint_{i}" for i in range(4, 12)]
ITEM_IDS = [f"item_{i}" for i in range(12)]


def toy_evaluator(candidate_id: str, head_sha: str, prompt: str) -> EvalResult:
    toy_evaluator.last_usage = {"total_tokens": 0}  # deterministic local scoring
    items = []
    unsolved = []
    for i, iid in enumerate(ITEM_IDS):
        solved = i < 4 or f"hint_{i}" in prompt
        items.append(ItemResult(item_id=iid, verdict=1 if solved else 0))
        if not solved:
            unsolved.append(i)
    score = sum(it.verdict for it in items) / len(items)
    feedback = "all solved"
    if unsolved:
        i = unsolved[0]
        feedback = f"item_{i} failed; missing hint: hint_{i}"
    return EvalResult(candidate_id=candidate_id, head_sha=head_sha, items=items,
                      combined_score=score, text_feedback=feedback,
                      reliability=ReliabilityMeta(n_trials=1, noise_floor=0.0))


class MockLLM:
    """Offline simulator, explicitly charging 1,000 simulated tokens per call."""

    supplier = "offline-simulation"
    model = "toy-script-v1"

    def __call__(self, prompt: str) -> str:
        self.last_usage = {"total_tokens": 1000}
        if prompt.startswith("[draft"):
            return "Solve the problem carefully."
        m = re.search(r"missing hint: (\w+)", prompt)
        current = prompt.split("CURRENT PROMPT:\n", 1)[1].split("\n\nSCORE:", 1)[0]
        if m:
            return current + "\n" + m.group(1)
        return current


def run(workdir: str = "/tmp/m0_toy", max_generations: int = 20) -> dict:
    fw = Framework(MockLLM(), toy_evaluator,
                   LoopConfig(max_generations=max_generations), workdir)
    return fw.evolve("Toy arithmetic prompt optimization")


if __name__ == "__main__":
    out = run(workdir=tempfile.mkdtemp(prefix="m0_toy_"))
    print(f"best_score       = {out['best_score']:.3f}")
    print(f"main trajectory  = {[round(s, 2) for s in out['main_scores']]}")
    print(f"IID-RS baseline  = {[round(s, 2) for s in out['baseline_scores']]}")
    print(f"B1 self-proof    = {out['self_attestation']}")
    print(f"C1/C2 audit = {out['governance_audit']['passed']}")
    print(f"ledger           = {out['ledger']}")
