"""Offline OpenEvolve circle recipe; fixture runs are not benchmark results."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path

from core.loop import Framework, LoopConfig
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.profile import build_profile
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.recipe_support import source_identity
from zoo.mle_bench_lite.agent_common import _atomic_json

TASK = 'Improve the arrangement of 26 circles in a square'


class FixtureProvider:
    """Deterministic patch fixture; does not contact a provider."""
    model, supplier = 'circle-fixture', 'offline'

    def __init__(self):
        self.calls = 0
        self.last_usage = None

    def __call__(self, prompt):
        json.loads(prompt)
        self.calls += 1
        self.last_usage = {'total_tokens': 7}
        return ('<<<<<<< SEARCH\n    n = 26\n=======\n'
                f'    n = 26\n    # fixture mutation {self.calls}\n>>>>>>> REPLACE\n')


def run(output: Path, *, mode='fixture', seed=0, iterations=1, ledger=None, provider=None, runner=None):
    if mode != 'fixture' or ledger is not None:
        raise ValueError('live OpenEvolve runner requires completed governance and reference integration')
    if provider is not None and type(provider) is not FixtureProvider:
        raise ValueError('fixture mode accepts only its offline provider')
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('fixture runner requires PYTHONHASHSEED=0 at process start')
    profile = build_profile(seed=seed, iterations=iterations, call_token_bound=128, migration_interval=2)
    output = Path(output).resolve()
    source = source_identity()
    manifest = {'schema_version': 1, 'mode': mode, 'source': source, 'task': TASK,
                'profile': profile, 'seed': seed, 'iterations': iterations}
    manifest_ref = payload_digest(manifest)
    resume = output.exists() and any(output.iterdir())
    if resume:
        try:
            recorded = json.loads((output / 'manifest.json').read_text())
            terminal = json.loads((output / 'terminal.json').read_text())
        except (OSError, ValueError) as error:
            raise ValueError('fixture output has no complete terminal proof') from error
        if recorded != manifest or terminal.get('manifest_sha256') != manifest_ref or \
                terminal.get('report_sha256') != payload_digest(terminal.get('report')):
            raise ValueError('fixture terminal or frozen configuration differs')
    output.mkdir(parents=True, exist_ok=True)
    if not resume:
        _atomic_json(output / 'manifest.json', manifest)
    fixture = provider if provider is not None else FixtureProvider()
    domain = CirclePackingDomain(output / 'domain', runner=runner if runner is not None else SandboxRunner())
    config = LoopConfig(max_generations=iterations, total_budget=(iterations + 1) * 256,
                        reeval_floor=0, baseline_every=100)
    if resume:
        config = replace(config, resume_from_checkpoint=True)
    framework = Framework.from_profile(profile, fixture, domain, config, str(output / 'framework'))
    result = framework.evolve(TASK)
    def adapters(path, store):
        return FixtureProvider(), CirclePackingDomain(output / 'replay-domain', runner=SandboxRunner())
    replay = framework.replay(TASK, adapter_factory=adapters)['replay_certificate']
    calls = len(list(framework.store.read('composed_provider_started')))
    report = {'schema_version': 1, 'mode': 'fixture', 'performance_claim': False,
              'source': source, 'seed': seed, 'iterations': iterations,
              'provider_calls': calls, 'runtime': result['runtime'], 'replay_certificate': replay}
    if resume:
        original = terminal['report']
        stable = lambda certificate: {key: value for key, value in certificate.items()
                                      if key not in {'replay_workdir', 'replay_id'}}
        if any(original.get(key) != report[key] for key in report if key != 'replay_certificate') or \
                not original.get('replay_certificate', {}).get('passed') or not replay.get('passed') or \
                stable(original['replay_certificate']) != stable(replay):
            raise ValueError('fixture terminal differs from replayed original records')
    else:
        _atomic_json(output / 'terminal.json', {'manifest_sha256': manifest_ref,
            'report': report, 'report_sha256': payload_digest(report)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--iterations', type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.output), seed=args.seed, iterations=args.iterations), sort_keys=True))


if __name__ == '__main__':
    main()
