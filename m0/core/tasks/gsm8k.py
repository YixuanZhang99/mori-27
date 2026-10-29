"""GSM8K-style deterministic task evaluator for prompt-evolution loads.

Dataset JSONL rows: {"question": ..., "answer": "... #### 42"} or
{"question": ..., "answer": 42}. The candidate is the solver's instruction prompt.
Scoring is per-item exact numeric match; feedback is textual and never enters M9.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from core.eval.types import EvalResult, ItemResult, ReliabilityMeta
from core.llm import reset_usage, take_usage

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def extract_number(text: str) -> float | None:
    """Prefer an explicit #### answer; otherwise use the final numeric token."""
    if "####" in text:
        text = text.rsplit("####", 1)[1]
    matches = _NUMBER.findall(text.replace("$", ""))
    if not matches:
        return None
    return float(matches[-1].replace(",", ""))


def load_jsonl(path: str | Path, limit: int | None = None) -> list[dict]:
    items = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            gold = extract_number(str(row["answer"]))
            if gold is None:
                raise ValueError(f"unparseable gold answer: {row['answer']!r}")
            items.append({"question": row["question"], "gold": gold})
            if limit is not None and len(items) >= limit:
                break
    if not items:
        raise ValueError("empty evaluation set")
    return items


class GSM8KEvaluator:
    def __init__(self, items: list[dict], solver_llm: Callable[[str], str],
                 evaluator_version: str = "gsm8k-det-v1", max_feedback: int = 3):
        self.items = items
        self.solver_llm = solver_llm
        self.evaluator_version = evaluator_version
        self.max_feedback = max_feedback
        self.last_usage = {"total_tokens": 0}

    def __call__(self, candidate_id: str, head_sha: str, prompt: str,
                 item_limit: int | None = None) -> EvalResult:
        results: list[ItemResult] = []
        failures: list[str] = []
        total_usage = 0
        self.last_usage = {"total_tokens": 0}
        selected_items = self.items if item_limit is None else self.items[:item_limit]
        for idx, item in enumerate(selected_items):
            solver_prompt = (f"{prompt}\n\nQuestion: {item['question']}\n"
                             "End your response with '#### <number>'.")
            reset_usage(self.solver_llm)
            self.last_usage = None  # cost of this invocation is not yet known
            try:
                output = self.solver_llm(solver_prompt)
            finally:
                total_usage += take_usage(self.solver_llm)
                self.last_usage = {"total_tokens": total_usage}
            pred = extract_number(output)
            gold = float(item["gold"])
            ok = pred is not None and abs(pred - gold) < 1e-6
            results.append(ItemResult(item_id=f"gsm8k-{idx}", verdict=1 if ok else 0))
            if not ok and len(failures) < self.max_feedback:
                failures.append(
                    f"gsm8k-{idx}: question={item['question']}; expected={gold:g}; "
                    f"predicted={pred}; solver_output={output[:400]}")
        self.last_usage = {"total_tokens": total_usage}
        score = sum(r.verdict for r in results) / len(results)
        feedback = ("All evaluation items solved." if not failures else
                    "Failed examples and expected answers:\n" + "\n".join(failures))
        return EvalResult(candidate_id=candidate_id, head_sha=head_sha,
                          items=results, combined_score=score,
                          public={"score": score}, private={"gold_count": len(results)},
                          text_feedback=feedback,
                          reliability=ReliabilityMeta(n_trials=1, noise_floor=0.0),
                          evaluator_version=self.evaluator_version)
