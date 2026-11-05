"""Construction seams required by the source-bound OpenEvolve diff recipe."""
import asyncio
import json

from core.composition.construction import PromptMaterializer
from core.composition.provider import MeteredProvider
from test_construction import ROLES, Scripted, plan, response


def test_materializer_seams_reuse_measured_repair_loop_and_frozen_hypothesis():
    class DiffFixture(PromptMaterializer):
        def build_request(self, plan_value, *, hypothesis, attempt, feedback):
            result = super().build_request(plan_value, hypothesis=hypothesis, attempt=attempt, feedback=feedback)
            result['wire_format'] = 'diff_fixture'
            return result

        def decode_output(self, raw, plan_value):
            if raw == 'invalid patch':
                raise ValueError('patch did not match fixed parent')
            return {'artifact': 'patched program', 'hypothesis': 'Use caching'}

    provider = Scripted([('invalid patch', 7), (response(), 9)])
    result = asyncio.run(DiffFixture(ROLES, max_attempts=2).construct(plan(), MeteredProvider(provider)))
    assert result.artifact == 'patched program'
    assert result.cost.tokens_in == 16
    assert [row['wire_format'] for row in provider.requests] == ['diff_fixture', 'diff_fixture']
    assert provider.requests[1]['repair_feedback'] == ['patch did not match fixed parent']
    assert all(row['hypothesis'] == 'Use caching' for row in provider.requests)


def test_default_materializer_request_bytes_and_manifest_remain_unchanged():
    from core.composition.construction import _json
    value = plan()
    data = value.to_dict()
    requests = []
    class Capture:
        last_usage = {'total_tokens': 1}
        def __call__(self, raw):
            requests.append(raw)
            self.last_usage = {'total_tokens': 1}
            return response()
    expected = {'schema_version': 1, 'plan_ref': value.ref, 'role': data['role'],
                'recipe': data['recipe'], 'context': data['projection'], 'hypothesis': 'Use caching',
                'hypothesis_frozen': True, 'attempt': 1, 'repair_feedback': [],
                'output_contract': {'artifact': 'nonempty text',
                                    'hypothesis': 'Copy the input hypothesis exactly, without any changes.'}}
    materializer = PromptMaterializer(ROLES)
    asyncio.run(materializer.construct(value, MeteredProvider(Capture())))
    assert requests == [_json(expected)]
    assert materializer.manifest_binding['kind'] == 'prompt_materializer_v1'
    assert 'explicit_json_output' not in materializer.manifest_binding['configuration']
