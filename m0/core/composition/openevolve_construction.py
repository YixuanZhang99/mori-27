"""Source-bound OpenEvolve diff materialization through the existing M7 loop."""
from __future__ import annotations

import hashlib
from dataclasses import asdict

from core.composition.construction import ConstructionPlan, ConstructionResult, PromptMaterializer, _ref
from core.executor.types import CostVec
# Initialize the repository-pinned vendored package path.
from core.openevolve_interop import ProgramDatabase as _ProgramDatabase  # noqa: F401
from openevolve.utils.code_utils import (
    _split_evolve_regions, apply_diff_blocks, enforce_evolve_blocks, extract_diffs,
)


class OpenEvolveMaterializer(PromptMaterializer):
    def __init__(self, roles, *, seed_program, max_attempts=2):
        if max_attempts != 2 or type(max_attempts) is not int:
            raise ValueError('OpenEvolve requires exactly two bounded construction attempts')
        if type(seed_program) is not str or not seed_program.strip():
            raise ValueError('OpenEvolve requires the frozen seed program')
        regions = _split_evolve_regions(seed_program)
        if regions is None or not regions[1]:
            raise ValueError('OpenEvolve seed requires well-formed evolve markers')
        self.seed_program = seed_program
        super().__init__(roles, max_attempts=max_attempts)

    @property
    def manifest_binding(self):
        manifest = super().manifest_binding
        manifest['kind'] = 'openevolve_diff_materializer_v1'
        manifest['configuration']['seed_program_ref'] = 'sha256:' + hashlib.sha256(
            self.seed_program.encode('utf-8')).hexdigest()
        manifest['configuration']['wire_format'] = 'search_replace_v1'
        return manifest

    def _parent(self, plan_value):
        parents = plan_value['recipe']['parent_artifacts']
        if len(parents) != 1 or len(plan_value['candidate']['parents']) != 1:
            raise ValueError('OpenEvolve mutation requires one fixed parent')
        if parents[0]['candidate_id'] != plan_value['candidate']['parents'][0]:
            raise ValueError('OpenEvolve parent binding differs')
        source = parents[0]['artifact']
        regions = _split_evolve_regions(source)
        if regions is None or not regions[1]:
            raise ValueError('OpenEvolve parent requires well-formed evolve markers')
        return source

    def build_request(self, plan_value, *, hypothesis, attempt, feedback):
        self._parent(plan_value)
        request = super().build_request(plan_value, hypothesis=hypothesis, attempt=attempt, feedback=feedback)
        request['output_contract']['artifact'] = 'SEARCH/REPLACE diff only'
        request['response_instruction'] = ('Return only SEARCH/REPLACE diff blocks. '
            'Use the fixed parent program. Keep all EVOLVE-BLOCK markers unchanged. '
            'Only edits inside those blocks are retained; do not return JSON or a full rewrite.')
        return request

    def decode_output(self, raw, plan_value):
        parent = self._parent(plan_value)
        if type(raw) is not str or len(raw) > 1024 * 1024:
            raise ValueError('OpenEvolve diff must be bounded text')
        blocks = extract_diffs(raw)
        if not blocks:
            raise ValueError('no valid SEARCH/REPLACE blocks')
        patched, matched = apply_diff_blocks(parent, blocks)
        if not matched:
            raise ValueError('no SEARCH block matched the fixed parent')
        if patched == parent:
            raise ValueError('diff did not change the fixed parent')
        patched = enforce_evolve_blocks(parent, patched)
        if patched == parent:
            raise ValueError('diff contains no change within evolve markers')
        return {'artifact': patched, 'hypothesis': plan_value['candidate']['hypothesis']}

    async def construct(self, plan, provider):
        if not isinstance(plan, ConstructionPlan) or not callable(provider):
            raise ValueError('materializer requires a construction plan and provider')
        value = plan.to_dict()
        if value['recipe']['parent_artifacts']:
            if not value['spec']['hypothesis_frozen']:
                raise ValueError('OpenEvolve mutation requires a frozen hypothesis')
            return await super().construct(plan, provider)
        role = self.roles.get(value['spec']['role'])
        if role is None or asdict(role) != value['role']:
            raise ValueError('construction role definition changed after plan binding')
        if value['candidate']['parents'] or value['recipe']['kind'] != 'draft':
            raise ValueError('OpenEvolve seed requires a parentless draft')
        hypothesis = value['candidate']['hypothesis']
        return ConstructionResult.from_dict({'schema_version': 1, 'plan_ref': plan.ref,
            'candidate': value['candidate'], 'artifact': self.seed_program, 'role': value['role'],
            'spec_ref': _ref(value['spec']), 'projection_ref': value['projection_ref'],
            'initial_hypothesis': hypothesis, 'effective_hypothesis': hypothesis,
            'cost': asdict(CostVec(tokens_in=0, node_count=1)),
            'measured_cost_units': ['token', 'node', 'eval_count'],
            'attempts': [{'attempt': 1, 'status': 'complete', 'hypothesis': hypothesis,
                          'known_tokens': 0, 'feedback': []}]}).validate_for(plan)
