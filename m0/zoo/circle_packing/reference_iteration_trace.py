"""Observe the pinned reference controller's submitted iteration futures.

This trace records outcomes, not controller admission or full physical/currency
coverage. Raw prompts, responses, candidate code, and error text are excluded.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def reference_iteration_attempt_limit(planned_iterations):
    """Bound initial submissions plus one attempt per island per completion."""
    from core.composition.openevolve_registration import host_database_options
    if type(planned_iterations) is not int or not 1 <= planned_iterations <= 6:
        raise ValueError('reference iteration limit differs from the frozen pilot')
    islands = host_database_options(2)['num_islands']
    return planned_iterations * (1 + islands)


def install_prompt_observer(sampler_class, root):
    """Record an iteration/request digest without changing prompt messages."""
    from core.x1.checkpoint import payload_digest
    from core.x1.store import AppendOnlyStore
    original = sampler_class.build_prompt
    def build(sampler, *args, **kwargs):
        result = original(sampler, *args, **kwargs)
        iteration = kwargs.get('evolution_round')
        if type(iteration) is int and type(result) is dict and \
                type(result.get('system')) is str and type(result.get('user')) is str:
            messages = {'system': result['system'], 'user': result['user']}
            argument = {'host_messages': messages, 'host_prompt_ref': 'sha256:' + payload_digest(messages)}
            prompt = json.dumps(argument, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            AppendOnlyStore(Path(root) / 'iteration-prompts.jsonl').append('reference_iteration_prompt',
                {'iteration': iteration, 'request_sha256': payload_digest({'args': (prompt,), 'kwargs': {}})})
        return result
    sampler_class.build_prompt = build


_original_worker_initializer = None


def _traced_worker_initializer(*args):
    from openevolve import process_parallel
    original = _original_worker_initializer or process_parallel._worker_init
    if original is _traced_worker_initializer:
        raise RuntimeError('reference worker initializer recursion')
    original(*args)
    from openevolve.prompt.sampler import PromptSampler
    install_prompt_observer(PromptSampler, os.environ['MORI_CIRCLE_REFERENCE_ROOT'])


class _Capture:
    def __init__(self):
        self._submitted = []

    def snapshot(self):
        rows = []
        for iteration, island, future in self._submitted:
            row = {'iteration': iteration, 'requested_island': island}
            if future is None:
                row['state'] = 'not_submitted'
            elif not future.done():
                row['state'] = 'unresolved'
            elif future.cancelled():
                row['state'] = 'cancelled'
            else:
                try:
                    result = future.result()
                    if type(result.iteration) is not int or result.iteration != iteration:
                        row['state'] = 'invalid_result'
                    else:
                        row.update(parent_id=result.parent_id, target_island=result.target_island,
                                   response_sha256=_digest(result.llm_response) if type(result.llm_response) is str else None)
                        if result.error is not None:
                            row.update(state='worker_error', error_sha256=_digest(str(result.error)))
                        elif type(result.child_program_dict) is dict:
                            child = result.child_program_dict
                            code, child_id = child.get('code'), child.get('id')
                            if type(code) is not str or type(child_id) is not str or not child_id:
                                row['state'] = 'invalid_result'
                            else:
                                row.update(state='candidate', child_id=child_id, program_sha256=_digest(code))
                                artifacts = result.artifacts
                                if artifacts is not None and type(artifacts) is not dict:
                                    row['stage_receipt_invalid'] = True
                                elif artifacts is not None and 'mori_stage_request_id' in artifacts:
                                    receipt = artifacts['mori_stage_request_id']
                                    if type(receipt) is str and re.fullmatch(r'[0-9a-f]{32}', receipt):
                                        row['stage_request_id'] = receipt
                                    else:
                                        row['stage_receipt_invalid'] = True
                        else:
                            row['state'] = 'no_candidate'
                except Exception as error:
                    row.update(state='future_error', error_type=type(error).__name__)
            rows.append(row)
        return {'schema_version': 1, 'scope': 'reference_submitted_future_outcomes',
                'performance_claim': False, 'iterations': rows}


@contextmanager
def capture_reference_iterations(controller_class, *, parallel_module=None):
    """Wrap submissions temporarily, returning the exact unmodified futures."""
    capture = _Capture()
    original = controller_class._submit_iteration
    global _original_worker_initializer
    previous_initializer = parallel_module._worker_init if parallel_module is not None else None
    if parallel_module is not None:
        _original_worker_initializer = previous_initializer
        parallel_module._worker_init = _traced_worker_initializer
    def submit(controller, iteration, island_id=None):
        future = original(controller, iteration, island_id)
        capture._submitted.append((iteration, island_id, future))
        return future
    controller_class._submit_iteration = submit
    try:
        yield capture
    finally:
        controller_class._submit_iteration = original
        if parallel_module is not None:
            parallel_module._worker_init = previous_initializer
            _original_worker_initializer = None


def audit_reference_iteration_receipts(trace, rows, *, planned_iterations):
    """Compare recorded future receipts with a caller-pinned physical prefix.

    Missing receipts and worker failures remain explicit; this does not prove
    complete iteration, physical operation, or provider-cost coverage.
    """
    if type(trace) is not dict or trace.get('scope') != 'reference_submitted_future_outcomes' or \
            trace.get('performance_claim') is not False or type(trace.get('iterations')) is not list or \
            type(rows) is not list or type(planned_iterations) is not int or planned_iterations < 1:
        raise ValueError('reference receipt audit requires recorded iteration and stage evidence')
    try:
        outcomes, submitted, attempts, previous_states, seen_receipts = [], set(), {}, {}, set()
        for item in trace['iterations']:
            iteration = item['iteration']
            if type(iteration) is not int or not 1 <= iteration <= planned_iterations or \
                    (iteration in previous_states and previous_states[iteration] != 'not_submitted'):
                raise ValueError('reference iteration identity is repeated or outside the plan')
            state = item['state']
            if state not in ('candidate', 'worker_error', 'no_candidate', 'unresolved', 'not_submitted',
                             'cancelled', 'future_error', 'invalid_result'):
                raise ValueError('reference iteration has an invalid outcome')
            previous_states[iteration] = state
            attempts[iteration] = attempts.get(iteration, 0) + 1
            if state != 'not_submitted':
                submitted.add(iteration)
            if item.get('stage_receipt_invalid') is not None:
                raise ValueError('reference iteration has an invalid stage receipt')
            receipt = item.get('stage_request_id')
            receipt_state = 'not_available'
            if receipt is not None:
                program = item.get('program_sha256')
                if state != 'candidate' or type(receipt) is not str or re.fullmatch(r'[0-9a-f]{32}', receipt) is None or \
                        type(program) is not str or re.fullmatch(r'[0-9a-f]{64}', program) is None or receipt in seen_receipts:
                    raise ValueError('reference iteration stage identity is invalid')
                matches = [row['payload'] for row in rows if row['kind'] == 'host_stage_started'
                           and row['payload']['request_id'] == receipt]
                if len(matches) != 1 or matches[0]['program_ref'] != 'sha256:' + program:
                    raise ValueError('reference iteration differs from its original physical stage')
                seen_receipts.add(receipt)
                receipt_state = 'matched'
            outcomes.append({'iteration': iteration, 'attempt': attempts[iteration],
                             'state': state, 'receipt_state': receipt_state})
        return {'schema_version': 1, 'scope': 'caller_pinned_reference_iteration_receipts',
                'performance_claim': False, 'iterations': outcomes,
                'missing_iterations': [number for number in range(1, planned_iterations + 1)
                                       if number not in submitted]}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid reference iteration receipt evidence') from error
