"""Driver-owned Arbor bindings. No optimizer loop or independent paid-call path."""
from __future__ import annotations

import hashlib

from core.composition.contracts import json_copy


class ArborCoordinator:
    def __init__(self, owner):
        self.owner = owner
        self.current = None
        cfg = owner.assembly
        if (not owner.construction_enabled or not owner.hierarchical or not owner.layered
                or cfg.memory.options.get('context_scope') != 'run'
                or cfg.knowledge is not None or cfg.execution.spec.hypothesis_frozen is not True
                or [spec.name for spec in cfg.operators] != ['hypothesis_refine']
                or not cfg.frontier.options.get('retain_rejected')):
            raise ValueError('Arbor requires frozen M7, hierarchical budget, retained tree and isolated layered admission')

    def prepare_observation(self, state, context):
        state = json_copy(state)
        for node in state['frontier']['nodes']:
            proposal = self.owner.proposals.get(node['id'])
            unavailable = proposal is None or not proposal.artifact.strip()
            if proposal is not None:
                direction, _ = self.owner._candidate_scope(proposal.candidate)
                unavailable = unavailable or not self.owner.budget.should_continue(direction)
            if unavailable:
                node['status'] = 'pruned'
        self.owner.store.append('arbor_observed', {'cycle': state['cycle'],
            'context_ref': context['context_pack_ref'], 'candidate_ids': [n['id'] for n in state['frontier']['nodes']]})
        state['planning_context'] = self.owner.construction.project(context)
        return state

    def proposed(self, cycle):
        policy = self.owner.parts['policy']
        self.owner.store.append('arbor_ideas_proposed', {'cycle': cycle,
            'ideas': json_copy(policy.new_ideas), 'selection': policy.selection})

    def selection(self, candidate_id, cycle, context):
        owner = self.owner
        idea = owner.parts['policy'].selected
        if idea is None:
            raise ValueError('Arbor has no selected hypothesis')
        basis, artifact = None, None
        if owner.incumbent is not None:
            proposal = owner.proposals[owner.incumbent]
            materialized = owner.construction.materializations[owner.incumbent]
            if materialized.proposal != proposal:
                raise ValueError('Arbor trunk differs from original materialization')
            basis = {'candidate_id': owner.incumbent,
                'artifact_sha256': hashlib.sha256(proposal.artifact.encode()).hexdigest(),
                'materialization_ref': materialized.ref}
            artifact = proposal.artifact
        binding = {'schema_version': 1, 'candidate_id': candidate_id, 'cycle': cycle,
            'hypothesis_id': idea['id'], 'hypothesis': idea['hypothesis'],
            'skeleton_parents': [] if idea['parent_id'] is None else [idea['parent_id']],
            'source_refs': idea['source_refs'], 'execution_base': basis,
            'context_ref': context['context_pack_ref']}
        self.current = {'binding': binding, 'artifact': artifact}
        owner.store.append('arbor_selected', json_copy(binding))
        return json_copy(self.current)

    def validate_request(self, request):
        if (self.current is None or request.strategy.get('arbor') != self.current
                or request.strategy.get('hypotheses') != [{'hypothesis': self.current['binding']['hypothesis']}]
                or request.candidate_id != self.current['binding']['candidate_id']
                or request.context.get('context_pack_ref') != self.current['binding']['context_ref']):
            raise ValueError('Arbor request differs from the driver-bound hypothesis or trunk')

    def dispatch(self, operation):
        if self.current is None or operation['cycle'] != self.current['binding']['cycle']:
            raise ValueError('Arbor dispatch lacks its original selection')
        self.owner.store.append('arbor_dispatched', {'binding': json_copy(self.current['binding']),
                                                   'operation': operation})

    def references(self, candidate_id):
        if self.current is None or self.current['binding']['candidate_id'] != candidate_id:
            raise ValueError('Arbor result lacks its selected hypothesis')
        for ref in self.current['binding']['source_refs']:
            if ref.startswith('candidate:'):
                self.owner.frontier.add_reference(ref.removeprefix('candidate:'), candidate_id,
                                                  'hypothesis source ' + ref)
