"""Bound effort is part of canonical requests; original currency limits remain fixed."""
import json
from types import SimpleNamespace

import pytest

from test_governed_cny_provider import binding, local_endpoint, protocol, provider, reply


def test_low_effort_reaches_wire_and_frozen_governance_without_changing_cost_bound():
    endpoint = SimpleNamespace(url='http://127.0.0.1:1/v1')
    default = provider(endpoint)
    low = provider(endpoint, reasoning_effort='low')
    wire = json.loads(low.prepare_request('produce a program'))
    assert wire['reasoning_effort'] == 'low'
    assert wire['thinking'] == {'type': 'enabled'}
    assert low.manifest_binding()['reasoning_effort'] == 'low'
    assert low.governance_binding()['sampling']['parameters']['reasoning_effort'] == 'low'
    assert low.governance_binding()['call_bound'] == default.governance_binding()['call_bound']
    assert low.manifest_binding()['campaign'] == default.manifest_binding()['campaign']
    assert json.loads(default.prepare_request('produce a program'))['reasoning_effort'] == 'high'
    with pytest.raises(ValueError, match='frozen provider protocol'):
        low.validate_dispatch(default.prepare_request('produce a program'))


def test_pure_request_encoder_uses_bound_effort():
    assert json.loads(protocol().build_request('hello', binding(reasoning_effort='low')))['reasoning_effort'] == 'low'


@pytest.mark.parametrize('bad', ['medium', 'none', '', True, None, []])
def test_unsupported_effort_is_rejected_before_dispatch(bad):
    with pytest.raises(ValueError, match='reasoning effort'):
        protocol().build_request('hello', binding(reasoning_effort=bad))
    with pytest.raises(ValueError, match='reasoning effort'):
        provider(SimpleNamespace(url='http://127.0.0.1:1/v1'), reasoning_effort=bad)


def test_low_effort_real_loopback_keeps_measured_usage(local_endpoint):
    local_endpoint.responses.append(reply())
    low = provider(local_endpoint, reasoning_effort='low')
    result = low.perform_request(low.prepare_request('produce a program'))
    assert result.result == 'answer'
    assert result.usage['total_tokens'] == 7
    assert json.loads(local_endpoint.requests[0])['reasoning_effort'] == 'low'

