"""OpenEvolve host sampling policy; the coordinator supplies original events."""
from __future__ import annotations

import copy
import math

from core.composition.strategies import GreedyPolicy


class OpenEvolvePolicy(GreedyPolicy):
    """Choose a measured host parent without treating host retention as admission.

    The Framework coordinator must supply the actual candidate ID and original
    event journal. This policy does not dispatch models or settle evaluations.
    """

    def __init__(self, scope_context, *, adapter, context_window=8):
        super().__init__(scope_context, context_window=context_window)
        self.adapter = adapter
        self._scope_context = scope_context

    async def select(self, frontier, budget):
        raise ValueError('OpenEvolve selection requires candidate identity and original events')

    async def select_for_candidate(self, candidate_id, frontier, budget, original_events):
        nodes = frontier.nodes
        eligible = {node.id for node in nodes.values()
                    if node.status in {'done', 'merged'} and node.eval_status == 'ok'
                    and type(node.score) in (int, float) and math.isfinite(node.score)}
        state = self.adapter.checkpoint_state()
        self.adapter.restore_state(state, original_events)
        if not self.adapter.events:
            if nodes:
                raise ValueError('frontier candidates lack original host evidence')
            return []
        if not eligible:
            raise ValueError('no eligible candidate remains in host population')
        receipt = self.adapter.select(candidate_id, eligible)
        return [receipt['source_candidate_id']]

    def pending_selection(self):
        events = self.adapter.events
        if events and events[-1]['kind'] == 'select':
            return copy.deepcopy(events[-1]['result'])
        return None

    def checkpoint_state(self):
        return {'policy': super().checkpoint_state(), 'host': self.adapter.checkpoint_state()}

    def restore_state(self, state, original_events):
        if type(state) is not dict or set(state) != {'policy', 'host'}:
            raise ValueError('invalid OpenEvolve policy checkpoint')
        # Validate the ordinary policy checkpoint before changing host state.
        checked = GreedyPolicy(self._scope_context, context_window=self.context_window)
        checked.restore_state(state['policy'])
        self.adapter.restore_state(state['host'], original_events)
        super().restore_state(state['policy'])

    async def absorb(self, evidence):
        # Retention and admission are performed by their respective owners.
        return []
