"""Only uniquely matched provider calls may be attributed to an iteration."""
import copy

import pytest

from zoo.circle_packing.reference_iteration_trace import audit_reference_iteration_provider


def test_unique_provider_request_is_linked_and_duplicate_prompt_is_ambiguous():
    digest, binding, call_id = 'a' * 64, 'b' * 64, 'c' * 64
    context = {'lane': 'main', 'argument_sha256': digest, 'intent_id': 'host-dispatch:fixture'}
    trace = {'prompt_bindings': [{'iteration': 1, 'request_sha256': digest}]}
    rows = [{'kind': 'composed_provider_started', 'payload': {'request_sha256': digest, 'binding': binding,
              'invocation': {'external_context': context}}},
            {'kind': 'composed_provider_completed', 'payload': {'binding': binding, 'tokens': 7}}]
    bundle = {'calls': [{'prepared': {'context': context, 'call_id': call_id},
                         'outcome': {'call_id': call_id, 'usage': {'total_tokens': 7}}}]}
    result = audit_reference_iteration_provider(trace, rows, bundle, planned_iterations=2)
    assert result['iterations'][0]['state'] == 'matched'
    assert result['iterations'][0]['call_id'] == call_id
    duplicate = {'prompt_bindings': trace['prompt_bindings'] + [{'iteration': 2, 'request_sha256': digest}]}
    assert all(item['state'] == 'ambiguous' for item in
               audit_reference_iteration_provider(duplicate, rows, bundle, planned_iterations=2)['iterations'])
    altered = copy.deepcopy(bundle)
    altered['calls'][0]['outcome']['usage']['total_tokens'] = 8
    with pytest.raises(ValueError, match='provider'):
        audit_reference_iteration_provider(trace, rows, altered, planned_iterations=2)
