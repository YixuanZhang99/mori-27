"""Fresh DeepSeek transport sessions for the independently admitted CNY bridge.

This adapter does not reserve, settle, retry, or publish durable outcomes. The
registered bridge must obtain both admissions and persist results. Direct calls
are refused; perform_request is the bridge's single-attempt transport primitive.
"""
from __future__ import annotations

import copy
import json
import math
import urllib.parse
import urllib.request

from core.llm import UsageError
from zoo.mle_bench_lite.cny_budget import POLICY
from zoo.mle_bench_lite.provider_protocol import build_request, parse_response
from zoo.mle_bench_lite.token_admission import admission_policy


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise UsageError('provider redirects are forbidden')


class GovernedCNYProvider:
    supplier = 'deepseek-governed-capacity-v1'

    def __init__(self, model, base_url, *, campaign_binding, max_completion_tokens=4096,
                 timeout=120.0, api_key=None, token_admission='model_capacity_v1',
                 phase_call_limits=None, reasoning_effort='high'):
        if type(reasoning_effort) is not str or reasoning_effort not in {'low', 'high', 'max'}:
            raise ValueError('reasoning effort must be low, high or max')
        if type(model) is not str or not model.strip():
            raise ValueError('an explicit model is required')
        if type(base_url) is not str:
            raise ValueError('provider URL must be text')
        url = urllib.parse.urlsplit(base_url)
        local = url.hostname in {'localhost', '127.0.0.1', '::1'}
        if not url.hostname or url.username or url.password or url.query or url.fragment or \
                url.scheme not in {'https', 'http'} or url.scheme == 'http' and not local:
            raise ValueError('provider URL requires HTTPS except loopback fixtures')
        if type(max_completion_tokens) is not int or max_completion_tokens <= 0:
            raise ValueError('output allowance must be a positive integer')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        if type(campaign_binding) is not dict:
            raise ValueError('frozen campaign binding is required')
        if set(campaign_binding) != set(POLICY) | {'campaign_id', 'limit_micro_cny', 'policy_sha256'} or \
                any(campaign_binding[key] != value for key, value in POLICY.items()):
            raise ValueError('frozen campaign policy has unsupported fields or values')
        campaign = json.loads(json.dumps(campaign_binding, sort_keys=True, allow_nan=False))
        if model != campaign.get('model') or type(campaign.get('context_tokens')) is not int or \
                campaign['context_tokens'] <= 0 or type(campaign.get('max_output_tokens')) is not int or \
                max_completion_tokens > campaign['max_output_tokens'] or \
                (not local and base_url.rstrip('/') != campaign.get('provider_base_url')):
            raise ValueError('provider differs from frozen campaign capacity or identity')
        if token_admission != 'model_capacity_v1':
            raise ValueError('governed provider requires hard service capacity admission')
        limits = {'operator': 1, 'evaluation': 0} if phase_call_limits is None else copy.deepcopy(phase_call_limits)
        if type(limits) is not dict or set(limits) != {'operator', 'evaluation'} or \
                any(type(value) is not int for value in limits.values()) or \
                limits['operator'] < 1 or limits['evaluation'] < 0:
            raise ValueError('provider requires finite phase call limits')
        if api_key is not None and (type(api_key) is not str or not api_key.strip()):
            raise ValueError('provider key must be nonempty text when supplied')
        self._api_key = api_key
        self._manifest = {'schema_version': 1, 'requested_model': model,
            'base_url': base_url.rstrip('/'), 'max_completion_tokens': max_completion_tokens,
            'timeout': float(timeout), 'request_format': 'deepseek', 'retry_policy': 'never',
            'response_model_required': True, 'thinking': {'type': 'enabled'},
            'reasoning_effort': reasoning_effort, 'temperature_applied': False, 'seed_applied': False,
            'immutable_snapshot_verified': False, 'campaign': campaign,
            'token_admission': admission_policy(token_admission, campaign),
            'phase_call_limits': limits}
        self.last_usage = {'total_tokens': 0}
        self._unresolved = False
        self._integrity_failure = False

    def manifest_binding(self):
        return copy.deepcopy(self._manifest)

    def protocol_binding(self):
        return {'requested_model': self._manifest['requested_model'],
            'request_format': 'deepseek', 'base_url': self._manifest['base_url'],
            'reasoning_effort': self._manifest['reasoning_effort'],
            'max_completion_tokens': self._manifest['max_completion_tokens'],
            'input_capacity': self._manifest['campaign']['context_tokens'],
            'token_admission': copy.deepcopy(self._manifest['token_admission'])}

    def governance_binding(self):
        wire = json.loads(self.prepare_request('binding'))
        wire.pop('messages')
        # Transport parameters and policy identity also freeze the adapter;
        # neither a temperature nor an unused remote seed is asserted applied.
        wire.update(base_url=self._manifest['base_url'], timeout=self._manifest['timeout'],
                    policy_sha256=self._manifest['campaign'].get('policy_sha256'))
        return {'schema_version': 2, 'fresh_session': True, 'state_independent': True,
            'sampling': {'method': 'supplier_unverified', 'parameters': wire, 'applied': True},
            'call_bound': {'kind': 'hard', 'units': {'token':
                self._manifest['campaign']['context_tokens'] + self._manifest['max_completion_tokens']}},
            'external_currency': {'schema_version': 1, 'bridge': 'cny_invocation_v1'},
            'phase_call_limits': copy.deepcopy(self._manifest['phase_call_limits'])}

    def __call__(self, *_args, **_kwargs):
        raise UsageError('governed provider requires a bound external bridge invocation')

    def prepare_request(self, prompt):
        return build_request(prompt, self.protocol_binding())

    def validate_dispatch(self, body):
        """Pure pre-dispatch checks; bridge may call this before reserving CNY."""
        if self._unresolved:
            raise UsageError('provider has unresolved earlier operation')
        if self._integrity_failure:
            raise UsageError('provider session has a prior integrity failure')
        if not self._api_key:
            raise ValueError('provider key is required before dispatch')
        try:
            data = json.loads(body) if type(body) is bytes else None
            prompt = data['messages'][0]['content']
            expected = self.prepare_request(prompt)
        except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
            raise ValueError('wire request differs from frozen provider protocol') from None
        if body != expected:
            raise ValueError('wire request differs from frozen provider protocol')

    def perform_request(self, body):
        """Make one HTTP attempt; durable admission/recovery belongs to bridge."""
        if not self._unresolved and not self._integrity_failure:
            self.last_usage = {'total_tokens': 0}
        self.validate_dispatch(body)
        request = urllib.request.Request(self._manifest['base_url'] + '/chat/completions',
            data=body, method='POST', headers={
                'Authorization': 'Bearer ' + self._api_key, 'Content-Type': 'application/json'})
        self.last_usage = None
        self._unresolved = True
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request,
                    timeout=self._manifest['timeout']) as response:
                raw = response.read()
        except Exception:
            raise UsageError('provider operation has unknown usage (transport_error)') from None
        parsed = parse_response(raw, self.protocol_binding())
        self.last_usage = parsed.usage
        self._unresolved = parsed.usage is None
        self._integrity_failure = parsed.integrity_reason not in {
            None, 'invalid_content', 'incomplete_output'}
        return parsed
