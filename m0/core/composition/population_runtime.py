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
        from core.composition.aide_policy import AIDEPolicy
        if type(policy) is AIDEPolicy:
            from core.composition.construction_recipes import RecipeOperator
            from core.composition.defaults import MetricAdmission
            operators = self.parts['operators']
            if not self.construction_enabled or type(self.frontier) is not ResearchFrontier \
                    or not self.frontier.retain_rejected or not self.hierarchical \
                    or [s.name for s in self.assembly.operators] != ['draft', 'debug', 'improve'] \
                    or any(type(o) is not RecipeOperator for o in operators) \
                    or operators[1].max_debug_depth != policy.config['max_debug_depth'] \
                    or not isinstance(self.parts['admission'], MetricAdmission) \
                    or self.parts['admission'].margin != 0:
                raise ValueError('AIDE requires retained tree, matching repair depth, M7 recipes and validation-best admission')
            memory = self.assembly.memory.options
            if memory.get('context_scope', 'ancestors') != 'run' or memory.get('levels') != ['L1'] \
                    or memory.get('trust_floor', 'gated') != 'ungated' \
                    or not memory.get('include_negative', True) or memory.get('include_imported', False) \
                    or memory.get('imports') or self.parts.get('knowledge') is not None \
                    or 'memory' not in self.assembly.execution.spec.context_projection:
                raise ValueError('AIDE requires run-local L1 journal retrieval without imports or knowledge')
        if isinstance(policy, PopulationPolicy):
            from core.composition.construction_recipes import RecipeOperator
            crossover = self.parts['operators'][1] if len(self.parts['operators']) > 1 else None
            supported = isinstance(crossover, CrossoverOperator) or (self.construction_enabled and
                isinstance(crossover, RecipeOperator) and crossover.kind == 'crossover')
            if not population or self.frontier.capacity < 2:
                raise ValueError('population policy requires a population frontier with capacity >= 2')
            if [spec.name for spec in self.assembly.operators] != ['draft', 'crossover'] \
                    or not supported:
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
        restored = ResearchFrontier.restore(raw)
        if restored.retain_rejected != self.frontier.retain_rejected:
            raise ValueError('tree retention configuration differs from the assembly')
        return restored

    def _validate_aide_restore(self, restored, incumbent, proposals, evidence):
        """Rebuild tree decisions and RNG from original events, not saved hashes."""
        from core.composition.aide_policy import AIDEPolicy
        from core.composition.configured_execution import ConfiguredExecution
        from core.composition.evaluation import comparison_projection
        import json
        policy = self.parts['policy']
        if type(policy) is not AIDEPolicy:
            return
        authority = ResearchFrontier(metric=self.frontier.metric, direction=self.frontier.direction,
                                     retain_rejected=True)
        chooser = AIDEPolicy(self.memory.context, **policy.config)
        physical = copy.copy(self.budget)
        physical._data = _empty_state()
        seen, chosen, best, cycle, pending = set(), None, None, None, None
        journals = {}

        def direction(identifier):
            ancestors = set()
            while proposals[identifier].candidate.parents:
                if identifier in ancestors:
                    raise ValueError('AIDE history contains cyclic ancestry')
                ancestors.add(identifier)
                identifier = proposals[identifier].candidate.parents[0]
            return identifier

        for row in self.store.read():
            kind, value = row['kind'], row['payload']
            if kind == 'hierarchical_budget':
                physical._reduce(physical._data, value['event'], value['data'])
            elif kind == 'composed_cycle_started':
                if pending is not None:
                    raise ValueError('AIDE history has an unfinished selection')
                cycle, chosen = value['cycle'], None
            elif kind == 'aide_selection':
                if chosen is not None or cycle is None:
                    raise ValueError('AIDE selection lacks a unique cycle')
                view = ConfiguredExecution.selection_view(ResearchFrontier.restore(authority.checkpoint()))
                compact = chooser._remember({'task': self.task, 'cycle': cycle,
                    'frontier': json.loads(view.view('json')),
                    'operators': [s.name for s in self.assembly.operators]})
                chooser._strategy = {'node_count': compact['node_count']}
                for identifier in seen:
                    if not proposals[identifier].artifact.strip() or not physical.should_continue(direction(identifier)):
                        view.nodes[identifier].status = 'pruned'
                chosen = chooser.choose(view)
                if value != {'candidate_id': value.get('candidate_id'), 'cycle': cycle,
                             'parents': chosen.parents, 'operator': chosen.operator,
                             'rng_state': chooser.checkpoint_state()['rng_state']}:
                    raise ValueError('AIDE selection differs from original tree and budget')
                pending = value['candidate_id']
            elif kind == 'composed_cycle_aborted':
                pending = None
            elif kind == 'composed_evidence':
                identifier = value['proposal']['candidate']['id']
                if identifier not in proposals or identifier in seen or identifier != pending:
                    raise ValueError('AIDE evidence lacks its original selection')
                proposal, measured = proposals[identifier], evidence[identifier]
                if value['proposal'] != _jsonable(proposal) or value['evidence'] != encode_evidence(measured)['evidence'] \
                        or proposal.candidate.parents != chosen.parents or proposal.candidate.operator != chosen.operator \
                        or proposal.candidate.created_cycle != cycle:
                    raise ValueError('AIDE checkpoint differs from original evidence or lineage')
                authority.add(proposal.candidate, public_projection(measured))
                entry = self.memory.aide_journal_entry(proposal, public_projection(measured),
                    value['evidence_ref'], cycle=cycle,
                    materialization=self.construction.materializations.get(identifier))
                journals[entry.id] = entry
                node = authority.nodes[identifier]
                node.result.update(memory_refs=[], evidence_ref=value['evidence_ref'],
                                   context_pack_ref=proposal.candidate.context_pack_ref)
                node.insight = None
                seen.add(identifier)
            elif kind == 'composed_decision':
                identifier = value['candidate_id']
                if identifier != pending or identifier not in seen:
                    raise ValueError('AIDE decision precedes its evidence')
                decision = self.parts['admission'].judge(comparison_projection(evidence[identifier]),
                    comparison_projection(evidence[best]) if best else None)
                if value['incumbent'] != best or value['decision'] != asdict(decision):
                    raise ValueError('AIDE decision differs from validation-best evidence')
                if decision.admit:
                    authority.nodes[identifier].status = 'merged'
                    best = identifier
                pending = None
        if set(journals) != set(self.memory.entries):
            raise ValueError('AIDE journal coverage differs from original execution')
        for identifier, expected in journals.items():
            actual = self.memory.entries[identifier]
            if actual.payload != expected.payload or actual.provenance != expected.provenance \
                    or actual.context != expected.context or actual.scope != 'run' or actual.level != 'L1' \
                    or actual.state != 'active' or actual.time.created_at != expected.time.created_at \
                    or actual.time.superseded_by is not None or actual.time.ttl is not None:
                raise ValueError('AIDE journal facts differ from original execution')
        if pending is not None or seen != set(proposals) or best != incumbent \
                or authority.checkpoint() != restored.checkpoint() \
                or chooser.checkpoint_state() != policy.checkpoint_state() \
                or self.parts['policy_absorber'].checkpoint_state() != AIDEPolicy(self.memory.context, **policy.config).checkpoint_state():
            raise ValueError('AIDE checkpoint tree, incumbent or policy RNG/history differs from original events')

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
        from core.composition.gepa_policy import GEPAInstancePolicy
        from core.frontier.gepa import InstanceFrontier
        policy = self.parts['policy']
        instance_draws = InstanceFrontier(list(policy.items), seed=policy.seed) if type(policy) is GEPAInstancePolicy else None
        from core.composition.funsearch_policy import FunSearchPolicy
        from core.composition.funsearch_history import FunSearchHistory
        island_history = FunSearchHistory(policy._config) if type(policy) is FunSearchPolicy else None

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
            elif kind == 'gepa_public_verdicts' and instance_draws is not None:
                instance_draws.offer(value['candidate_id'], value['verdicts'])
            elif kind == 'gepa_parent_selection' and instance_draws is not None:
                allowed = {identifier for identifier in authority.eligible_parent_ids()
                           if physical is None or physical.should_continue(direction(identifier))}
                selected = [instance_draws.select(eligible=allowed)] if allowed else []
                if current_cycle is None or current_attempt in draws or value != {
                        'eligible': sorted(allowed), 'selected': selected}:
                    raise ValueError('GEPA population parent draw differs from durable instance evidence')
                draws[current_attempt] = selected
            elif kind.startswith('funsearch_') and island_history is not None:
                if kind == 'funsearch_selection':
                    if current_cycle is None or current_attempt in draws or current_attempt in completed_attempts | aborted_attempts:
                        raise ValueError('FunSearch population draw has no unique cycle binding')
                    allowed = {identifier for identifier in authority.eligible_parent_ids()
                               if physical is None or physical.should_continue(direction(identifier))}
                    draws[current_attempt] = island_history.consume(kind, value, eligible=allowed)
                else:
                    island_history.consume(kind, value)
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
        from core.composition.gepa_policy import GEPAInstancePolicy
        from core.composition.funsearch_policy import FunSearchPolicy
        if type(self.parts['policy']) is FunSearchPolicy:
            # The coordinator already durably recorded this island draw. Its
            # sampler owns the RNG; the frontier owns membership and budgets.
            self.funsearch._audit()
            pending = self.parts['policy'].pending_selection()
            if pending is None:
                if parents or allowed:
                    raise ValueError('FunSearch population parents lack an original draw')
            elif pending['receipt']['eligible'] != sorted(allowed) or pending['receipt']['ancestry'] != parents:
                raise ValueError('FunSearch population eligible parents differ from the original draw')
            return
        if type(self.parts['policy']) is GEPAInstancePolicy:
            from core.frontier.gepa import InstanceFrontier
            policy = self.parts['policy']
            authority = InstanceFrontier(list(policy.items), seed=policy.seed)
            for row in self.store.read():
                value = row['payload']
                if row['kind'] == 'gepa_public_verdicts':
                    authority.offer(value['candidate_id'], value['verdicts'])
                elif row['kind'] == 'gepa_parent_selection' and value['eligible']:
                    if [authority.select(eligible=set(value['eligible']))] != value['selected']:
                        raise ValueError('GEPA parent selection history differs')
            selected = [authority.select(eligible=allowed)] if allowed else []
            if selected != parents or authority.checkpoint_state() != policy.instance_frontier.checkpoint_state():
                raise ValueError('GEPA parent draw differs from authoritative instance evidence')
            self.store.append('gepa_parent_selection', {'eligible': sorted(allowed), 'selected': selected})
        else:
            self.frontier.commit_selection(parents, view.sampling_receipts, allowed_ids=allowed)

    def _finalize_frontier_admission(self, candidate_id, decision, decision_ref):
        if isinstance(self.frontier, PopulationFrontier):
            self.applier.apply(StateMutation(MutationOp.POPULATION_FINALIZE, candidate_id,
                {'admitted': decision.admit, 'reason': decision.reason,
                 'selected_id': candidate_id if decision.admit else self.incumbent,
                 'decision_ref': decision_ref}, 'apply M9 outcome and deterministic population retention'))
        elif decision.admit or not self.frontier.retain_rejected:
            self.applier.apply(StateMutation(MutationOp.MERGE if decision.admit else MutationOp.PRUNE,
                candidate_id, {} if decision.admit else {'reason': decision.reason}, decision.reason))

    def _population_state(self):
        if not isinstance(self.frontier, PopulationFrontier):
            return None
        return {'members': list(self.frontier.member_ids), 'protected_id': self.frontier.protected_id,
                'capacity': self.frontier.capacity, 'retention': self.frontier.retention,
                'selection': self.frontier.selection, 'rng_state': self.frontier.rng_state,
                'nodes': len(self.frontier.nodes)}
