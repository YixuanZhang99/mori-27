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


def _evolve_plan(parent=None):
    from core.composition.construction import ConstructionPlan
    from core.executor.types import Candidate, ExecutorSpec
    from test_construction import pack
    context = pack()
    parents = [] if parent is None else ['parent']
    candidate = Candidate('next', parents=parents, hypothesis='Use caching', context_pack_ref=context.ref)
    spec = ExecutorSpec('general', True, None, ['memory'])
    recipe = {'kind': 'draft' if parent is None else 'reflective', 'task_desc': 'Optimize program',
              'parent_artifacts': [] if parent is None else [{'candidate_id': 'parent', 'artifact': parent}],
              'instructions': ['Preserve the objective'], 'comparison': {}}
    return ConstructionPlan.create(candidate, recipe, spec, context, roles=ROLES)


PARENT = 'outside = 0\n# EVOLVE-BLOCK-START\nvalue = 1\n# EVOLVE-BLOCK-END\n'


def _diff(search, replacement):
    return f'<<<<<<< SEARCH\n{search}\n=======\n{replacement}\n>>>>>>> REPLACE\n'


def test_evolve_seed_is_exact_zero_token_construction_without_provider_calls():
    from core.composition.openevolve_construction import OpenEvolveMaterializer
    def forbidden(_):
        raise AssertionError('seed must never call provider')
    result = asyncio.run(OpenEvolveMaterializer(ROLES, seed_program=PARENT).construct(_evolve_plan(), forbidden))
    assert result.artifact == PARENT and result.cost.tokens_in == 0
    result.validate_for(_evolve_plan())


def test_evolve_partial_patch_follows_host_and_uses_fixed_parent():
    from core.composition.openevolve_construction import OpenEvolveMaterializer
    patch = _diff('value = 1', 'value = 2') + _diff('missing = 1', 'missing = 2')
    provider = Scripted([(patch, 9)])
    result = asyncio.run(OpenEvolveMaterializer(ROLES, seed_program=PARENT).construct(
        _evolve_plan(PARENT), MeteredProvider(provider)))
    assert result.artifact == PARENT.replace('value = 1', 'value = 2')
    assert result.cost.tokens_in == 9
    assert provider.requests[0]['output_contract']['artifact'] == 'SEARCH/REPLACE diff only'


def test_evolve_patch_failures_exhaust_same_parent_attempts_and_charge_all():
    import pytest
    from core.composition.contracts import OperatorFailure
    from core.composition.openevolve_construction import OpenEvolveMaterializer
    for invalid in ('not a diff', _diff('missing', 'changed'), _diff('value = 1', 'value = 1'),
                    _diff('outside = 0', 'outside = 7'),
                    _diff('# EVOLVE-BLOCK-END', '# removed')):
        provider = Scripted([(invalid, 3), (invalid, 5)])
        with pytest.raises(OperatorFailure) as failure:
            asyncio.run(OpenEvolveMaterializer(ROLES, seed_program=PARENT).construct(
                _evolve_plan(PARENT), MeteredProvider(provider)))
        assert failure.value.cost.tokens_in == 8
        assert len(provider.requests) == 2
        assert all(row['recipe']['parent_artifacts'][0]['artifact'] == PARENT for row in provider.requests)


def test_evolve_retry_repairs_diff_against_same_parent_and_keeps_usage():
    from core.composition.openevolve_construction import OpenEvolveMaterializer
    bad = _diff('not present', 'changed')
    good = _diff('value = 1', 'value = 4')
    provider = Scripted([(bad, 3), (good, 5)])
    result = asyncio.run(OpenEvolveMaterializer(ROLES, seed_program=PARENT).construct(
        _evolve_plan(PARENT), MeteredProvider(provider)))
    assert result.artifact == PARENT.replace('value = 1', 'value = 4')
    assert result.cost.tokens_in == 8
    assert len(result.to_dict()['attempts']) == 2
    assert provider.requests[1]['repair_feedback']
    assert all(row['recipe']['parent_artifacts'][0]['artifact'] == PARENT for row in provider.requests)


def test_evolve_rejects_missing_parent_markers_before_calling_provider():
    import pytest
    from core.composition.openevolve_construction import OpenEvolveMaterializer
    provider = Scripted([(_diff('value = 1', 'value = 2'), 3)])
    with pytest.raises(ValueError, match='markers'):
        asyncio.run(OpenEvolveMaterializer(ROLES, seed_program=PARENT).construct(
            _evolve_plan('value = 1\n'), MeteredProvider(provider)))
    assert not provider.requests
