"""AIDE draft quota, buggy-leaf repair and validation-best improvement."""
import random

from core.composition.contracts import Selection, json_copy
from core.composition.strategies import GreedyPolicy, policy_options


def aide_options(options):
    if type(options) is not dict or set(options) - {
            'num_drafts', 'debug_probability', 'max_debug_depth', 'seed', 'context_window'}:
        raise ValueError('unsupported AIDE policy options')
    policy_options({'context_window': options.get('context_window', 8)})
    for key, default, minimum in (('num_drafts', 3, 1), ('max_debug_depth', 2, 0), ('seed', 0, 0)):
        value = options.get(key, default)
        if type(value) is not int or value < minimum:
            raise ValueError(f'AIDE {key} must be an integer >= {minimum}')
    probability = options.get('debug_probability', .5)
    if type(probability) not in (int, float) or not 0 <= probability <= 1:
        raise ValueError('AIDE debug_probability must be between zero and one')


def debug_depth(node, nodes):
    """Count consecutive buggy ancestors; a failed root has depth zero."""
    depth, seen = 0, {node.id}
    while node.parent_ids:
        if len(node.parent_ids) != 1 or node.parent_ids[0] in seen:
            raise ValueError('AIDE requires an acyclic single-parent code tree')
        node = nodes[node.parent_ids[0]]
        if node.eval_status == 'ok':
            break
        seen.add(node.id)
        depth += 1
    return depth


def repairable(node, nodes, limit):
    return (node.status in {'done', 'merged'} and
            node.eval_status in {'failed_to_run', 'timeout', 'invalid'} and
            not node.children_ids and debug_depth(node, nodes) < limit)


def _tuples(value):
    return tuple(_tuples(item) for item in value) if type(value) is list else value


class AIDEPolicy(GreedyPolicy):
    def __init__(self, scope_context, *, num_drafts=3, debug_probability=.5,
                 max_debug_depth=2, seed=0, context_window=8):
        self.config = dict(num_drafts=num_drafts, debug_probability=debug_probability,
                           max_debug_depth=max_debug_depth, seed=seed, context_window=context_window)
        aide_options(self.config)
        super().__init__(scope_context, context_window=context_window)
        self.rng = random.Random(seed)

    def choose(self, frontier):
        nodes = sorted(frontier.nodes.values(), key=lambda n: (n.created_cycle, n.id))
        if sum(not n.parent_ids for n in nodes) < self.config['num_drafts']:
            return Selection([], 'draft')
        if self.rng.random() < self.config['debug_probability']:
            failed = [n for n in nodes if repairable(n, frontier.nodes, self.config['max_debug_depth'])]
            if failed:
                return Selection([self.rng.choice(failed).id], 'debug')
        valid = [n for n in nodes if n.status in {'done', 'merged'} and
                 n.eval_status == 'ok' and n.score is not None]
        if not valid:
            return Selection([], 'draft')
        best = (max if frontier.direction == 'maximize' else min)(valid, key=lambda n: n.score)
        return Selection([best.id], 'improve')

    async def select(self, frontier, budget):
        return self.choose(frontier)

    async def ideate(self, context, parent, k):
        intent = {'draft': 'Construct an independent executable solution',
                  'debug': 'Repair the selected failed program using its public execution feedback',
                  'improve': 'Improve the selected validation-best program'}
        return [{'hypothesis': context.get('execution', {}).get('hypothesis') or
                 intent[context['operator']]} for _ in range(k)]

    async def absorb(self, evidence):
        # M5 owns the source-bound L1 journal. Do not inherit L2 promotion.
        return []

    def checkpoint_state(self):
        import json
        return {'schema_version': 1, 'base': super().checkpoint_state(),
                'config': json_copy(self.config), 'rng_state': json.loads(json.dumps(self.rng.getstate()))}

    def restore_state(self, state):
        if type(state) is not dict or set(state) != {'schema_version', 'base', 'config', 'rng_state'} \
                or type(state['schema_version']) is not int or state['schema_version'] != 1 \
                or state['config'] != self.config:
            raise ValueError('AIDE checkpoint configuration differs')
        super().restore_state(state['base'])
        try:
            self.rng.setstate(_tuples(state['rng_state']))
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid AIDE RNG state') from exc
