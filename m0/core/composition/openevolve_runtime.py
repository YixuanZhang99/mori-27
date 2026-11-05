"""Journal-bound OpenEvolve coordination; public runtime wiring is pending."""
from __future__ import annotations

import copy
import math

from core.composition.contracts import Proposal
from core.composition.evaluation import binding_for, decode_evidence, encode_evidence
from core.composition.openevolve_policy import OpenEvolvePolicy
from core.composition.openevolve_prompt import build_bound_prompt
from core.composition.recovery import ContinuationStore
from core.executor.types import Candidate, CostVec, EvalRequest, EvalStatus
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.domain import CirclePackingDomain


class OpenEvolveCoordinator:
    """Bind serial host decisions to original main-lane development evidence."""

    def __init__(self, policy, store, *, logical_run_id, domain):
        if not isinstance(policy, OpenEvolvePolicy) or not isinstance(store, ContinuationStore) \
                or not isinstance(domain, CirclePackingDomain) or type(logical_run_id) is not str or not logical_run_id:
            raise ValueError('OpenEvolve requires its policy, durable journal and frozen circle domain')
        self.policy, self.store, self.logical_run_id, self.domain = policy, store, logical_run_id, domain

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

    def _audit(self):
        host_events = self._rows('openevolve_host_event')
        self.policy.adapter.restore_state(self.policy.adapter.checkpoint_state(), host_events)
        evidence_rows = self._rows('composed_evidence')
        prompt_rows = self._rows('openevolve_prompt')
        prompts, selections, seen = {}, {}, set()
        for row in prompt_rows:
            if type(row) is not dict or set(row) != {'candidate_id', 'evolution_round', 'selection_ref', 'input_ref', 'prompt_ref'} \
                    or row['candidate_id'] in prompts:
                raise ValueError('invalid or duplicate original prompt record')
            prompts[row['candidate_id']] = row
        for index, event in enumerate(host_events):
            args, candidate = event['args'], event['candidate_id']
            if event['kind'] == 'select':
                if candidate in selections or not set(args['eligible_ids']) <= seen:
                    raise ValueError('selection lacks registered original sources')
                selections[candidate] = (event['result'], index)
                continue
            if event['kind'] == 'abandon':
                if candidate not in selections or candidate not in prompts:
                    raise ValueError('abandonment lacks original selection and prompt')
                item = self._projection(candidate)
                if item['status'] == 'ok' or item['parents'] != [selections[candidate][0]['source_candidate_id']]:
                    raise ValueError('abandonment differs from original failure evidence')
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
            seen.add(candidate)
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
        if type(reason) is not str or not reason.strip() or len(reason) > 1024:
            raise ValueError('abandonment reason must be bounded text')
        return self._commit('abandon', {'candidate_id': candidate_id, 'reason': reason})
