"""Optional, explicitly billed training screen before full development scoring."""
from dataclasses import asdict, dataclass

from core.composition.evaluation import request_digest, validate_evidence
from core.executor.types import EvalRequest, EvalStatus


@dataclass(frozen=True)
class PairedEvaluationPlan:
    request: EvalRequest
    item_ids: tuple[str, ...]
    metric: str = 'train/score'

    def __post_init__(self):
        self.request.validate()
        if self.request.split_id != 'train' or self.request.resume_from is not None:
            raise ValueError('paired screen requires an explicit train request')
        if type(self.item_ids) is not tuple or not self.item_ids or any(
                type(i) is not str or not i for i in self.item_ids) or len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError('paired screen requires frozen unique item IDs')
        if self.metric != 'train/score':
            raise ValueError('paired screen cannot publish a development metric')

    def to_dict(self):
        return {'request': asdict(self.request), 'item_ids': list(self.item_ids),
                'metric': self.metric, 'criterion': 'strict_improvement'}

    def scores(self, evidence):
        result = evidence.eval_result
        if result.status is not EvalStatus.OK:
            return None
        if result.contract.binding.request_sha256 != request_digest(self.request):
            raise ValueError('paired evidence uses a different training request')
        items = result.contract.items or ()
        if tuple(i.item_id for i in items) != self.item_ids or any(
                i.visibility != 'public' or i.seed is not None or type(i.verdict) is not int
                or i.verdict not in (0, 1) for i in items):
            raise ValueError('paired evidence requires the exact public binary training items')
        values = [i.verdict for i in items]
        if set(result.metrics) != {self.metric} or result.metrics[self.metric] != sum(values) / len(values):
            raise ValueError('training scores cannot claim development performance')
        return values

    def accepts(self, parent, child):
        before, after = self.scores(parent), self.scores(child)
        return before is not None and after is not None and sum(after) > sum(before)


def feedback_payload(evidence):
    """Explicit public training provenance; no validation errors in reflection."""
    validate_evidence(evidence, require_full=False)
    result = evidence.eval_result
    if result.contract.visibility != 'public' or result.contract.binding.split_id != 'train':
        raise ValueError('reflection requires an explicitly public training projection')
    return {'source': asdict(result.contract.binding), 'rollouts': result.text_feedback,
            'items': [asdict(i) for i in result.contract.items or () if i.visibility == 'public']}
