"""Only uniquely matched provider calls may be attributed to an iteration."""
import copy

import pytest

from zoo.circle_packing.reference_iteration_trace import audit_reference_iteration_provider


def test_unique_provider_request_is_linked_and_duplicate_prompt_is_ambiguous():
    digest, binding, call_id = 'a' * 64, 'b' * 64, 'c' * 64
    context = {'lane': 'main', 'argument_sha256': digest, 'intent_id': 'host-dispatch:fixture'}
    trace = {'prompt_bindings': [{'iteration': 1, 'request_sha256': digest}],
             'iterations': [{'iteration': 1, 'state': 'candidate'}, {'iteration': 2, 'state': 'worker_error'}]}
    rows = [{'kind': 'composed_provider_started', 'payload': {'request_sha256': digest, 'binding': binding,
              'invocation': {'external_context': context}}},
            {'kind': 'composed_provider_completed', 'payload': {'binding': binding, 'tokens': 7}}]
    bundle = {'calls': [{'prepared': {'context': context, 'call_id': call_id},
                         'outcome': {'call_id': call_id, 'usage': {'total_tokens': 7}}}]}
    result = audit_reference_iteration_provider(trace, rows, bundle, planned_iterations=2)
    assert result['iterations'][0]['state'] == 'matched'
    assert result['iterations'][0]['call_id'] == call_id
    assert result['missing_prompt_iterations'] == [2] and result['unattributed_provider_bindings'] == []
    duplicate = {**trace, 'prompt_bindings': trace['prompt_bindings'] + [{'iteration': 2, 'request_sha256': digest}]}
    assert all(item['state'] == 'ambiguous' for item in
               audit_reference_iteration_provider(duplicate, rows, bundle, planned_iterations=2)['iterations'])
    assert audit_reference_iteration_provider(duplicate, rows, bundle, planned_iterations=2)['unattributed_provider_bindings'] == [binding]
    duplicate_round = {**trace, 'prompt_bindings': trace['prompt_bindings'] +
                       [{'iteration': 1, 'request_sha256': 'd' * 64}]}
    assert all(item['state'] == 'ambiguous' for item in
               audit_reference_iteration_provider(duplicate_round, rows, bundle, planned_iterations=2)['iterations'])
    cancelled = {**trace, 'iterations': [{'iteration': 1, 'state': 'cancelled'}]}
    assert audit_reference_iteration_provider(cancelled, rows, bundle, planned_iterations=2)['iterations'][0]['state'] == 'unverified_submission'
    altered = copy.deepcopy(bundle)
    altered['calls'][0]['outcome']['usage']['total_tokens'] = 8
    with pytest.raises(ValueError, match='provider'):
        audit_reference_iteration_provider(trace, rows, altered, planned_iterations=2)


def test_identical_prompts_use_distinct_original_broker_request_ids():
    digest = 'a' * 64
    trace = {'iterations': [{'iteration': 1, 'state': 'candidate'}, {'iteration': 2, 'state': 'worker_error'}],
             'prompt_bindings': [{'iteration': 1, 'request_sha256': digest}, {'iteration': 2, 'request_sha256': digest}],
             'request_bindings': [{'iteration': 1, 'request_sha256': digest, 'request_id': '1' * 32},
                                  {'iteration': 2, 'request_sha256': digest, 'request_id': '2' * 32}]}
    rows, calls = [], []
    for digit in ('1', '2'):
        context = {'lane': 'main', 'argument_sha256': digest, 'intent_id': 'host:' + digit * 32}
        binding, call_id = digit * 64, ('a' if digit == '1' else 'b') * 64
        rows += [{'kind': 'composed_provider_started', 'payload': {'request_sha256': digest, 'binding': binding,
                   'invocation': {'external_context': context}}},
                 {'kind': 'composed_provider_completed', 'payload': {'binding': binding, 'tokens': 7}}]
        calls.append({'prepared': {'context': context, 'call_id': call_id},
                      'outcome': {'call_id': call_id, 'usage': {'total_tokens': 7}}})
    result = audit_reference_iteration_provider(trace, rows, {'calls': calls}, planned_iterations=2)
    assert [item['state'] for item in result['iterations']] == ['matched', 'matched']
    assert result['unattributed_provider_bindings'] == []
