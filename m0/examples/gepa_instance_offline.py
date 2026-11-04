"""Public Framework instance-selection fixture; not a GEPA benchmark."""
from __future__ import annotations

import json
import tempfile

from core.composition.defaults import composed_profile
from core.composition.evaluation import EvaluationContract, ItemOutcome, binding_for
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.loop import Framework, LoopConfig


class Provider:
    model = 'synthetic-provider'
    supplier = 'offline-fixture'
    def __init__(self):
        self.calls = 0
    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {'total_tokens': 1}
        return 'synthetic candidate ' + str(self.calls)


class Domain:
    evaluator_version = 'synthetic-instance-v1'
    evaluation_context = 'sha256:' + 'a' * 64
    def validate_request(self, request):
        request.validate()
        if request.split_id != 'dev' or request.fidelity != 'dev':
            raise ValueError('fixture supports only development evaluation')
    async def evaluate(self, proposal, request):
        self.validate_request(request)
        cycle = proposal.candidate.created_cycle
        items = (ItemOutcome('left', int(cycle % 2 == 0), visibility='public'),
                 ItemOutcome('right', int(cycle % 2 == 1), visibility='public'))
        return EvalResult(EvalStatus.OK, {'dev/score': 0.5}, CostVec(eval_count=1),
            fidelity=request.fidelity, text_feedback='Synthetic fixture feedback.',
            contract=EvaluationContract(binding_for(proposal, request, evaluator_version=self.evaluator_version,
                evaluation_context=self.evaluation_context), ('token', 'node', 'eval_count'), items=items))


def main():
    profile = composed_profile(name='gepa-instance-offline-fixture')
    profile['domain'] = {'name': 'native'}
    profile['policy'] = {'name': 'gepa_instance', 'options': {'items': ['left', 'right'], 'seed': 9}}
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {level: {'token': 1000, 'node': 20, 'eval_count': 20}
                   for level in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
                                   'operator': {'token': 10, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}}
    with tempfile.TemporaryDirectory(prefix='mori-gepa-instance-') as directory:
        provider = Provider()
        fw = Framework.from_profile(profile, provider, Domain(),
            LoopConfig(max_generations=3, total_budget=1000, intent_cost=1, reeval_floor=0), directory)
        result = fw.evolve('Synthetic public instance selection')
        frontier = fw._composed.parts['policy'].instance_frontier
        print(json.dumps({'runtime': result['runtime'], 'candidates': len(frontier.checkpoint_state()['candidates']),
            'instances': list(frontier.winners()), 'provider_calls': provider.calls,
            'external_model_requests': 0, 'benchmark_result': False,
            'notice': 'Instance-selection fixture only; not a full GEPA reproduction.'}))


if __name__ == '__main__':
    main()
