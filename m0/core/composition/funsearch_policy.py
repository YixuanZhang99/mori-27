"""Checkpointable FunSearch population policy; runtime bridge is not installed.

The driver must journal selection before physical generation, validate public
projection against original evidence, and bind state to that journal on restore.
"""
from __future__ import annotations

import copy
import re
from core.composition.strategies import GreedyPolicy
from core.executor.types import EvalStatus
from core.funsearch_population import FunSearchPopulation
from core.funsearch_selection import draw_selection, verify_selection
from core.x1.checkpoint import payload_digest


class FunSearchPolicy(GreedyPolicy):
    def __init__(self, scope_context, *, case_ids, islands, seed, prompt_size,
                 temperature, temperature_period, context_window=8):
        super().__init__(scope_context, context_window=context_window)
        self.population = FunSearchPopulation(case_ids=case_ids, islands=islands, seed=seed,
            prompt_size=prompt_size, temperature=temperature, temperature_period=temperature_period)
        if prompt_size > 2:
            raise ValueError('current runtime supports at most two distinct parents')
        self._config = self.population.checkpoint_state()['config']
        self._evidence_refs = {}
        self._pending = None

    async def select(self, frontier, budget):
        if self._pending is not None:
            raise ValueError('pending program selection must be settled first')
        eligible = {node.id for node in frontier.nodes.values() if node.status in {'done', 'merged'}
                    and node.eval_status == EvalStatus.OK.value and node.score is not None}
        if not self._evidence_refs:
            if eligible:
                raise ValueError('eligible candidates lack public program evidence')
            return []
        if not eligible:
            raise ValueError('no eligible candidate remains in the population')
        before = self.population.checkpoint_state()
        receipt = draw_selection(self.population, None, eligible=eligible, max_parents=2)
        after = self.population.checkpoint_state()
        self._pending = {'receipt': receipt, 'before': before, 'after': after}
        return list(receipt['ancestry'])

    def pending_selection(self):
        return copy.deepcopy(self._pending)

    def record_evaluated(self, projection):
        if type(projection) is not dict or set(projection) != {
                'candidate_id', 'scores', 'program_ref', 'program_length', 'evidence_ref'}:
            raise ValueError('evaluated candidate requires a complete public projection')
        candidate = projection['candidate_id']
        if type(candidate) is not str or not candidate or candidate in self._evidence_refs:
            raise ValueError('candidate already recorded or identity invalid')
        ref = projection['evidence_ref']
        if type(ref) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', ref):
            raise ValueError('canonical original evidence reference required')
        if self._pending is None:
            if self._evidence_refs:
                raise ValueError('evaluated child requires a pending selection')
            island, epoch = None, None
        else:
            island, epoch = self._pending['receipt']['island'], self._pending['receipt']['epoch']
        self.population.register_projection(candidate, program_ref=projection['program_ref'],
            program_length=projection['program_length'], scores=projection['scores'], island=island, epoch=epoch)
        self._evidence_refs[candidate] = ref
        self._pending = None

    def abandon_selection(self, reason):
        if self._pending is None or reason not in {'evaluation_failed', 'stale_epoch'}:
            raise ValueError('pending selection and explicit failure reason are required')
        previous = copy.deepcopy(self._pending)
        self._pending = None
        return {**previous, 'reason': reason}

    def reset_weaker_half(self):
        if self._pending is not None:
            raise ValueError('pending program selection prevents island reset')
        return self.population.reset_weaker_half()

    def audit_original_evidence(self, rows, *, metric, logical_run_id, evaluator_version, evaluation_context):
        """Check every retained candidate against authenticated main-lane rows."""
        from core.funsearch_public_evidence import verify_selected_projections
        candidates = self.population.checkpoint_state()['candidates']
        if not candidates:
            return True
        projections = {candidate: {'candidate_id': candidate, **record,
                       'evidence_ref': self._evidence_refs[candidate]}
                       for candidate, record in candidates.items()}
        return verify_selected_projections(rows, projections, set(candidates), case_ids=self._config['case_ids'],
            metric=metric, logical_run_id=logical_run_id, evaluator_version=evaluator_version,
            evaluation_context=evaluation_context)

    def checkpoint_state(self):
        return {'schema_version': 1, 'base': super().checkpoint_state(),
                'population': self.population.checkpoint_state(),
                'evidence_refs': dict(self._evidence_refs), 'pending': self.pending_selection()}

    def restore_state(self, state):
        if (type(state) is not dict or set(state) != {'schema_version', 'base', 'population', 'evidence_refs', 'pending'}
                or type(state['schema_version']) is not int or state['schema_version'] != 1
                or type(state['evidence_refs']) is not dict):
            raise ValueError('invalid FunSearch policy checkpoint')
        population = FunSearchPopulation.from_checkpoint(state['population'])
        frozen = population.checkpoint_state()
        if payload_digest(frozen['config']) != payload_digest(self._config):
            raise ValueError('FunSearch policy configuration differs')
        refs = state['evidence_refs']
        if set(refs) != set(frozen['candidates']) or any(type(ref) is not str or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', ref) for ref in refs.values()):
            raise ValueError('FunSearch evidence coverage differs')
        pending = state['pending']
        if pending is not None:
            if type(pending) is not dict or set(pending) != {'receipt', 'before', 'after'}:
                raise ValueError('invalid pending FunSearch selection')
            try:
                eligible = set(pending['receipt']['eligible'])
                verify_selection(pending['receipt'], pending['before'], pending['after'],
                                 eligible=eligible, max_parents=2)
            except (KeyError, TypeError) as exc:
                raise ValueError('invalid pending FunSearch selection') from exc
            if payload_digest(pending['after']) != payload_digest(frozen):
                raise ValueError('pending selection differs from population state')
        super().restore_state(state['base'])
        self.population, self._evidence_refs, self._pending = population, dict(refs), copy.deepcopy(pending)
