"""Join a FunSearch provider prompt to earlier durable main-lane evidence.

The caller supplies authenticated journal rows and a provider request already
matched to its external invocation. This reducer makes no external calls and
is not, by itself, an authentication mechanism for journal contents.
"""
from __future__ import annotations

import hashlib
from core.composition.evaluation import decode_evidence
from core.funsearch_prompt import build_journal_bound_prompt
from core.funsearch_public_evidence import project_program_candidate, verify_selected_projections
from core.x1.checkpoint import payload_digest


def audit_funsearch_invocation(rows, provider_index, request, *, case_ids, metric, logical_run_id,
                               evaluator_version, evaluation_context, template_ref, template,
                               function_name, comparison_metric='dev/score'):
    if type(rows) is not list or type(provider_index) is not int or not 0 <= provider_index < len(rows):
        raise ValueError('original provider position is required')
    if type(template) is not str or template_ref != 'sha256:' + hashlib.sha256(template.encode('utf-8')).hexdigest():
        raise ValueError('program template differs from frozen manifest')
    try:
        start = rows[provider_index]
        context = start['payload']['invocation']['external_context']
        if start['kind'] != 'composed_provider_started' or context['phase'] != 'operator' or context['lane'] != 'main':
            raise ValueError('FunSearch prompt requires an original main-lane provider start')
        candidate_id = context['candidate_id']
        if type(candidate_id) is not str or not candidate_id:
            raise ValueError('provider start lacks candidate identity')
        recipe = request['recipe']
        if type(recipe) is not dict or set(recipe) != {'kind', 'task_desc', 'parent_artifacts', 'instructions', 'comparison', 'funsearch_binding'} or recipe['kind'] != 'funsearch':
            raise ValueError('invalid FunSearch construction recipe')
        prefix = rows[:provider_index]
        selections = [(index, row['payload']) for index, row in enumerate(prefix)
                      if row['kind'] == 'funsearch_selection' and row['payload'].get('candidate_id') == candidate_id]
        materializations = [(index, row['payload']) for index, row in enumerate(prefix)
                            if row['kind'] == 'funsearch_materialization' and row['payload'].get('candidate_id') == candidate_id]
        if len(selections) != 1 or len(materializations) != 1 or selections[0][0] >= materializations[0][0]:
            raise ValueError('provider start lacks unique ordered selection and materialization events')
        selection = selections[0][1]['selection']
        receipt = selection['receipt']
        selected = set(receipt['ancestry'])
        before_selection = prefix[:selections[0][0]]
        evidence_rows = [row['payload'] for row in before_selection if row['kind'] == 'composed_evidence']
        public_rows = [row['payload'] for row in before_selection if row['kind'] == 'funsearch_public_candidate'
                       and row['payload'].get('candidate_id') in selected]
        if len(public_rows) != len(selected) or {item['candidate_id'] for item in public_rows} != selected:
            raise ValueError('selected candidates lack unique earlier public projection events')
        projections = {item['candidate_id']: item for item in public_rows}
        verify_selected_projections(evidence_rows, projections, selected, case_ids=case_ids, metric=metric,
            logical_run_id=logical_run_id, evaluator_version=evaluator_version, evaluation_context=evaluation_context)
        selected_rows = {row['proposal']['candidate']['id']: row for row in evidence_rows
                         if row['proposal']['candidate']['id'] in selected}
        sources = {candidate: row['proposal']['artifact'] for candidate, row in selected_rows.items()}
        bound = build_journal_bound_prompt(template, function_name, receipt, selection['before'], selection['after'],
            eligible=set(receipt['eligible']), max_parents=2, sources=sources, projections=projections,
            evidence_rows=evidence_rows, case_ids=case_ids, metric=metric, logical_run_id=logical_run_id,
            evaluator_version=evaluator_version, evaluation_context=evaluation_context)
        event = {'candidate_id': candidate_id, 'function_name': function_name, 'template_ref': template_ref,
                 **{key: bound[key] for key in ('selection_ref', 'input_ref', 'prompt_ref', 'binding_ref')}}
        if payload_digest(event) != payload_digest(materializations[0][1]):
            raise ValueError('provider prompt differs from original materialization event')
        expected_binding = {'selection': receipt, **{key: bound[key] for key in
            ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs', 'binding_ref')}}
        if payload_digest(recipe['funsearch_binding']) != payload_digest(expected_binding) or recipe['instructions'] != [bound['prompt']]:
            raise ValueError('provider recipe differs from verified FunSearch prompt')
        parents = [{'candidate_id': parent, 'artifact': sources[parent]} for parent in receipt['ancestry']]
        if payload_digest(recipe['parent_artifacts']) != payload_digest(parents):
            raise ValueError('provider recipe differs from evaluated parent artifacts')
        comparison = {}
        for parent in receipt['ancestry']:
            evidence = decode_evidence({'schema_version': 1, 'evidence': selected_rows[parent]['evidence']})
            comparison[parent] = evidence.eval_result.metrics[comparison_metric]
        if payload_digest(recipe['comparison']) != payload_digest(comparison):
            raise ValueError('provider comparison differs from original evaluation metrics')
        return {'candidate_id': candidate_id, 'samples': len(receipt['samples']),
                'selection_ref': bound['selection_ref'], 'prompt_ref': bound['prompt_ref'],
                'external_provider_requests': 0}
    except (KeyError, TypeError, IndexError, UnicodeEncodeError) as exc:
        raise ValueError('invalid original FunSearch invocation evidence') from exc
