"""M8/M9 types (M0 kernel subset). See 开发指南 M8M9 页 §1."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal, Optional


@dataclass
class ItemResult:
    item_id: str
    verdict: Literal[0, 1]


@dataclass
class ReliabilityMeta:
    n_trials: int = 1
    ci95: Optional[tuple[float, float]] = None
    noise_floor: Optional[float] = None


@dataclass
class EvalResult:
    candidate_id: str
    head_sha: str
    items: list[ItemResult]
    combined_score: float = 0.0          # display-only; never a gate input
    public: dict = field(default_factory=dict)
    private: dict = field(default_factory=dict)
    text_feedback: str = ""              # S-4: required for reflective improve
    reliability: ReliabilityMeta = field(default_factory=ReliabilityMeta)
    evaluator_version: str = "det-v1"
    evaluation_context: str = ""        # empty only for legacy opaque evaluators


def validate_eval_result(result: EvalResult, *, candidate_id: str | None = None,
                         head_sha: str | None = None,
                         evaluator_version: str | None = None,
                         evaluation_context: str | None = None) -> EvalResult:
    """Validate native per-item evidence at each consumption boundary.

    EvalResult and ItemResult remain mutable transport types, so construction-time
    checks alone cannot protect restored or subsequently modified outcomes.
    Optional expected identities bind a result to the operation that produced it.
    Empty evaluation_context is a legacy version/item-ID contract; it does not
    certify dataset content or undeclared configuration of an opaque evaluator.
    This function deliberately does not interpret aggregate metrics or costs.
    """
    if not isinstance(result, EvalResult):
        raise ValueError("evaluation result must be an EvalResult")
    for field_name, expected in (("candidate_id", candidate_id),
                                 ("head_sha", head_sha),
                                 ("evaluator_version", evaluator_version)):
        value = getattr(result, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"evaluation {field_name} must be a non-empty string")
        if expected is not None and value != expected:
            raise ValueError(f"evaluation {field_name} binding mismatch")
    context = result.evaluation_context
    if not isinstance(context, str) or (context and not re.fullmatch(r"sha256:[0-9a-f]{64}", context)):
        raise ValueError("evaluation_context must be empty or a canonical SHA-256 digest")
    if evaluation_context is not None and context != evaluation_context:
        raise ValueError("evaluation evaluation_context binding mismatch")
    if not isinstance(result.items, list) or not result.items:
        raise ValueError("EvalResult.items must be a non-empty list (gate-not-rank)")
    item_ids: set[str] = set()
    for item in result.items:
        if not isinstance(item, ItemResult):
            raise ValueError("evaluation items must be ItemResult records")
        if not isinstance(item.item_id, str) or not item.item_id.strip():
            raise ValueError("evaluation item_id must be a non-empty string")
        if item.item_id in item_ids:
            raise ValueError("evaluation item ids must be unique")
        # bool and 0.0/1.0 compare equal to integers but are not binary evidence.
        if type(item.verdict) is not int or item.verdict not in (0, 1):
            raise ValueError("evaluation verdicts must be binary integers (0 or 1)")
        item_ids.add(item.item_id)
    if not isinstance(result.public, dict) or not isinstance(result.private, dict):
        raise ValueError("evaluation public/private must be objects")
    if "cascade_stopped" in result.private and type(result.private["cascade_stopped"]) is not bool:
        raise ValueError("evaluation cascade_stopped must be a boolean")
    return result


def validate_eval_comparison(result: EvalResult, incumbent: EvalResult) -> None:
    """Require a fixed sample universe and evaluator for final adjudication."""
    validate_eval_result(result)
    validate_eval_result(incumbent)
    if result.evaluator_version != incumbent.evaluator_version:
        raise ValueError("evaluation comparison requires the same evaluator version")
    if result.evaluation_context != incumbent.evaluation_context:
        raise ValueError("evaluation comparison requires the same evaluation context")
    if {item.item_id for item in result.items} != {item.item_id for item in incumbent.items}:
        raise ValueError("evaluation comparison requires identical item ids")


@dataclass
class Verdict:
    kind: Literal["ACCEPT", "REJECT"]
    rationale_ref: Optional[str] = None


@dataclass
class Receipt:
    receipt_id: str
    verdict: Verdict
    head_sha: str
    evaluator_version: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class GateEvidenceRecord:
    candidate_id: str
    receipt_id: Optional[str]
    transition: str                     # evaluate | verdict | invalidate:* | rollback
    rule_id: str
    signals_snapshot: dict = field(default_factory=dict)
    decision_context: dict = field(default_factory=dict)
