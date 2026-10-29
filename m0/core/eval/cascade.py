"""M8 cascade extension: shallow screening with deterministic escalation rules.

The cascade saves evaluation budget only; M9 still adjudicates per-item evidence.
No aggregate score is exposed to the gate beyond the existing display field.
"""
from __future__ import annotations

from core.eval.types import EvalResult
from core.llm import take_usage


class CascadingEvaluator:
    def __init__(self, base_evaluator, shallow_items: int,
                 escalate_at_best_ratio: float = 0.5):
        if shallow_items < 1 or not 0 <= escalate_at_best_ratio <= 1:
            raise ValueError("invalid cascade configuration")
        self.base = base_evaluator
        self.shallow_items = shallow_items
        self.escalate_at_best_ratio = escalate_at_best_ratio
        self.best_score = 0.0
        self.last_usage = {"total_tokens": 0}
        self.evaluator_version = getattr(base_evaluator, "evaluator_version",
                                         "cascade-det-v1")
        self.shallow_count = 0
        self.full_count = 0

    def __call__(self, candidate_id: str, head_sha: str, prompt: str) -> EvalResult:
        shallow = self.base(candidate_id, head_sha, prompt,
                            item_limit=self.shallow_items)
        self.shallow_count += 1
        usage = take_usage(self.base)
        threshold = self.best_score * self.escalate_at_best_ratio
        if self.best_score > 0 and shallow.combined_score < threshold:
            shallow.private["cascade_stopped"] = True
            shallow.public["tier"] = "shallow"
            self.last_usage = {"total_tokens": usage}
            return shallow
        full = self.base(candidate_id, head_sha, prompt)
        self.full_count += 1
        usage += take_usage(self.base)
        full.private["cascade_stopped"] = False
        full.public["tier"] = "full"
        self.best_score = max(self.best_score, full.combined_score)
        self.last_usage = {"total_tokens": usage}
        return full
