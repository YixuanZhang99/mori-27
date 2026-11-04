"""Configured per-instance frontier policy; a GEPA building block, not full GEPA."""
from __future__ import annotations

from core.composition.strategies import GreedyPolicy, policy_options
from core.executor.types import EvalStatus
from core.frontier.gepa import InstanceFrontier


def gepa_policy_options(options):
    if type(options) is not dict or set(options) - {'items', 'seed', 'context_window'}:
        raise ValueError('instance policy requires items, seed and optional context_window')
    policy_options({'context_window': options.get('context_window', 8)})
    InstanceFrontier(options.get('items'), seed=options.get('seed'))


class GEPAInstancePolicy(GreedyPolicy):
    """Sample parents by public development instance winner coverage.

    This policy does not implement GEPA minibatching, paired candidate
    acceptance, or a held-out validation dataset. The task adapter must expose
    exactly the declared public binary verdicts on each successful dev result.
    """
    def __init__(self, scope_context, *, items, seed, context_window=8):
        gepa_policy_options({'items': items, 'seed': seed, 'context_window': context_window})
        super().__init__(scope_context, context_window=context_window)
        self.items, self.seed = tuple(items), seed
        self.instance_frontier = InstanceFrontier(list(items), seed=seed)

    async def select(self, frontier, budget):
        eligible = {node.id for node in frontier.nodes.values() if node.status in {'done', 'merged'}
                    and node.eval_status == EvalStatus.OK.value and node.score is not None}
        if not self.instance_frontier.frequencies(eligible=eligible):
            if eligible:
                raise ValueError('eligible parent lacks public instance evidence')
            return []
        return [self.instance_frontier.select(eligible=eligible)]

    async def absorb(self, evidence):
        result = evidence.eval_result
        if result.status is EvalStatus.OK:
            if result.contract.binding.split_id != 'dev' or result.contract.items is None:
                raise ValueError('GEPA selection requires public instance development evidence')
            values = {}
            for item in result.contract.items:
                if item.visibility != 'public' or item.seed is not None or item.item_id in values \
                        or type(item.verdict) is not int or item.verdict not in (0, 1):
                    raise ValueError('GEPA selection requires unique public instance binary verdicts')
                values[item.item_id] = item.verdict
            if set(values) != set(self.items):
                raise ValueError('GEPA selection requires all frozen public instance verdicts')
            self.instance_frontier.offer(evidence.candidate_id, values)
        return await super().absorb(evidence)

    def checkpoint_state(self):
        return {'schema_version': 1, 'base': super().checkpoint_state(),
                'instance_frontier': self.instance_frontier.checkpoint_state()}

    def restore_state(self, state):
        if type(state) is not dict or set(state) != {'schema_version', 'base', 'instance_frontier'} \
                or type(state['schema_version']) is not int or state['schema_version'] != 1:
            raise ValueError('invalid GEPA instance policy checkpoint')
        frontier = InstanceFrontier.from_checkpoint(state['instance_frontier'])
        frozen = frontier.checkpoint_state()
        if frozen['items'] != list(self.items) or frozen['seed'] != self.seed:
            raise ValueError('GEPA instance policy checkpoint configuration differs')
        super().restore_state(state['base'])
        self.instance_frontier = frontier
