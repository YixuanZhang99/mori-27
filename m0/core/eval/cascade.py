"""M8 cascade extension: shallow screening with deterministic escalation rules.

The cascade saves evaluation budget only; M9 still adjudicates per-item evidence.
No aggregate score is exposed to the gate beyond the existing display field.
"""
from __future__ import annotations

from core.eval.types import EvalResult, validate_eval_result
from core.llm import reset_usage, take_usage


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
        self._base_evaluator_version = getattr(base_evaluator, "evaluator_version", None)
        self.evaluation_context = getattr(base_evaluator, "evaluation_context", "")
        self.shallow_count = 0
        self.full_count = 0

    def validate_context(self) -> None:
        """Validate the pinned base before starting either evaluation tier."""
        if getattr(self.base, "evaluation_context", "") != self.evaluation_context \
                or getattr(self.base, "evaluator_version", None) != self._base_evaluator_version:
            raise ValueError("cascade base evaluation configuration changed")
        validate = getattr(self.base, "validate_context", None)
        if callable(validate):
            validate()

    def __call__(self, candidate_id: str, head_sha: str, prompt: str) -> EvalResult:
        self.last_usage = {"total_tokens": 0}
        self.validate_context()
        self.last_usage = None
        reset_usage(self.base)
        try:
            shallow = validate_eval_result(
                self.base(candidate_id, head_sha, prompt, item_limit=self.shallow_items),
                candidate_id=candidate_id, head_sha=head_sha,
                evaluator_version=self._base_evaluator_version,
                evaluation_context=self.evaluation_context)
        finally:
            usage = take_usage(self.base)
            self.last_usage = {"total_tokens": usage}
        self.shallow_count += 1
        threshold = self.best_score * self.escalate_at_best_ratio
        if self.best_score > 0 and shallow.combined_score < threshold:
            shallow.private["cascade_stopped"] = True
            shallow.public["tier"] = "shallow"
            self.last_usage = {"total_tokens": usage}
            return shallow
        self.last_usage = None
        reset_usage(self.base)
        try:
            full = validate_eval_result(
                self.base(candidate_id, head_sha, prompt),
                candidate_id=candidate_id, head_sha=head_sha,
                evaluator_version=self._base_evaluator_version,
                evaluation_context=self.evaluation_context)
        finally:
            usage += take_usage(self.base)
            self.last_usage = {"total_tokens": usage}
        self.full_count += 1
        full.private["cascade_stopped"] = False
        full.public["tier"] = "full"
        self.best_score = max(self.best_score, full.combined_score)
        self.last_usage = {"total_tokens": usage}
        return full
