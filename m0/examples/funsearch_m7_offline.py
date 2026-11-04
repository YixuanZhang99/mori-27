"""A local M7 FunSearch lifecycle fixture, not a benchmark or sandbox."""
from __future__ import annotations

import hashlib
import json
import tempfile

from core.composition.defaults import composed_profile
from core.composition.evaluation import EvaluationContract, ItemOutcome, binding_for
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.loop import Framework, LoopConfig

TEMPLATE = 'def priority(x):\n    return x\n'


class FixtureProvider:
    model = 'synthetic-provider'
    supplier = 'offline-fixture'

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {'total_tokens': 1}
        request = json.loads(prompt)
        return json.dumps({'artifact': f'def priority(x):\n    return x + {self.calls}\n',
                           'hypothesis': request['hypothesis']})


class FixtureDomain:
    evaluator_version = 'synthetic-funsearch-v1'
    evaluation_context = 'sha256:' + 'a' * 64

    def validate_request(self, request):
        request.validate()
        if request.split_id != 'dev' or request.fidelity != 'dev':
            raise ValueError('fixture supports only development evaluation')

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        cycle = proposal.candidate.created_cycle
        items = (ItemOutcome('left', metrics={'quality': .2 + cycle * .01}, visibility='public'),
                 ItemOutcome('right', metrics={'quality': .4 + cycle * .01}, visibility='public'))
        return EvalResult(EvalStatus.OK, {'dev/score': .3 + cycle * .01}, CostVec(eval_count=1),
            fidelity=request.fidelity, contract=EvaluationContract(
                binding_for(proposal, request, evaluator_version=self.evaluator_version,
                            evaluation_context=self.evaluation_context),
                ('token', 'node', 'eval_count'), items=items))


def main():
    profile = composed_profile(name='funsearch-m7-offline-fixture')
    profile.update(schema_version=2, domain={'name': 'native'},
        operators=[{'name': 'draft'}, {'name': 'funsearch'}],
        policy={'name': 'funsearch', 'options': {
            'case_ids': ['left', 'right'], 'islands': 2, 'seed': 7, 'prompt_size': 2,
            'temperature': 1.0, 'temperature_period': 10, 'metric': 'quality',
            'template': TEMPLATE, 'template_ref': 'sha256:' + hashlib.sha256(TEMPLATE.encode()).hexdigest(),
            'function_name': 'priority', 'reset_interval': 2}},
        execution={'schema_version': 1, 'spec': {'role': 'coder', 'hypothesis_frozen': True,
            'context_projection': []}, 'constructor': {'name': 'funsearch_prompt',
            'options': {'template': TEMPLATE, 'function_name': 'priority'}}})
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {level: {'token': 1000, 'node': 20, 'eval_count': 20}
                   for level in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
                                   'operator': {'token': 10, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}}
    with tempfile.TemporaryDirectory(prefix='mori-funsearch-m7-') as directory:
        provider = FixtureProvider()
        fw = Framework.from_profile(profile, provider, FixtureDomain(),
            LoopConfig(max_generations=2, total_budget=1000, intent_cost=1, reeval_floor=0), directory)
        result = fw.evolve('Synthetic public program selection')
        print(json.dumps({'runtime': result['runtime'], 'provider_calls': provider.calls,
            'public_candidates': len(list(fw.store.read('funsearch_public_candidate'))),
            'selections': len(list(fw.store.read('funsearch_selection'))),
            'replay_passed': fw.replay()['replay_certificate']['passed'],
            'external_model_requests': 0, 'benchmark_result': False,
            'notice': 'Offline lifecycle fixture; generated programs are not executed.'}))


if __name__ == '__main__':
    main()
