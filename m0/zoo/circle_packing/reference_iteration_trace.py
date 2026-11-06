"""Observe the pinned reference controller's submitted iteration futures.

This trace records outcomes, not controller admission or full physical/currency
coverage. Raw prompts, responses, candidate code, and error text are excluded.
"""
from contextlib import contextmanager
import hashlib
import re


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


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
def capture_reference_iterations(controller_class):
    """Wrap submissions temporarily, returning the exact unmodified futures."""
    capture = _Capture()
    original = controller_class._submit_iteration
    def submit(controller, iteration, island_id=None):
        future = original(controller, iteration, island_id)
        capture._submitted.append((iteration, island_id, future))
        return future
    controller_class._submit_iteration = submit
    try:
        yield capture
    finally:
        controller_class._submit_iteration = original
