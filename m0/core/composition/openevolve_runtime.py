"""Journal-bound OpenEvolve coordination; public runtime wiring is pending."""
from __future__ import annotations

import copy
from dataclasses import asdict
import math
import json

from core.composition.contracts import OperatorFailure, Proposal
from core.composition.construction import decode_construction_outcome
from core.composition.evaluation import binding_for, decode_evidence, encode_evidence
from core.composition.execution import Materialization
from core.composition.openevolve_policy import OpenEvolvePolicy
from core.composition.openevolve_prompt import build_bound_prompt
from core.composition.recovery import ContinuationStore
from core.executor.types import Candidate, CostVec, EvalRequest, EvalStatus
from core.x1.checkpoint import payload_digest


def is_openevolve_domain(domain):
    """Validate the trusted domain adapter without importing the benchmark layer."""
    return (getattr(domain, 'openevolve_binding', None) == {
                'schema_version': 1, 'kind': 'openevolve-circle-packing-adapted-v1'}
            and getattr(domain, 'evaluator_version', None) == 'openevolve-circle-packing-adapted-v1'
            and all(callable(getattr(domain, name, None)) for name in
                    ('validate_context', '_identity', '_validate_record'))
            and type(getattr(domain, 'evaluation_contexts', None)) is dict
            and set(domain.evaluation_contexts) == {'dev', 'final_audit'})


