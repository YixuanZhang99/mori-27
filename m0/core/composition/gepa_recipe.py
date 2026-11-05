"""Single-component GEPA reflection recipe with deterministic epoch batches."""
import hashlib
import json
import random

from core.composition.construction_recipes import RecipeOperator
from core.composition.paired_evaluation import PairedEvaluationPlan, feedback_payload
from core.executor.types import EvalRequest


def epoch_batch(item_ids, *, seed, size, iteration):
    if type(seed) is not int or seed < 0 or type(iteration) is not int or iteration < 0 \
            or type(size) is not int or size < 1 or type(item_ids) is not list or not item_ids \
            or any(type(i) is not str or not i for i in item_ids) \
            or len(set(item_ids)) != len(item_ids) or len(item_ids) % size:
        raise ValueError('GEPA pilot requires unique original IDs and complete equal-sized batches')
    rng = random.Random(seed)
    batches_per_epoch = len(item_ids) // size
    for _ in range(iteration // batches_per_epoch + 1):
        shuffled = sorted(item_ids)
        rng.shuffle(shuffled)
    offset = iteration % batches_per_epoch * size
    return shuffled[offset:offset + size]


def training_plan(item_ids, *, seed, size, iteration):
    batch = epoch_batch(item_ids, seed=seed, size=size, iteration=iteration)
    identity = json.dumps({'ids': batch, 'seed': seed, 'iteration': iteration}, sort_keys=True)
    request = EvalRequest('train:' + hashlib.sha256(identity.encode()).hexdigest(),
                          split_id='train', seed_set=[seed])
    return PairedEvaluationPlan(request, tuple(batch))


def gepa_recipe_options(options):
    if type(options) is not dict or set(options) != {'train_ids', 'seed', 'minibatch_size'}:
        raise ValueError('GEPA recipe requires train_ids, seed and minibatch_size')
    epoch_batch(options['train_ids'], seed=options['seed'], size=options['minibatch_size'], iteration=0)


class GEPAReflectiveRecipe:
    measured_cost_units = ("token", "node", "eval_count")
    def __init__(self, *, train_ids, seed, minibatch_size):
        gepa_recipe_options(dict(train_ids=train_ids, seed=seed, minibatch_size=minibatch_size))
        self.train_ids, self.seed, self.minibatch_size = list(train_ids), seed, minibatch_size

    def evaluation_plan(self, request):
        if len(request.parents) != 1 or request.cycle < 1:
            raise ValueError('GEPA reflection requires one evaluated parent')
        return training_plan(self.train_ids, seed=self.seed, size=self.minibatch_size,
                             iteration=request.cycle - 1)

    def recipe(self, request):
        plan = self.evaluation_plan(request)
        if len(request.evidence) != 1 or plan.scores(request.evidence[0]) is None:
            raise ValueError('GEPA reflection requires successful actual training feedback')
        feedback = request.evidence[0].eval_result.text_feedback
        if not feedback.strip():
            raise ValueError('GEPA reflection cannot use empty rollout feedback')
        result = RecipeOperator('reflective', metric='train/score').recipe(request)
        result['instructions'] = [
            'Reflect on the following training rollouts and errors, then return an improved solver instruction prompt. '
            'The artifact must be reusable instructions, not answers for these particular questions.\n' +
            json.dumps(feedback_payload(request.evidence[0]), sort_keys=True, ensure_ascii=False)]
        return result
