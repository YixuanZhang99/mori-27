"""Driver hooks for one population DAG, governed selection and M9 outcomes."""
from __future__ import annotations

import copy

from dataclasses import asdict

from core.composition.population import CrossoverOperator, PopulationPolicy
from core.composition.budget import _empty_state
from core.composition.evaluation import encode_evidence, public_projection
from core.executor.types import EvalRequest, EvalStatus
from core.frontier.population import PopulationFrontier
from core.frontier.research import ResearchFrontier
from core.policy.types import MutationOp, StateMutation
from core.state import _jsonable

_UNSET = object()


class PopulationRuntime:
    def _preflight_population(self):
        population = isinstance(self.frontier, PopulationFrontier)
        policy = self.parts['policy']
        if isinstance(policy, PopulationPolicy):
            if not population or self.frontier.capacity < 2:
                raise ValueError('population policy requires a population frontier with capacity >= 2')
            if [spec.name for spec in self.assembly.operators] != ['draft', 'crossover'] \
                    or not isinstance(self.parts['operators'][1], CrossoverOperator):
                raise ValueError('population policy requires registered operators ordered as draft, crossover')
        for operator in self.parts['operators']:
            if isinstance(operator, CrossoverOperator) and operator.metric != self.frontier.metric:
                raise ValueError('crossover objective differs from development exploration')
        if population and self.hierarchical:
            requests = [asdict(EvalRequest(**value)) for value in self.budget.options['fidelity_rungs']]
            if any(request != requests[0] for request in requests[1:]):
                raise ValueError('population elite retention requires one comparable development request')

    def _restore_frontier_snapshot(self, raw, *, incumbent=_UNSET, proposals=None, evidence=None):
        if type(self.frontier) is PopulationFrontier:
            restored = PopulationFrontier.restore(raw)
            if restored._config() != self.frontier._config():
                raise ValueError('population checkpoint configuration differs from the assembly')
            if incumbent is not _UNSET:
                self._validate_population_restore(restored, incumbent, proposals, evidence)
            return restored
        if type(self.frontier) is not ResearchFrontier:
            # Preserve the earlier fresh-run behavior for custom tree views;
            # their checkpoint restore contract remains explicitly unsupported.
            if incumbent is _UNSET and isinstance(self.frontier, ResearchFrontier) \
                    and not isinstance(self.frontier, PopulationFrontier):
                return ResearchFrontier.restore(raw)
            raise ValueError('configured frontier does not implement portable restore')
        return ResearchFrontier.restore(raw)

    def _validate_population_restore(self, restored, incumbent, proposals, evidence):
        # The checkpoint and its own hashes are not authority. Rebuild the
        # bounded member view from the durable evidence, decision, mutation and
        # sampling transcript, including the budget pool at each parent draw.
        rows = list(self.store.read())
        measured_rows, decisions = {}, {}
        for row in rows:
            if row['kind'] == 'composed_evidence':
                payload = row['payload']
                identifier = payload['proposal']['candidate']['id']
                if identifier in measured_rows:
                    raise ValueError('population durable proposal identity is duplicated')
                measured_rows[identifier] = payload
            elif row['kind'] == 'composed_decision':
                payload = row['payload']
                identifier = payload['candidate_id']
                if identifier in decisions:
                    raise ValueError('population durable M9 decision is duplicated')
                decisions[identifier] = payload
        if restored.protected_id != incumbent or set(restored.nodes) != set(proposals or {}) \
                or set(restored.nodes) != set(evidence or {}) or set(restored.nodes) != set(measured_rows) \
                or set(restored.nodes) != set(decisions):
            raise ValueError('population checkpoint differs from durable candidate or incumbent identities')
        for identifier, proposal in proposals.items():
            actual = measured_rows[identifier]
            if _jsonable(proposal) != actual['proposal'] \
                    or encode_evidence(evidence[identifier])['evidence'] != actual['evidence']:
                raise ValueError('population checkpoint proposal or evidence differs from durable execution')
        authority = PopulationFrontier(**self.frontier._config())
        physical = copy.copy(self.budget) if self.hierarchical else None
        if physical is not None:
            physical._data = _empty_state()
        current_cycle, current_attempt, draws, observed, finalized = None, -1, {}, set(), {}
        completed_attempts, aborted_attempts = set(), set()

        def direction(identifier, visiting=frozenset()):
            if identifier in visiting or identifier not in proposals:
                raise ValueError('population durable candidate genealogy is invalid')
            parents = proposals[identifier].candidate.parents
            return direction(parents[0], visiting | {identifier}) if parents else identifier

        for row in rows:
            kind, value = row['kind'], row['payload']
            if kind == 'hierarchical_budget' and physical is not None:
                physical._reduce(physical._data, value['event'], value['data'])
            elif kind == 'composed_cycle_started':
                current_cycle = value['cycle']
                current_attempt += 1
            elif kind == 'composed_cycle_aborted':
                if value['cycle'] != current_cycle:
                    raise ValueError('population cycle abort has no matching active attempt')
                aborted_attempts.add(current_attempt)
            elif kind == 'population_sampling_committed':
                if current_cycle is None or current_attempt in draws \
                        or current_attempt in completed_attempts | aborted_attempts or type(value) is not dict \
                        or set(value) != {'receipts', 'rng_state'} or not value['receipts']:
                    raise ValueError('population sampling transcript has no unique cycle binding')
                allowed = {identifier for identifier in authority.eligible_parent_ids()
                           if physical is None or physical.should_continue(direction(identifier))}
                parents = value['receipts'][-1]['selected']
                authority.commit_selection(parents, value['receipts'], allowed_ids=allowed)
                if authority.rng_state != value['rng_state']:
                    raise ValueError('population RNG journal differs from recomputed sampling receipts')
                draws[current_attempt] = parents
            elif kind == 'composed_evidence':
                candidate = proposals[value['proposal']['candidate']['id']].candidate
                if candidate.created_cycle != current_cycle or candidate.parents != draws.get(current_attempt, []):
                    raise ValueError('population proposal parents differ from its committed sampling receipt')
                observed.add(candidate.id)
                completed_attempts.add(current_attempt)
            elif kind == 'population_finalized':
                identifier = value['candidate_id']
                if identifier in finalized:
                    raise ValueError('population finalization receipt is duplicated')
                finalized[identifier] = value
            elif kind == 'state_mutation':
                op, target, fields = value['op'], value['target'], value['fields']
                if op in {MutationOp.WRITE_MEMORY.value, MutationOp.PROMOTE_MEMORY.value}:
                    continue
                if target not in observed:
                    raise ValueError('population mutation precedes its actual execution evidence')
                public = public_projection(evidence[target])
                if op == MutationOp.ADD_NODE.value:
                    if fields != {'candidate': _jsonable(proposals[target].candidate), 'evidence': _jsonable(public)}:
                        raise ValueError('population materialization differs from durable evidence')
                    authority.add(proposals[target].candidate, public)
                elif op == MutationOp.UPDATE_NODE.value:
                    mutation = StateMutation(MutationOp.UPDATE_NODE, target, fields, value['rationale'])
                    self._validate_mutations([mutation], public)
                    authority.update_node(target, fields)
                elif op == MutationOp.POPULATION_FINALIZE.value:
                    decision = decisions[target]
                    expected = {'admitted': decision['decision']['admit'], 'reason': decision['decision']['reason'],
                        'selected_id': target if decision['decision']['admit'] else authority.protected_id,
                        'decision_ref': decision['receipt_id']}
                    if fields != expected:
                        raise ValueError('population outcome differs from its durable M9 receipt')
                    receipt = authority.finalize(target, **fields)
                    if receipt != finalized.get(target) or receipt != value['result']:
                        raise ValueError('population membership differs from authoritative finalization')
                else:
                    raise ValueError('population transcript contains an unauthorized state mutation')
        if set(draws) - completed_attempts - aborted_attempts:
            raise ValueError('population draw has neither an executed proposal nor a durable cycle abort')
        if authority.protected_id != incumbent or authority.checkpoint() != restored.checkpoint():
            raise ValueError('population checkpoint differs from reconstructed authoritative state')

    def _commit_population_selection(self, view, parents, eligible_parents):
        if not isinstance(self.frontier, PopulationFrontier):
            return
        if type(view) is not PopulationFrontier:
            raise ValueError('population policy must select from its detached population view')
        allowed = set(eligible_parents).intersection(self.frontier.eligible_parent_ids())
        if any(identifier not in allowed for identifier in parents):
            raise ValueError('policy selected a candidate outside the retained population')
        self.frontier.commit_selection(parents, view.sampling_receipts, allowed_ids=allowed)

    def _finalize_frontier_admission(self, candidate_id, decision, decision_ref):
        if isinstance(self.frontier, PopulationFrontier):
            self.applier.apply(StateMutation(MutationOp.POPULATION_FINALIZE, candidate_id,
                {'admitted': decision.admit, 'reason': decision.reason,
                 'selected_id': candidate_id if decision.admit else self.incumbent,
                 'decision_ref': decision_ref}, 'apply M9 outcome and deterministic population retention'))
        else:
            self.applier.apply(StateMutation(MutationOp.MERGE if decision.admit else MutationOp.PRUNE,
                candidate_id, {} if decision.admit else {'reason': decision.reason}, decision.reason))

    def _population_state(self):
        if not isinstance(self.frontier, PopulationFrontier):
            return None
        return {'members': list(self.frontier.member_ids), 'protected_id': self.frontier.protected_id,
                'capacity': self.frontier.capacity, 'retention': self.frontier.retention,
                'selection': self.frontier.selection, 'rng_state': self.frontier.rng_state,
                'nodes': len(self.frontier.nodes)}
