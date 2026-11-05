"""Installed-package M7 example: one managed Git artifact, multiple split evaluations.

Usage: python configured_execution_offline.py --workdir /new/absolute/directory
No test imports, network, credentials or caller-repository snapshot are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from core.composition.defaults import execution_profile
from core.composition.evaluation import binding_for
from core.executor.evaluation_contract import EvaluationContract
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.loop import Framework, LoopConfig


class LocalConstructor:
    model = 'offline-construction-fixture-v1'
    supplier = 'offline-simulation'

    def __init__(self, forbidden=False):
        self.index, self.calls, self.forbidden = 0, 0, forbidden

    def __call__(self, prompt):
        if self.forbidden:
            raise AssertionError('recorded replay invoked the model')
        value = json.loads(prompt)
        self.index += 1
        self.calls += 1
        self.last_usage = {'total_tokens': 5}
        return json.dumps({'artifact': 'candidate ' + str(self.index), 'hypothesis': value['hypothesis']})

    def checkpoint_state(self):
        return {'index': self.index}

    def restore_state(self, state):
        self.index = state['index']


class LocalDomain:
    evaluator_version = 'offline-git-artifact-domain-v1'
    measured_cost_units = ('token', 'node', 'eval_count')
    contexts = {name: 'sha256:' + hashlib.sha256(('fixture split ' + name).encode()).hexdigest()
                for name in ('dev', 'admission', 'final_audit')}
    evaluation_context = contexts['dev']

    def __init__(self, forbidden=False):
        self.forbidden = forbidden

    def validate_request(self, request):
        request.validate()
        if request.split_id not in self.contexts:
            raise ValueError('unsupported offline split')

    def evaluation_context_for(self, request):
        self.validate_request(request)
        return self.contexts[request.split_id]

    async def evaluate(self, proposal, request):
        if self.forbidden:
            raise AssertionError('recorded replay invoked a domain')
        self.validate_request(request)
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context_for(request))
        score = float(proposal.artifact.split()[-1])
        return EvalResult(EvalStatus.OK, {'dev/score': score}, CostVec(eval_count=1),
                          fidelity=request.fidelity,
                          contract=EvaluationContract(binding, self.measured_cost_units))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workdir')
    args = parser.parse_args(argv)
    temporary = tempfile.TemporaryDirectory(prefix='mori-configured-example-') if not args.workdir else None
    root = Path(args.workdir or temporary.name).absolute()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError('example requires an empty workdir')
    assembly = execution_profile()
    assembly['execution']['spec']['role'] = 'coder'
    task = 'Construct two offline text candidates; validate immutable Git provenance.'
    first = LocalConstructor()
    paused = Framework.from_profile(assembly, first, LocalDomain(),
        LoopConfig(max_generations=1, reeval_floor=0, stop_after_generation=0), str(root))
    paused.evolve(task)
    second = LocalConstructor()
    resumed = Framework.from_profile(assembly, second, LocalDomain(),
        LoopConfig(max_generations=1, reeval_floor=0, resume_from_checkpoint=True), str(root))
    resumed.evolve(task)
    rows = list(resumed.store.read('materialization_completed'))
    assert len(rows) == first.calls + second.calls == 2
    commits = []
    for row in rows:
        value = row['payload']; descriptor = value['artifact']
        repo = value['identity']['artifact_backend']['base_repo']
        raw = subprocess.check_output(['git', '-C', repo, 'show',
                                      descriptor['commit'] + ':' + descriptor['artifact_path']])
        assert raw == value['construction_result']['artifact'].encode()
        assert 'sha256:' + hashlib.sha256(raw).hexdigest() == descriptor['reference']
        commits.append(descriptor['commit'])
    before = list(resumed.store.read('governed_evaluation_completed'))
    replay = resumed.replay(adapter_factory=lambda path, store: (
        LocalConstructor(forbidden=True), LocalDomain(forbidden=True)))
    assert replay['replay_certificate']['passed']
    assert list(resumed.store.read('governed_evaluation_completed')) == before
    print(json.dumps({'runtime': resumed.inspect()['runtime'], 'artifacts': len(rows),
        'artifact_commits': commits, 'evaluations': len(before), 'generation_calls': first.calls + second.calls,
        'synthetic_generation_tokens': 10, 'external_provider_requests': 0,
        'recorded_replay_passed': True, 'notice': 'Offline fixture scores and usage; not a benchmark result.'}, indent=2))
    if temporary:
        temporary.cleanup()


if __name__ == '__main__':
    main()