class OpenEvolveCoordinator:
    """Bind serial host decisions to original main-lane development evidence."""

    def __init__(self, policy, store, *, logical_run_id, domain, require_materializations=False, budget=None):
        if not isinstance(policy, OpenEvolvePolicy) or not isinstance(store, ContinuationStore) \
                or not is_openevolve_domain(domain) or type(logical_run_id) is not str or not logical_run_id:
            raise ValueError('OpenEvolve requires its policy, durable journal and frozen circle domain')
        if type(require_materializations) is not bool:
            raise ValueError('materialization audit flag must be boolean')
        self.policy, self.store, self.logical_run_id, self.domain = policy, store, logical_run_id, domain
        if require_materializations and budget is None:
            raise ValueError('production coordinator requires the original hierarchical budget')
        self.require_materializations = require_materializations
        self.budget = budget

    def _rows(self, kind):
        return [row['payload'] for row in self.store.read(kind)]

    def _projection(self, candidate_id):
        rows = [row for row in self._rows('composed_evidence')
                if row.get('proposal', {}).get('candidate', {}).get('id') == candidate_id]
        if len(rows) != 1:
            raise ValueError('candidate requires unique original development evidence')
        row = rows[0]
        if set(row) != {'cycle', 'proposal', 'evidence_ref', 'evidence'} \
                or type(row['cycle']) is not int or row['cycle'] < 0:
            raise ValueError('invalid original development event')
        payload = row['proposal']
        proposal = Proposal(Candidate(**payload['candidate']), payload['artifact'])
        evidence = decode_evidence({'schema_version': 1, 'evidence': row['evidence']})
        result, binding = evidence.eval_result, evidence.eval_result.contract.binding
        reference = 'sha256:' + payload_digest({'logical_run_id': self.logical_run_id,
                                                 'evidence': encode_evidence(evidence)})
        expected_binding = binding_for(proposal, EvalRequest(fidelity='dev', split_id='dev'),
            evaluator_version=self.domain.evaluator_version,
            evaluation_context=self.domain.evaluation_contexts['dev'])
        if evidence.candidate_id != candidate_id or binding != expected_binding or row['evidence_ref'] != reference:
            raise ValueError('candidate development evidence identity differs')
        data = result.contract.private.data
        if result.contract.binding_source == 'invocation':
            if proposal.artifact or result.status is not EvalStatus.FAILED_TO_RUN \
                    or result.metrics or result.cost != CostVec() or data:
                raise ValueError('invalid pre-evaluation construction failure evidence')
            return {'candidate_id': candidate_id, 'artifact': '', 'parents': proposal.candidate.parents,
                    'score': None, 'status': result.status.value, 'evidence_ref': reference, 'cycle': row['cycle']}
        identity = self.domain._identity(proposal)
        record = data.get('record')
        self.domain._validate_record(candidate_id, record)
        if record['identity'] != identity or result.status.value != record['status'] \
                or data.get('geometry_ref') != record['geometry_ref'] \
                or result.cost.eval_count != record['eval_count'] or result.cost.wall_seconds != record['wall_seconds']:
            raise ValueError('candidate original physical evidence differs')
        expected = {'dev/score': record['metrics']['combined_score']} if result.status is EvalStatus.OK else {}
        if result.metrics != expected:
            raise ValueError('candidate public score differs from original geometry')
        return {'candidate_id': candidate_id, 'artifact': proposal.artifact, 'parents': proposal.candidate.parents,
                'score': expected.get('dev/score'), 'status': result.status.value,
                'evidence_ref': reference, 'cycle': row['cycle']}

    def _reconstruct_plan(self, result, cycle):
        from core.composition.construction import ConstructionPlan, _json
        from core.composition.construction_recipes import DEFAULT_ROLES
        from core.composition.context import ContextPack
        from core.composition.contracts import ExecutionConfig
        starts = self._rows('run_start')
        contexts = [row for row in self._rows('composed_context') if row.get('cycle') == cycle]
        candidate = Candidate(**result['candidate'])
        if len(starts) != 1 or len(contexts) != 1:
            raise ValueError('original run or candidate context is missing')
        execution = ExecutionConfig.from_dict(starts[0]['manifest']['assembly']['execution'])
        context = ContextPack(_json(contexts[0]['context']))
        if contexts[0]['context_ref'] != context.ref or candidate.context_pack_ref != context.ref:
            raise ValueError('candidate context differs from original retrieval')
        parents = candidate.parents
        if not parents:
            recipe = {'kind': 'draft', 'task_desc': starts[0]['task_desc'],
                      'parent_artifacts': [], 'instructions': [], 'comparison': {}}
        elif len(parents) == 1:
            parent = self._projection(parents[0])
            events = self._rows('openevolve_host_event')
            selected = [(i, event['result']) for i, event in enumerate(events)
                        if event['kind'] == 'select' and event['candidate_id'] == candidate.id]
            prompt_rows = [row for row in self._rows('openevolve_prompt') if row['candidate_id'] == candidate.id]
            if len(selected) != 1 or len(prompt_rows) != 1 or prompt_rows[0]['evolution_round'] != cycle:
                raise ValueError('candidate construction lacks its original selection and prompt')
            index, selection = selected[0]
            prompt = build_bound_prompt(selection, events[:index + 1], self._rows('composed_evidence'),
                logical_run_id=self.logical_run_id, evaluator_version=self.domain.evaluator_version,
                evaluation_context=self.domain.evaluation_contexts['dev'], evolution_round=cycle)
            bound = {'system': prompt['system'], 'user': prompt['user'], 'input_ref': prompt['input_ref'],
                     'prompt_ref': prompt['prompt_ref'], 'selection_ref': 'sha256:' + payload_digest(selection)}
            instruction = json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            recipe = {'kind': 'reflective', 'task_desc': starts[0]['task_desc'],
                      'parent_artifacts': [{'candidate_id': parent['candidate_id'], 'artifact': parent['artifact']}],
                      'instructions': [instruction], 'comparison': {parent['candidate_id']: parent['score']}}
        else:
            raise ValueError('OpenEvolve mutation requires a single original parent')
        plan = ConstructionPlan.create(candidate, recipe, execution.spec, context, roles=DEFAULT_ROLES)
        if plan.ref != result['plan_ref']:
            raise ValueError('materialization plan differs from original host prompt and context')
        originals = [row for row in self._rows('openevolve_construction_plan')
                     if row.get('candidate_id') == candidate.id]
        if len(originals) != 1 or originals[0] != {'candidate_id': candidate.id,
                                                    'plan': plan.to_dict(), 'plan_ref': plan.ref}:
            raise ValueError('original OpenEvolve construction plan differs')
        return plan

    def _audit_materialization(self, candidate_id, cycle):
        if not self.require_materializations:
            return
        rows = [row for row in self._rows('composed_evidence')
                if row['proposal']['candidate']['id'] == candidate_id]
        matches = [row for row in self._rows('materialization_completed')
                   if row['construction_result']['candidate']['id'] == candidate_id]
        if len(rows) != 1 or len(matches) != 1:
            raise ValueError('candidate lacks its unique original M7 materialization')
        data = matches[0]
        item = Materialization.from_dict(data)
        operation = data['identity']['operation']
        if payload_digest(asdict(item.proposal)) != payload_digest(rows[0]['proposal']) \
                or operation['run_id'] != self.logical_run_id or operation['cycle'] != cycle \
                or operation['lane'] != 'main' or operation['slot_id'] is not None \
                or data['identity']['materializer']['kind'] != 'openevolve_diff_materializer_v1':
            raise ValueError('M7 materialization differs from original candidate or run')
        starts = [row for row in self._rows('construction_started') if row['identity'] == data['identity']]
        outcomes = [row for row in self._rows('construction_outcome') if row['identity'] == data['identity']]
        if len(starts) != 1 or len(outcomes) != 1 or outcomes[0]['outcome'] != {
                'kind': 'returned', 'result': data['construction_result']}:
            raise ValueError('M7 materialization lacks its original start and outcome')
        result = data['construction_result']
        plan = self._reconstruct_plan(result, cycle)
        calls = [row for row in self._rows('composed_provider_started')
                 if row.get('invocation', {}).get('intent_id') == operation['intent_id']]
        if not result['candidate']['parents']:
            import hashlib
            if 'sha256:' + hashlib.sha256(result['artifact'].encode('utf-8')).hexdigest() != \
                    data['identity']['materializer']['configuration']['seed_program_ref']:
                raise ValueError('seed artifact differs from its pinned construction source')
            if calls or result['cost']['tokens_in'] != 0:
                raise ValueError('pinned seed must not consume provider calls')
            return
        if len(result['candidate']['parents']) != 1 or len(calls) != len(result['attempts']):
            raise ValueError('M7 patch attempts differ from original provider calls')
        from core.composition.construction import _json
        from core.composition.openevolve_registration import constructor_factory
        decoder = constructor_factory(None, {})
        plan_value = plan.to_dict()
        feedback = []
        completed = self._rows('composed_provider_completed')
        used = 0
        for index, (started, attempt) in enumerate(zip(calls, result['attempts'])):
            if started['invocation'].get('ordinal') != index:
                raise ValueError('provider call ordinal differs from patch attempts')
            request = decoder.build_request(plan_value, hypothesis=result['initial_hypothesis'],
                                            attempt=index + 1, feedback=feedback)
            request_digest = payload_digest({'args': (_json(request),), 'kwargs': {}})
            if started.get('request_sha256') != request_digest:
                raise ValueError('original provider request differs from the bound host prompt')
            matches = [row for row in completed if row.get('binding') == started.get('binding')]
            if len(matches) != 1 or type(matches[0].get('tokens')) is not int or matches[0]['tokens'] < 0:
                raise ValueError('patch attempt lacks unique original provider completion')
            used += matches[0]['tokens']
            if attempt['known_tokens'] != used:
                raise ValueError('patch usage differs from original provider completions')
            try:
                decoded = decoder.decode_output(matches[0]['result'], plan_value)
            except (ValueError, TypeError) as error:
                if attempt['status'] != 'invalid_output' or attempt['feedback'] != [str(error)]:
                    raise ValueError('original provider diff differs from recorded failed attempt') from None
            else:
                if attempt['status'] != 'complete' or decoded['artifact'] != result['artifact'] \
                        or decoded['hypothesis'] != result['effective_hypothesis']:
                    raise ValueError('materialized program differs from original provider diff')
            feedback = attempt['feedback']
        if used != result['cost']['tokens_in']:
            raise ValueError('materialization cost differs from original provider usage')

    def _audit_failed_construction(self, candidate_id, cycle):
        if not self.require_materializations:
            return
        rows = [row for row in self._rows('composed_evidence')
                if row['proposal']['candidate']['id'] == candidate_id]
        if len(rows) != 1:
            raise ValueError('failed candidate lacks unique original evidence')
        proposal = rows[0]['proposal']
        if proposal['artifact']:
            self._audit_materialization(candidate_id, cycle)
            return
        outcomes = [row for row in self._rows('construction_outcome')
                    if row['identity']['operation']['cycle'] == cycle
                    and row['identity']['operation']['run_id'] == self.logical_run_id
                    and row['identity']['operation']['lane'] == 'main'
                    and row['identity']['operation']['phase'] == 'operator']
        if len(outcomes) != 1:
            raise ValueError('failed candidate lacks original M7 construction outcome')
        terminal = outcomes[0]
        identity = terminal['identity']
        failure = decode_construction_outcome(terminal, identity)
        if not isinstance(failure, OperatorFailure) or asdict(failure.cost) != proposal['cost'] \
                or list(failure.measured_cost_units) != proposal['measured_cost_units'] \
                or identity['materializer']['kind'] != 'openevolve_diff_materializer_v1':
            raise ValueError('failed candidate cost differs from original construction outcome')
        starts = [row for row in self._rows('construction_started') if row['identity'] == identity]
        if len(starts) != 1:
            raise ValueError('failed construction lacks its original start')
        operation = identity['operation']
        calls = [row for row in self._rows('composed_provider_started')
                 if row.get('invocation', {}).get('intent_id') == operation['intent_id']]
        completions = self._rows('composed_provider_completed')
        from core.composition.construction import _json
        from core.composition.openevolve_registration import constructor_factory
        decoder = constructor_factory(None, {})
        plans = [row for row in self._rows('openevolve_construction_plan')
                 if row.get('candidate_id') == candidate_id]
        if len(plans) != 1 or type(plans[0].get('plan')) is not dict:
            raise ValueError('failed candidate lacks its original construction plan')
        planned_candidate = plans[0]['plan'].get('candidate')
        if type(planned_candidate) is not dict or {**planned_candidate, 'hypothesis': proposal['candidate']['hypothesis']} != proposal['candidate']:
            raise ValueError('failed candidate differs from its original construction plan')
        plan = self._reconstruct_plan({'candidate': planned_candidate,
                                       'plan_ref': identity['plan_ref']}, cycle)
        plan_value = plan.to_dict()
        if len(calls) > decoder.max_attempts:
            raise ValueError('failed construction exceeded its patch attempt limit')
        feedback = []
        used = 0
        for index, started in enumerate(calls):
            if started['invocation'].get('ordinal') != index:
                raise ValueError('failed provider call ordinal differs')
            request = decoder.build_request(plan_value, hypothesis=planned_candidate['hypothesis'],
                                            attempt=index + 1, feedback=feedback)
            if started.get('request_sha256') != payload_digest({'args': (_json(request),), 'kwargs': {}}):
                raise ValueError('failed provider request differs from bound host prompt')
            matches = [row for row in completions if row.get('binding') == started.get('binding')]
            if len(matches) != 1 or type(matches[0].get('tokens')) is not int or matches[0]['tokens'] < 0:
                raise ValueError('failed construction lacks measured provider completion')
            used += matches[0]['tokens']
            outcome = matches[0].get('outcome')
            if outcome in {'failed', 'budget_exhausted'}:
                if index != len(calls) - 1:
                    raise ValueError('failed provider invocation cannot be followed by another attempt')
                continue
            try:
                decoder.decode_output(matches[0]['result'], plan_value)
            except (TypeError, ValueError, RecursionError) as error:
                feedback = [str(error)]
            else:
                raise ValueError('successful original patch cannot yield an exhausted failure')
        if used != failure.cost.tokens_in:
            raise ValueError('failed construction cost differs from original provider usage')

    def _audit_budget_scopes(self):
        if self.budget is None:
            return
        from core.composition.budget import HierarchicalBudget
        if not isinstance(self.budget, HierarchicalBudget):
            raise ValueError('OpenEvolve requires the original hierarchical budget')
        rows = list(self.store.read())
        class Prefix:
            def __init__(self, values):
                self.values = values
            def read(self, kind=None):
                return (row for row in self.values if kind is None or row['kind'] == kind)
        governed = self.budget._governed
        governance = copy.deepcopy(governed.config) if governed is not None else None
        for index, row in enumerate(rows):
            if row['kind'] != 'openevolve_selection_scope':
                continue
            budget = HierarchicalBudget(self.budget.options, self.budget.stamp, Prefix(rows[:index]),
                                        governance=governance)
            budget.restore_from_journal()
            summary = budget.main_account_summary() if governed is not None else budget.account_summary()
            if row['payload'].get('budget_ref') != 'sha256:' + payload_digest(summary):
                raise ValueError('selection budget scope differs from original budget events')
            proposals, original_evidence, nodes = {}, {}, {}
            for original in rows[:index]:
                payload = original['payload']
                if original['kind'] == 'composed_evidence':
                    proposal = payload['proposal']
                    candidate = proposal['candidate']['id']
                    if candidate in proposals:
                        raise ValueError('duplicate candidate in original frontier history')
                    proposals[candidate] = proposal
                    original_evidence[candidate] = payload['evidence']
                elif original['kind'] == 'state_mutation' and payload.get('op') == 'add_node':
                    candidate = payload['target']
                    if candidate not in proposals or candidate in nodes:
                        raise ValueError('frontier node lacks unique original proposal')
                    declared = payload['fields']['candidate']
                    if declared != proposals[candidate]['candidate']:
                        raise ValueError('frontier candidate differs from original proposal')
                    evidence = payload['fields']['evidence']['eval_result']
                    source = original_evidence[candidate]['eval_result']
                    if evidence['status'] != source['status'] or evidence['metrics'] != source['metrics']:
                        raise ValueError('frontier score differs from original evaluation evidence')
                    score = evidence['metrics'].get('dev/score') if evidence['status'] == 'ok' else None
                    nodes[candidate] = {'id': candidate, 'status': 'done', 'eval_status': evidence['status'],
                                        'score': float(score) if score is not None else None}
                elif original['kind'] == 'state_mutation' and payload.get('op') in {'merge', 'prune'}:
                    candidate = payload['target']
                    if candidate not in nodes:
                        raise ValueError('frontier disposition lacks original node')
                    nodes[candidate]['status'] = 'merged' if payload['op'] == 'merge' else 'pruned'
            def root(candidate, visiting):
                if candidate in visiting or candidate not in proposals:
                    raise ValueError('frontier ancestry lacks original proposal')
                parents = proposals[candidate]['candidate']['parents']
                return candidate if not parents else root(parents[0], visiting | {candidate})
            for candidate, node in nodes.items():
                if not proposals[candidate]['artifact'].strip() or not budget.should_continue(root(candidate, set())):
                    node['status'] = 'pruned'
            scope_nodes = [nodes[key] for key in sorted(nodes)]
            if row['payload'].get('frontier_ref') != 'sha256:' + payload_digest(scope_nodes):
                raise ValueError('selection frontier differs from original execution events')
            eligible = [node['id'] for node in scope_nodes if node['status'] in {'done', 'merged'}
                        and node['eval_status'] == 'ok' and node['score'] is not None]
            if row['payload'].get('eligible_ids') != eligible:
                raise ValueError('eligible parents differ from original frontier and budget')

    def _audit(self):
        self._audit_budget_scopes()
        host_events = self._rows('openevolve_host_event')
        self.policy.adapter.restore_state(self.policy.adapter.checkpoint_state(), host_events)
        evidence_rows = self._rows('composed_evidence')
        prompt_rows = self._rows('openevolve_prompt')
        scope_rows = self._rows('openevolve_selection_scope')
        prompts, selections, scopes, seen = {}, {}, {}, set()
        for row in scope_rows:
            if type(row) is not dict or set(row) != {'candidate_id', 'eligible_ids', 'budget_ref', 'frontier_ref'} \
                    or row['candidate_id'] in scopes \
                    or any(type(row[key]) is not str or len(row[key]) != 71 or not row[key].startswith('sha256:')
                           for key in ('budget_ref', 'frontier_ref')):
                raise ValueError('invalid original selection scope')
            scopes[row['candidate_id']] = row
        for row in prompt_rows:
            if type(row) is not dict or set(row) != {'candidate_id', 'evolution_round', 'selection_ref', 'input_ref', 'prompt_ref'} \
                    or row['candidate_id'] in prompts:
                raise ValueError('invalid or duplicate original prompt record')
            prompts[row['candidate_id']] = row
        for index, event in enumerate(host_events):
            args, candidate = event['args'], event['candidate_id']
            if event['kind'] == 'select':
                if candidate in selections or not set(args['eligible_ids']) <= seen \
                        or candidate not in scopes or scopes[candidate]['eligible_ids'] != args['eligible_ids']:
                    raise ValueError('selection differs from original eligible source scope')
                selections[candidate] = (event['result'], index)
                continue
            if event['kind'] == 'abandon':
                if candidate not in selections or candidate not in prompts:
                    raise ValueError('abandonment lacks original selection and prompt')
                item = self._projection(candidate)
                if item['status'] == 'ok' or item['parents'] != [selections[candidate][0]['source_candidate_id']]:
                    raise ValueError('abandonment differs from original failure evidence')
                self._audit_failed_construction(candidate, item['cycle'])
                continue
            if event['kind'] != 'register':
                raise ValueError('unsupported original host event')
            if candidate in seen:
                raise ValueError('duplicate original host registration')
            item = self._projection(candidate)
            selection = args['selection']
            expected_parents = [] if selection is None else [selection['source_candidate_id']]
            if item['status'] != 'ok' or args['artifact'] != item['artifact'] \
                    or args['metrics'] != {'combined_score': item['score']} \
                    or args['evidence_ref'] != item['evidence_ref'] or args['iteration'] != item['cycle'] \
                    or item['parents'] != expected_parents:
                raise ValueError('host registration differs from original execution evidence')
            if selection is not None and (candidate not in selections or candidate not in prompts
                    or selections[candidate][0] != selection):
                raise ValueError('host registration lacks original selected prompt')
            self._audit_materialization(candidate, item['cycle'])
            seen.add(candidate)
        if set(scopes) != set(selections):
            raise ValueError('selection scope journal coverage differs')
        for candidate, row in prompts.items():
            if candidate not in selections:
                raise ValueError('prompt lacks original host selection')
            selection, index = selections[candidate]
            prompt = build_bound_prompt(selection, host_events[:index + 1], evidence_rows,
                logical_run_id=self.logical_run_id, evaluator_version=self.domain.evaluator_version,
                evaluation_context=self.domain.evaluation_contexts['dev'], evolution_round=row['evolution_round'])
            expected = {'candidate_id': candidate, 'evolution_round': row['evolution_round'],
                        'selection_ref': 'sha256:' + payload_digest(selection),
                        'input_ref': prompt['input_ref'], 'prompt_ref': prompt['prompt_ref']}
            if row != expected:
                raise ValueError('original prompt record differs from its evidence')
        return host_events

    def _replay_tape(self, kind, args):
        previous = self.store.peek()
        if previous is None:
            return None
        if previous['kind'] != 'openevolve_host_event':
            raise ValueError('durable continuation expects a different event')
        event = previous['payload']
        if event.get('kind') != kind or event.get('args') != args:
            raise ValueError('host operation differs from original journal')
        return event['tape']

    def _commit(self, kind, args):
        tape = self._replay_tape(kind, args)
        result = self.policy.adapter._apply(kind, args, tape)
        event = self.policy.adapter.events[-1]
        self.store.append('openevolve_host_event', event)
        self._audit()
        return result

    def record_evaluated(self, candidate_id):
        self._audit()
        item = self._projection(candidate_id)
        if item['status'] != 'ok':
            raise ValueError('failed candidate cannot be registered as measured host program')
        self._audit_materialization(candidate_id, item['cycle'])
        selection = self.policy.pending_selection()
        expected_parents = [] if selection is None else [selection['source_candidate_id']]
        if item['parents'] != expected_parents:
            raise ValueError('candidate ancestry differs from selected host source')
        if selection is not None:
            matches = [row for row in self._rows('openevolve_prompt') if row['candidate_id'] == candidate_id]
            if len(matches) != 1:
                raise ValueError('candidate lacks its original prompt journal entry')
        args = {'candidate_id': candidate_id, 'artifact': item['artifact'],
                'metrics': {'combined_score': item['score']}, 'evidence_ref': item['evidence_ref'],
                'iteration': item['cycle'], 'selection': selection}
        return self._commit('register', args)

    async def select(self, candidate_id, frontier, budget):
        self._audit()
        if type(candidate_id) is not str or not candidate_id:
            raise ValueError('candidate identity required')
        if not self.policy.adapter.events:
            if frontier.nodes:
                raise ValueError('frontier candidates lack original host evidence')
            return []
        eligible = sorted(node.id for node in frontier.nodes.values()
                          if node.status in {'done', 'merged'} and node.eval_status == 'ok'
                          and type(node.score) in (int, float) and math.isfinite(node.score))
        if not eligible:
            raise ValueError('no eligible candidate remains in host population')
        if self.policy.pending_selection() is not None or any(
                row['candidate_id'] == candidate_id for row in self._rows('openevolve_selection_scope')):
            raise ValueError('candidate selection is already pending or recorded')
        nodes = [{'id': node.id, 'status': node.status, 'eval_status': node.eval_status, 'score': node.score}
                 for node in sorted(frontier.nodes.values(), key=lambda item: item.id)]
        scope = {'candidate_id': candidate_id, 'eligible_ids': eligible,
                 'budget_ref': 'sha256:' + payload_digest(budget),
                 'frontier_ref': 'sha256:' + payload_digest(nodes)}
        self.store.append('openevolve_selection_scope', scope)
        args = {'candidate_id': candidate_id, 'eligible_ids': eligible}
        receipt = self._commit('select', args)
        return [receipt['source_candidate_id']]

    def materialize(self, candidate_id, *, evolution_round):
        events = self._audit()
        selection = self.policy.pending_selection()
        if selection is None or selection['candidate_id'] != candidate_id:
            raise ValueError('candidate lacks its original host selection')
        prompt = build_bound_prompt(selection, events, self._rows('composed_evidence'),
            logical_run_id=self.logical_run_id, evaluator_version=self.domain.evaluator_version,
            evaluation_context=self.domain.evaluation_contexts['dev'], evolution_round=evolution_round)
        record = {'candidate_id': candidate_id, 'evolution_round': evolution_round,
                  'selection_ref': 'sha256:' + payload_digest(selection),
                  'input_ref': prompt['input_ref'], 'prompt_ref': prompt['prompt_ref']}
        existing = [row for row in self._rows('openevolve_prompt') if row['candidate_id'] == candidate_id]
        if existing:
            if existing != [record]:
                raise ValueError('prompt differs from its original journal entry')
        else:
            self.store.append('openevolve_prompt', record)
        return copy.deepcopy(prompt)

    def abandon(self, candidate_id, reason):
        self._audit()
        selection = self.policy.pending_selection()
        if selection is None or selection['candidate_id'] != candidate_id:
            raise ValueError('candidate lacks its original host selection')
        item = self._projection(candidate_id)
        if item['status'] == 'ok':
            raise ValueError('successful execution must be registered, not abandoned')
        if item['parents'] != [selection['source_candidate_id']]:
            raise ValueError('failed candidate ancestry differs from original selection')
        self._audit_failed_construction(candidate_id, item['cycle'])
        if type(reason) is not str or not reason.strip() or len(reason) > 1024:
            raise ValueError('abandonment reason must be bounded text')
        return self._commit('abandon', {'candidate_id': candidate_id, 'reason': reason})
