"""Pure request bytes and sanitized measured responses; no dispatch or authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

from zoo.mle_bench_lite.cny_budget import validate_detailed_usage


def build_request(prompt: str, binding: dict) -> bytes:
    """Preserve the existing canonical OpenAI/DeepSeek body exactly."""
    if type(prompt) is not str or not prompt.strip():
        raise ValueError('provider prompt must be nonempty')
    model = binding.get('requested_model')
    allowance = binding.get('max_completion_tokens')
    if type(model) is not str or not model.strip() or type(allowance) is not int or allowance <= 0:
        raise ValueError('provider request requires model and positive output allowance')
    kind = binding.get('request_format', 'openai')
    mode = binding.get('message_mode', 'single_user_v1')
    if mode == 'single_user_v1':
        messages = [{'role': 'user', 'content': prompt}]
    elif mode == 'openevolve_v1':
        from core.x1.checkpoint import payload_digest
        try:
            request = json.loads(prompt)
            vendor = request['vendor_messages']
            instruction = request['response_instruction']
            feedback = request['repair_feedback']
            if type(vendor) is not dict or set(vendor) != {'system', 'user'} or \
                    any(type(vendor[k]) is not str or not vendor[k].strip() for k in vendor) or \
                    request['vendor_prompt_ref'] != 'sha256:' + payload_digest(vendor) or \
                    type(instruction) is not str or not instruction.strip() or \
                    type(feedback) is not list or any(type(v) is not str for v in feedback):
                raise ValueError('invalid bound OpenEvolve messages')
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise ValueError('invalid bound OpenEvolve messages') from error
        suffix = '\n\n' + instruction
        if feedback:
            suffix += '\nRepair feedback:\n' + '\n'.join(feedback)
        messages = [{'role': 'system', 'content': vendor['system']},
                    {'role': 'user', 'content': vendor['user'] + suffix}]
    elif mode == 'openevolve_host_v1':
        from core.x1.checkpoint import payload_digest
        try:
            request = json.loads(prompt)
            vendor = request['host_messages']
            if type(request) is not dict or set(request) != {'host_messages', 'host_prompt_ref'} or \
                    type(vendor) is not dict or set(vendor) != {'system', 'user'} or \
                    any(type(vendor[key]) is not str or not vendor[key].strip() for key in vendor) or \
                    request['host_prompt_ref'] != 'sha256:' + payload_digest(vendor):
                raise ValueError('invalid bound host messages')
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise ValueError('invalid bound host messages') from error
        messages = [{'role': 'system', 'content': vendor['system']},
                    {'role': 'user', 'content': vendor['user']}]
    else:
        raise ValueError('unsupported provider message mode')
    payload = {'model': model, 'messages': messages}
    if kind == 'deepseek':
        effort = binding.get('reasoning_effort', 'high')
        if type(effort) is not str or effort not in {'none', 'low', 'high', 'max'}:
            raise ValueError('reasoning effort must be none, low, high or max')
        payload.update(max_tokens=allowance, stream=False,
                       thinking={'type': 'disabled' if effort == 'none' else 'enabled'}, reasoning_effort=effort)
    elif kind == 'openai':
        temperature = binding.get('temperature', 0.0)
        if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError('provider request temperature must be finite and in [0,2]')
        payload.update(temperature=temperature, max_completion_tokens=allowance)
    else:
        raise ValueError('unsupported provider request protocol')
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@dataclass(frozen=True)
class ParsedProviderResponse:
    """Known physical usage survives content and provider-contract failures."""
    response_sha256: str
    returned_model: str | None
    _usage_json: str | None
    result: str | None
    finish_reason: str | None
    integrity_reason: str | None

    @property
    def usage(self):
        return json.loads(self._usage_json) if self._usage_json is not None else None

    def to_dict(self):
        return {'response_sha256': self.response_sha256, 'returned_model': self.returned_model,
                'usage': self.usage, 'result': self.result, 'finish_reason': self.finish_reason,
                'integrity_reason': self.integrity_reason}


def parse_response(raw: bytes, binding: dict) -> ParsedProviderResponse:
    """Never infer unknown usage or discard a known bill after a bad response."""
    if type(raw) is not bytes:
        raise TypeError('provider response must be bytes')
    digest = hashlib.sha256(raw).hexdigest()
    def outcome(reason, *, model=None, usage=None, result=None, finish=None):
        return ParsedProviderResponse(digest, model,
            json.dumps(usage, sort_keys=True, allow_nan=False) if usage is not None else None,
            result, finish, reason)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return outcome('invalid_json')
    if type(data) is not dict:
        return outcome('invalid_response')
    model = data.get('model')
    model = model if type(model) is str and model.strip() else None
    raw_usage = data.get('usage')
    if type(raw_usage) is not dict or type(raw_usage.get('total_tokens')) is not int or raw_usage['total_tokens'] < 0:
        return outcome('invalid_usage', model=model)
    # A trustworthy total remains useful even if detailed pricing is impossible.
    usage = {'total_tokens': raw_usage['total_tokens']}
    details_valid = True
    try:
        usage = validate_detailed_usage(raw_usage)
    except ValueError:
        details_valid = False
    try:
        finish = data['choices'][0]['finish_reason']
    except (KeyError, IndexError, TypeError):
        finish = None
    if type(finish) is not str or finish not in {'stop', 'length', 'content_filter',
                                               'tool_calls', 'insufficient_system_resource'}:
        finish = None
    reason = None
    if model != binding.get('requested_model'):
        reason = 'model_mismatch'
    elif not details_valid:
        reason = 'invalid_usage_details'
    elif usage['prompt_tokens'] > binding['input_capacity']:
        reason = 'input_bound_exceeded'
    elif usage['completion_tokens'] > binding['max_completion_tokens']:
        reason = 'output_bound_exceeded'
    elif finish != 'stop':
        reason = 'incomplete_output'
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        content = None
    if reason is None and (type(content) is not str or not content.strip()):
        reason = 'invalid_content'
    return outcome(reason, model=model, usage=usage,
                   result=content if reason is None else None, finish=finish)
