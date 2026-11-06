"""Opt-in OpenEvolve message transport preserves upstream roles and provenance."""
import json

import pytest

from core.x1.checkpoint import payload_digest
from zoo.mle_bench_lite.provider_protocol import build_request


def binding(**changes):
    return {'requested_model': 'deepseek-flash', 'request_format': 'deepseek',
            'max_completion_tokens': 16, 'message_mode': 'openevolve_v1', **changes}


def prompt():
    messages = {'system': 'vendor system', 'user': 'vendor user'}
    return json.dumps({'vendor_messages': messages, 'vendor_prompt_ref': 'sha256:' + payload_digest(messages),
                       'response_instruction': 'Return a diff.', 'repair_feedback': ['fix mismatch']})


def test_opt_in_sends_vendor_roles_and_repair_feedback():
    wire = json.loads(build_request(prompt(), binding()))
    assert wire['messages'][0] == {'role': 'system', 'content': 'vendor system'}
    assert wire['messages'][1]['role'] == 'user'
    assert wire['messages'][1]['content'].startswith('vendor user')
    assert 'Return a diff.' in wire['messages'][1]['content']
    assert 'fix mismatch' in wire['messages'][1]['content']


@pytest.mark.parametrize('value', ['ordinary user request', '{}', '{"vendor_messages":{}}'])
def test_opt_in_rejects_unbound_prompt(value):
    with pytest.raises(ValueError):
        build_request(value, binding())


def test_governed_provider_requires_original_argument_for_two_role_dispatch():
    from zoo.mle_bench_lite.cny_budget import POLICY
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    campaign = {**POLICY, 'campaign_id': 'fixture-campaign', 'limit_micro_cny': 200000000,
                'policy_sha256': 'a' * 64}
    provider = GovernedCNYProvider('deepseek-flash', 'http://127.0.0.1:12345/v1',
        campaign_binding=campaign, max_completion_tokens=16, api_key='fixture-only',
        message_mode='openevolve_v1')
    body = provider.prepare_request(prompt())
    assert provider.manifest_binding()['message_mode'] == 'openevolve_v1'
    provider.validate_dispatch(body, prompt=prompt())
    with pytest.raises(ValueError):
        provider.validate_dispatch(body)
    with pytest.raises(ValueError):
        provider.validate_dispatch(body, prompt=prompt().replace('vendor user', 'other'))
    changed = json.loads(body)
    changed['messages'][0]['content'] = 'tampered system'
    with pytest.raises(ValueError):
        provider.validate_dispatch(json.dumps(changed, sort_keys=True, separators=(',', ':')).encode(),
                                   prompt=prompt())
