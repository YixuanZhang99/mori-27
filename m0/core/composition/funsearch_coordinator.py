"""Durable M7-facing FunSearch coordination, not yet installed in Framework.

The owning runtime must hold its coordinator lock, provide the validated main
journal and bind policy checkpoint and invocation receipts to that journal.
This module performs no provider or evaluator calls.
"""
from __future__ import annotations

import hashlib
import re

from core.composition.evaluation import decode_evidence
from core.composition.funsearch_policy import FunSearchPolicy
from core.composition.recovery import ContinuationStore
from core.funsearch_prompt import build_journal_bound_prompt
from core.funsearch_public_evidence import project_program_candidate, verify_selected_projections
from core.x1.checkpoint import payload_digest


class FunSearchCoordinator:
    def __init__(self, policy, store, *, case_ids, metric, logical_run_id, evaluator_version, evaluation_context,
                 template_ref, template, function_name):
        if type(policy) is not FunSearchPolicy or not isinstance(store, ContinuationStore):
            raise ValueError('durable FunSearch policy and continuation store are required')
        if any(type(value) is not str or not value.strip() for value in
               (metric, logical_run_id, evaluator_version, evaluation_context)):
            raise ValueError('frozen evaluator and run identities are required')
        if case_ids != policy.population.checkpoint_state()['config']['case_ids']:
            raise ValueError('frozen case identities differ from policy')
        if (type(template_ref) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', template_ref) or
                type(template) is not str or not template or
                type(function_name) is not str or not function_name.isidentifier()):
            raise ValueError('frozen template reference and function identity are required')
        try:
            actual_ref = 'sha256:' + hashlib.sha256(template.encode('utf-8')).hexdigest()
        except UnicodeEncodeError as exc:
            raise ValueError('frozen template must be valid UTF-8') from exc
        if actual_ref != template_ref:
            raise ValueError('frozen template reference differs from its source')
        self.policy, self.store = policy, store
        self.template_ref, self.template, self.function_name = template_ref, template, function_name
        self.frozen = dict(case_ids=list(case_ids), metric=metric, logical_run_id=logical_run_id,
                           evaluator_version=evaluator_version, evaluation_context=evaluation_context)

    def _rows(self, kind):
        return [row['payload'] for row in self.store.read(kind)]

    def _audit(self):
        candidates = self.policy.checkpoint_state()['population']['candidates']
        events = self._rows('funsearch_public_candidate')
        by_id = {}
        for event in events:
            if type(event) is not dict or type(event.get('candidate_id')) is not str or event['candidate_id'] in by_id:
                raise ValueError('invalid candidate journal events')
            by_id[event['candidate_id']] = event
        if set(by_id) != set(candidates):
            raise ValueError('candidate journal coverage differs from policy state')
        if by_id:
            verify_selected_projections(self._rows('composed_evidence'), by_id, set(by_id), **self.frozen)
        return self.policy.audit_original_evidence(self._rows('composed_evidence'),
            metric=self.frozen['metric'], logical_run_id=self.frozen['logical_run_id'],
            evaluator_version=self.frozen['evaluator_version'], evaluation_context=self.frozen['evaluation_context'],
            selection_rows=[row['selection'] for row in self._rows('funsearch_selection')],
            reset_rows=self._rows('funsearch_reset'), abandonment_rows=self._rows('funsearch_abandonment'))

    def _event(self, candidate_id):
        events = [row for row in self._rows('funsearch_selection') if row.get('candidate_id') == candidate_id]
        pending = self.policy.pending_selection()
        if len(events) != 1 or set(events[0]) != {'candidate_id', 'selection'} or pending is None or \
                payload_digest(events[0]['selection']) != payload_digest(pending):
            raise ValueError('candidate lacks its original selection journal event')
        return events[0]

    def _projection(self, candidate_id):
        rows = [row for row in self._rows('composed_evidence')
                if row.get('proposal', {}).get('candidate', {}).get('id') == candidate_id]
        if len(rows) != 1:
            raise ValueError('candidate requires unique original evidence')
        row = rows[0]
        evidence = decode_evidence({'schema_version': 1, 'evidence': row['evidence']})
        projection = project_program_candidate(evidence, row['proposal']['artifact'],
            case_ids=self.frozen['case_ids'], metric=self.frozen['metric'], logical_run_id=self.frozen['logical_run_id'])
        verify_selected_projections(self._rows('composed_evidence'), {candidate_id: projection}, {candidate_id}, **self.frozen)
        return row, projection

    def record_evaluated(self, candidate_id):
        if type(candidate_id) is not str or not candidate_id:
            raise ValueError('candidate identity is required')
        if self.policy.pending_selection() is not None:
            self._audit()
            selection = self._event(candidate_id)['selection']
            records = [row for row in self._rows('funsearch_materialization') if row.get('candidate_id') == candidate_id]
            if (len(records) != 1 or set(records[0]) != {'candidate_id', 'function_name', 'template_ref',
                    'selection_ref', 'input_ref', 'prompt_ref', 'binding_ref'} or
                    type(records[0]['function_name']) is not str or not records[0]['function_name'].isidentifier() or
                    records[0]['selection_ref'] != 'sha256:' + payload_digest(selection['receipt']) or
                    any(type(records[0][key]) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', records[0][key])
                        for key in ('template_ref', 'input_ref', 'prompt_ref', 'binding_ref'))):
                raise ValueError('candidate lacks its durable materialization record')
            self.materialize(candidate_id, self.template, self.function_name)
        if any(row.get('candidate_id') == candidate_id for row in self._rows('funsearch_public_candidate')):
            raise ValueError('candidate was already recorded')
        _row, projection = self._projection(candidate_id)
        self.policy.record_evaluated(projection)
        self.store.append('funsearch_public_candidate', projection)
        self._audit()

    async def select(self, candidate_id, frontier, budget):
        if type(candidate_id) is not str or not candidate_id:
            raise ValueError('candidate identity is required')
        self._audit()
        if any(row.get('candidate_id') == candidate_id for row in self._rows('funsearch_selection')):
            raise ValueError('candidate selection already exists')
        ancestry = await self.policy.select(frontier, budget)
        selection = self.policy.pending_selection()
        if selection is not None:
            self.store.append('funsearch_selection', {'candidate_id': candidate_id, 'selection': selection})
            self._audit()
        return ancestry

    def abandon(self, candidate_id, reason):
        self._audit()
        self._event(candidate_id)
        disposition = self.policy.abandon_selection(reason)
        self.store.append('funsearch_abandonment', disposition)
        self._audit()
        return disposition

    def reset_weaker_half(self):
        self._audit()
        events = self.policy.reset_weaker_half()
        self.store.append('funsearch_reset', self.policy.pending_reset())
        self._audit()
        return events

    def materialize(self, candidate_id, template, function_name):
        if (type(template) is not str or function_name != self.function_name or
                'sha256:' + hashlib.sha256(template.encode('utf-8')).hexdigest() != self.template_ref):
            raise ValueError('template differs from frozen program configuration')
        self._audit()
        selection = self._event(candidate_id)['selection']
        identifiers = selection['receipt']['ancestry']
        pairs = {name: self._projection(name) for name in identifiers}
        sources = {name: pair[0]['proposal']['artifact'] for name, pair in pairs.items()}
        projections = {name: pair[1] for name, pair in pairs.items()}
        result = build_journal_bound_prompt(template, function_name, selection['receipt'], selection['before'],
            selection['after'], eligible=set(selection['receipt']['eligible']), max_parents=2,
            sources=sources, projections=projections, evidence_rows=self._rows('composed_evidence'), **self.frozen)
        record = {'candidate_id': candidate_id, 'function_name': function_name,
                  'template_ref': 'sha256:' + hashlib.sha256(template.encode('utf-8')).hexdigest(),
                  'selection_ref': result['selection_ref'], 'input_ref': result['input_ref'],
                  'prompt_ref': result['prompt_ref'], 'binding_ref': result['binding_ref']}
        existing = [row for row in self._rows('funsearch_materialization') if row.get('candidate_id') == candidate_id]
        if existing:
            if len(existing) != 1 or payload_digest(existing[0]) != payload_digest(record):
                raise ValueError('materialization differs from its original journal event')
        else:
            self.store.append('funsearch_materialization', record)
        return result
