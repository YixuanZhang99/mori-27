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


_active_prompt = None


def record_iteration_request(messages, request_id):
    """Bind an actual broker request ID to the current observed iteration."""
    from core.x1.checkpoint import payload_digest
    from core.x1.store import AppendOnlyStore
    active = _active_prompt
    if active is None:
        return
    argument = {'host_messages': messages, 'host_prompt_ref': 'sha256:' + payload_digest(messages)}
    prompt = json.dumps(argument, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    digest = payload_digest({'args': (prompt,), 'kwargs': {}})
    if digest != active['request_sha256']:
        return
    if type(request_id) is not str or re.fullmatch(r'[0-9a-f]{32}', request_id) is None:
        raise ValueError('reference request identity is invalid')
    AppendOnlyStore(active['root'] / 'iteration-requests.jsonl').append('reference_iteration_request',
        {'iteration': active['iteration'], 'request_sha256': digest, 'request_id': request_id})


def record_iteration_stage(request_id, program_ref, *, stage, prior_id):
    """Record a stage request against the active worker iteration, if present."""
    from core.x1.store import AppendOnlyStore
    active = _active_prompt
    if active is None:
        return
    if type(request_id) is not str or re.fullmatch(r'[0-9a-f]{32}', request_id) is None or \
            type(program_ref) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', program_ref) is None or \
            type(stage) is not int or stage not in (1, 2) or \
            (stage == 1 and prior_id is not None) or \
            (stage == 2 and (type(prior_id) is not str or re.fullmatch(r'[0-9a-f]{32}', prior_id) is None)):
        raise ValueError('reference stage identity is invalid')
    AppendOnlyStore(active['root'] / 'iteration-stages.jsonl').append('reference_iteration_stage',
        {'iteration': active['iteration'], 'request_id': request_id, 'program_ref': program_ref,
         'stage': stage, 'prior_id': prior_id})


def install_prompt_observer(sampler_class, root):
    """Record an iteration/request digest without changing prompt messages."""
    from core.x1.checkpoint import payload_digest
    from core.x1.store import AppendOnlyStore
    original = sampler_class.build_prompt
    def build(sampler, *args, **kwargs):
        global _active_prompt
        _active_prompt = None
        result = original(sampler, *args, **kwargs)
        iteration = kwargs.get('evolution_round')
        if type(iteration) is int and type(result) is dict and \
                type(result.get('system')) is str and type(result.get('user')) is str:
            messages = {'system': result['system'], 'user': result['user']}
            argument = {'host_messages': messages, 'host_prompt_ref': 'sha256:' + payload_digest(messages)}
            prompt = json.dumps(argument, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            digest = payload_digest({'args': (prompt,), 'kwargs': {}})
            _active_prompt = {'root': Path(root), 'iteration': iteration, 'request_sha256': digest}
            AppendOnlyStore(Path(root) / 'iteration-prompts.jsonl').append('reference_iteration_prompt',
                {'iteration': iteration, 'request_sha256': digest})
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
        self._controller_run = None

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
        report = {'schema_version': 1, 'scope': 'reference_submitted_future_outcomes',
                  'performance_claim': False, 'iterations': rows}
        if self._controller_run is not None:
            report['controller_run'] = dict(self._controller_run)
        return report


@contextmanager
def capture_reference_iterations(controller_class, *, parallel_module=None):
    """Wrap submissions temporarily, returning the exact unmodified futures."""
    capture = _Capture()
    original = controller_class._submit_iteration
    original_run = getattr(controller_class, 'run_evolution', None)
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
    if original_run is not None:
        async def run(controller, start_iteration, max_iterations, *args, **kwargs):
            try:
                result = await original_run(controller, start_iteration, max_iterations, *args, **kwargs)
            except BaseException as error:
                capture._controller_run = {'start_iteration': start_iteration, 'max_iterations': max_iterations,
                                           'stop_reason': 'exception', 'exception_type': type(error).__name__}
                raise
            completed = getattr(controller, 'completed_iterations', None)
            early = getattr(controller, 'early_stopping_triggered', None)
            shutdown = controller.shutdown_event.is_set()
            reason = ('early_stopping' if early is True else 'shutdown' if shutdown else
                      'iteration_limit' if type(completed) is int and completed == max_iterations else
                      'incomplete_unspecified')
            capture._controller_run = {'start_iteration': start_iteration, 'max_iterations': max_iterations,
                'reported_completed_iterations': completed, 'stop_reason': reason}
            return result
        controller_class.run_evolution = run
    try:
        yield capture
    finally:
        controller_class._submit_iteration = original
        if original_run is not None:
            controller_class.run_evolution = original_run
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


def audit_reference_iteration_provider(trace, rows, bundle, *, planned_iterations):
    """Join uniquely occurring prompt digests to recorded provider receipts.

    The caller must independently pin and verify both journals and the currency
    bundle. Duplicate prompts or calls are reported as ambiguous, not assigned.
    """
    if type(trace) is not dict or type(rows) is not list or type(bundle) is not dict or \
            type(planned_iterations) is not int or not 1 <= planned_iterations <= 6:
        raise ValueError('reference provider audit requires recorded evidence')
    try:
        bindings = trace.get('prompt_bindings', [])
        submitted = trace.get('iterations')
        if type(bindings) is not list or type(submitted) is not list or \
                len(bindings) > reference_iteration_attempt_limit(planned_iterations):
            raise ValueError('reference prompt bindings are invalid')
        for item in bindings:
            if type(item) is not dict or set(item) != {'iteration', 'request_sha256'} or \
                    type(item['iteration']) is not int or not 1 <= item['iteration'] <= planned_iterations or \
                    type(item['request_sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', item['request_sha256']) is None:
                raise ValueError('reference prompt binding is invalid')
        request_bindings = trace.get('request_bindings')
        if request_bindings is not None:
            if type(request_bindings) is not list or len(request_bindings) > reference_iteration_attempt_limit(planned_iterations):
                raise ValueError('reference request bindings are invalid')
            for item in request_bindings:
                if type(item) is not dict or set(item) != {'iteration', 'request_sha256', 'request_id'} or \
                        type(item['iteration']) is not int or not 1 <= item['iteration'] <= planned_iterations or \
                        type(item['request_sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', item['request_sha256']) is None or \
                        type(item['request_id']) is not str or re.fullmatch(r'[0-9a-f]{32}', item['request_id']) is None:
                    raise ValueError('reference request binding is invalid')
        starts = [row['payload'] for row in rows if row['kind'] == 'composed_provider_started'
                  and row['payload']['invocation']['external_context']['lane'] == 'main']
        completions = [row['payload'] for row in rows if row['kind'] == 'composed_provider_completed']
        calls = bundle['calls']
        if type(calls) is not list:
            raise ValueError('reference provider calls are invalid')
        outcomes, attributed = [], set()
        for item in bindings:
            digest = item['request_sha256']
            matching_bindings = [entry for entry in bindings if entry['request_sha256'] == digest]
            same_iteration = [entry for entry in bindings if entry['iteration'] == item['iteration']]
            submissions = [entry for entry in submitted if entry['iteration'] == item['iteration']
                           and entry['state'] != 'not_submitted']
            requests = None if request_bindings is None else [entry for entry in request_bindings
                if entry['iteration'] == item['iteration'] and entry['request_sha256'] == digest]
            request_id = requests[0]['request_id'] if requests and len(requests) == 1 else None
            matching_starts = [entry for entry in starts if entry['request_sha256'] == digest and
                (request_bindings is None or request_id is not None and
                 entry['invocation']['external_context']['intent_id'] == 'host:' + request_id)]
            result = {'iteration': item['iteration'], 'request_sha256': digest}
            duplicate_request = request_id is not None and sum(
                entry['request_id'] == request_id for entry in request_bindings) != 1
            if (request_bindings is None and len(matching_bindings) != 1) or len(same_iteration) != 1 or \
                    len(submissions) > 1 or len(matching_starts) > 1 or \
                    (requests is not None and len(requests) > 1) or duplicate_request:
                result['state'] = 'ambiguous'
            elif not submissions or submissions[0]['state'] not in ('candidate', 'worker_error', 'no_candidate'):
                result['state'] = 'unverified_submission'
            elif requests is not None and not requests:
                result['state'] = 'unverified_request'
            elif not matching_starts:
                result['state'] = 'not_observed'
            else:
                start = matching_starts[0]
                context = start['invocation']['external_context']
                matched_completions = [entry for entry in completions if entry['binding'] == start['binding']]
                matched_calls = [entry for entry in calls if entry['prepared']['context'] == context]
                if context['argument_sha256'] != digest or len(matched_completions) != 1 or len(matched_calls) != 1:
                    raise ValueError('reference provider start lacks one matching original receipt')
                call = matched_calls[0]
                call_id = call['prepared']['call_id']
                usage = call['outcome']['usage']
                if type(call_id) is not str or re.fullmatch(r'[0-9a-f]{64}', call_id) is None or \
                        call['outcome']['call_id'] != call_id or type(usage) is not dict or \
                        type(usage.get('total_tokens')) is not int or \
                        matched_completions[0]['tokens'] != usage['total_tokens']:
                    raise ValueError('reference provider receipt differs from its physical completion')
                result.update(state='matched', call_id=call_id, total_tokens=usage['total_tokens'])
                attributed.add(start['binding'])
            outcomes.append(result)
        return {'schema_version': 1, 'scope': 'caller_pinned_reference_iteration_provider',
                'performance_claim': False, 'iterations': outcomes,
                'missing_prompt_iterations': [number for number in range(1, planned_iterations + 1)
                                              if not any(item['iteration'] == number for item in bindings)],
                'unattributed_provider_bindings': [start['binding'] for start in starts
                                                   if start['binding'] not in attributed]}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid reference iteration provider evidence') from error


def audit_reference_iteration_stages(trace, rows, *, planned_iterations):
    """Compare worker stage IDs to a caller-pinned physical stage transcript."""
    if type(trace) is not dict or type(rows) is not list or type(planned_iterations) is not int or \
            not 1 <= planned_iterations <= 6 or type(trace.get('stage_bindings')) is not list or \
            type(trace.get('iterations')) is not list:
        raise ValueError('reference stage audit requires recorded evidence')
    try:
        entries = trace['stage_bindings']
        if len(entries) > 2 * reference_iteration_attempt_limit(planned_iterations):
            raise ValueError('reference stage trace exceeds its planned bound')
        starts = [row['payload'] for row in rows if row['kind'] == 'host_stage_started']
        completions = [row['payload'] for row in rows if row['kind'] == 'host_stage_completed']
        results, seen, attributed = [], set(), set()
        for entry in entries:
            if type(entry) is not dict or set(entry) != {'iteration', 'request_id', 'program_ref', 'stage', 'prior_id'}:
                raise ValueError('reference stage binding has invalid fields')
            iteration, request_id, program, stage, prior = (entry[key] for key in
                ('iteration', 'request_id', 'program_ref', 'stage', 'prior_id'))
            if type(iteration) is not int or not 1 <= iteration <= planned_iterations or \
                    type(request_id) is not str or re.fullmatch(r'[0-9a-f]{32}', request_id) is None or \
                    request_id in seen or type(program) is not str or \
                    re.fullmatch(r'sha256:[0-9a-f]{64}', program) is None or type(stage) is not int or \
                    stage not in (1, 2) or (stage == 1 and prior is not None) or \
                    (stage == 2 and (type(prior) is not str or re.fullmatch(r'[0-9a-f]{32}', prior) is None)):
                raise ValueError('reference iteration stage identity is invalid')
            seen.add(request_id)
            submitted = [row for row in trace['iterations'] if row['iteration'] == iteration
                         and row['state'] != 'not_submitted']
            matching = [row for row in starts if row['request_id'] == request_id]
            output = {'iteration': iteration, 'request_id': request_id, 'stage': stage}
            if len(submitted) != 1 or submitted[0]['state'] not in ('candidate', 'worker_error', 'no_candidate'):
                output['state'] = 'unverified_submission'
            elif len(matching) > 1:
                raise ValueError('reference stage was started more than once')
            elif not matching:
                output['state'] = 'not_observed'
            else:
                started = matching[0]
                if any(started[key] != entry[key] for key in ('program_ref', 'stage', 'prior_id')) or \
                        (submitted[0]['state'] == 'candidate' and
                         program != 'sha256:' + submitted[0]['program_sha256']):
                    raise ValueError('reference stage differs from its original program or request')
                terminal = [row for row in completions if row['request_id'] == request_id]
                if len(terminal) > 1:
                    raise ValueError('reference stage has duplicate terminal evidence')
                if not terminal:
                    output['state'] = 'unresolved'
                else:
                    status = terminal[0]['result']['status']
                    if status not in ('ok', 'timeout', 'failed_to_run'):
                        raise ValueError('reference stage outcome is invalid')
                    output.update(state='matched', stage_status=status,
                                  candidate_program_digest_matches=submitted[0]['state'] == 'candidate')
                    attributed.add(request_id)
            results.append(output)
        return {'schema_version': 1, 'scope': 'caller_pinned_reference_iteration_stages',
                'performance_claim': False, 'stages': results,
                'unattributed_stage_ids': [row['request_id'] for row in starts if row['request_id'] not in attributed]}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid reference iteration stage evidence') from error


def summarize_reference_run_coverage(trace, receipts, provider, stages, *, planned_iterations):
    """Report observed per-iteration coverage and the controller's stop assertion.

    This combines already checked partial reports. It does not certify complete
    physical or cost coverage, or authorize another paid cell.
    """
    if any(type(value) is not dict for value in (trace, receipts, provider, stages)) or \
            type(planned_iterations) is not int or not 1 <= planned_iterations <= 6:
        raise ValueError('reference run summary requires bounded recorded reports')
    try:
        controller = trace.get('controller_run')
        if controller is None:
            reason, completed = 'not_recorded', None
        else:
            reason = controller['stop_reason']
            completed = controller.get('reported_completed_iterations')
            if controller['start_iteration'] != 1 or controller['max_iterations'] != planned_iterations or \
                    reason not in ('iteration_limit', 'early_stopping', 'shutdown', 'incomplete_unspecified', 'exception') or \
                    (completed is not None and (type(completed) is not int or not 0 <= completed <= planned_iterations)) or \
                    (reason == 'iteration_limit' and completed != planned_iterations):
                raise ValueError('reference controller stop metadata differs from the plan')
        attempts = receipts['iterations']
        providers = provider.get('iterations', [])
        stage_rows = stages.get('stages', [])
        if any(type(value) is not list for value in (attempts, providers, stage_rows)):
            raise ValueError('reference run summary requires iteration lists')
        outcomes = []
        for iteration in range(1, planned_iterations + 1):
            own = [item for item in attempts if item['iteration'] == iteration]
            actual = [item for item in own if item['state'] != 'not_submitted']
            links = [item['state'] for item in providers if item['iteration'] == iteration]
            physical = [{'state': item['state'], 'stage_status': item.get('stage_status')}
                        for item in stage_rows if item['iteration'] == iteration]
            outcomes.append({'iteration': iteration,
                'submission_state': actual[0]['state'] if len(actual) == 1 else
                                    'not_submitted' if not actual else 'ambiguous',
                'submission_attempts': len(own), 'provider_states': links, 'stages': physical})
        return {'schema_version': 1, 'scope': 'reference_run_partial_coverage', 'performance_claim': False,
                'complete_run_certified': False, 'controller_stop_reason': reason,
                'controller_reported_completed_iterations': completed, 'iterations': outcomes,
                'missing_prompt_iterations': provider.get('missing_prompt_iterations'),
                'unattributed_provider_bindings': provider.get('unattributed_provider_bindings'),
                'unattributed_stage_ids': stages.get('unattributed_stage_ids')}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid reference run coverage evidence') from error


def audit_reference_accounting_coverage(coverage, provider, stages, *, rows, plan):
    """Account for planned calls and stages, including the initial seed stage.

    Inputs must already be verified against the original worker and campaign.
    Even a complete accounting result is not a full search/replay certificate.
    """
    if any(type(value) is not dict for value in (coverage, provider, stages, plan)) or type(rows) is not list:
        raise ValueError('reference accounting coverage requires recorded reports')
    try:
        count, seed = plan['iterations'], plan['seed_sha256']
        if type(count) is not int or not 1 <= count <= 6 or type(seed) is not str or \
                re.fullmatch(r'[0-9a-f]{64}', seed) is None:
            raise ValueError('reference accounting plan is invalid')
        reasons = []
        if coverage['controller_stop_reason'] != 'iteration_limit' or \
                coverage['controller_reported_completed_iterations'] != count:
            reasons.append('controller_did_not_report_all_iterations')
        outcomes = coverage['iterations']
        if type(outcomes) is not list or [row['iteration'] for row in outcomes] != list(range(1, count + 1)):
            raise ValueError('reference iteration summary differs from the plan')
        if provider.get('missing_prompt_iterations') != [] or provider.get('unattributed_provider_bindings') != []:
            reasons.append('provider_coverage_incomplete')
        provider_rows = provider['iterations']
        stage_rows = stages['stages']
        for item in outcomes:
            number, state = item['iteration'], item['submission_state']
            calls = [row for row in provider_rows if row['iteration'] == number]
            physical = [row for row in stage_rows if row['iteration'] == number]
            if state not in ('candidate', 'worker_error'):
                reasons.append(f'iteration_{number}_outcome_unverified')
            if len(calls) != 1 or calls[0]['state'] != 'matched':
                reasons.append(f'iteration_{number}_provider_unverified')
            if state == 'candidate' and (not physical or any(row['state'] != 'matched' or
                    row.get('candidate_program_digest_matches') is not True for row in physical)):
                reasons.append(f'iteration_{number}_stages_unverified')
            if state != 'candidate' and physical:
                reasons.append(f'iteration_{number}_stage_candidate_unverified')
        main_indices = [index for index, row in enumerate(rows) if row['kind'] == 'composed_provider_started'
                        and row['payload']['invocation']['external_context']['lane'] == 'main']
        if not main_indices:
            reasons.append('initial_seed_order_unverified')
            seed_stages = []
        else:
            seed_stages = [row['payload'] for row in rows[:main_indices[0]] if row['kind'] == 'host_stage_started']
            valid_seed = (len(seed_stages) in (1, 2) and seed_stages[0]['stage'] == 1 and
                          seed_stages[0]['prior_id'] is None and all(
                              row['program_ref'] == 'sha256:' + seed for row in seed_stages) and
                          (len(seed_stages) == 1 or seed_stages[1]['stage'] == 2 and
                           seed_stages[1]['prior_id'] == seed_stages[0]['request_id']))
            if not valid_seed:
                reasons.append('initial_seed_stages_unverified')
        seed_ids = [row['request_id'] for row in seed_stages]
        if len(seed_ids) != len(set(seed_ids)) or stages.get('unattributed_stage_ids') != seed_ids:
            reasons.append('unattributed_physical_stages')
        return {'schema_version': 1, 'scope': 'reference_iteration_accounting_coverage',
                'performance_claim': False, 'complete_run_certified': False,
                'iteration_accounting_complete': not reasons, 'reasons': reasons, 'seed_stage_ids': seed_ids}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid reference accounting coverage evidence') from error
