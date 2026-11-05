"""Offline best-fit OR3 development check via the public Framework API."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from core.composition.defaults import composed_profile
from core.loop import Framework, LoopConfig
from zoo.funsearch_binpacking.domain import OR3DevDomain

DEV_SHA256 = 'a99be58e4e5cf25986edcffd55f03928f47e82f2db00397eab72b9c1d73c19c3'
TEMPLATE = 'def priority(item, bins):\n    return -(bins - item)\n'


class OfflineProvider:
    model, supplier = 'offline-best-fit-fixture', 'offline-fixture'

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {'total_tokens': 1}
        return json.dumps({'artifact': TEMPLATE, 'hypothesis': json.loads(prompt)['hypothesis']})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dev_data', type=Path)
    args = parser.parse_args()
    raw = args.dev_data.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DEV_SHA256:
        raise ValueError('OR3 development data differs from the pinned split')
    cases = json.loads(raw)
    profile = composed_profile(name='funsearch-or3-offline-reference')
    profile.update(schema_version=2, domain={'name': 'native'},
        operators=[{'name': 'draft'}, {'name': 'funsearch'}],
        policy={'name': 'funsearch', 'options': {'case_ids': sorted(cases), 'islands': 2, 'seed': 7,
            'prompt_size': 2, 'temperature': 1.0, 'temperature_period': 10, 'metric': 'score',
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
    with tempfile.TemporaryDirectory(prefix='mori-or3-framework-') as workdir:
        provider = OfflineProvider()
        domain = OR3DevDomain(args.dev_data, expected_sha256=DEV_SHA256, template=TEMPLATE, timeout=30)
        framework = Framework.from_profile(profile, provider, domain,
            LoopConfig(max_generations=1, total_budget=1000, intent_cost=1, reeval_floor=0), workdir)
        result = framework.evolve('Offline reference best-fit on OR3 development cases')
        candidates = [row['payload'] for row in framework.store.read('funsearch_public_candidate')]
        means = [sum(row['scores'].values()) / len(row['scores']) for row in candidates]
        replay = framework.replay()['replay_certificate']['passed']
        if len(means) != 2 or means != [-213.9, -213.9] or not replay or provider.calls != 2:
            raise ValueError('offline OR3 reference check differed')
        print(json.dumps({'schema_version': 1, 'runtime': result['runtime'], 'dev_sha256': DEV_SHA256,
            'dev_cases': len(cases), 'candidate_mean_scores': means, 'recorded_replay_passed': replay,
            'external_model_requests': 0, 'model_benchmark_result': False,
            'notice': 'Pinned best-fit reference fixture; no held-out or model-generated result.'}, indent=2))


if __name__ == '__main__':
    main()
