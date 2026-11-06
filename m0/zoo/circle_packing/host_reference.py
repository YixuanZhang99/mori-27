"""Offline fixture for the actual pinned OpenEvolve controller and worker.

This entry point refuses live use and does not implement the paid comparison.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import sys

# Installs the pinned vendored OpenEvolve package path.
from core.openevolve_interop import ProgramDatabase as _ProgramDatabase  # noqa: F401
from core.composition.openevolve_registration import _SEED, _SEED_SHA, _frozen_source, policy_options
from core.composition.openevolve_prompt import _CONFIG, _verify_sources
from core.x1.store import AppendOnlyStore

_ALLOWED_ENV = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'PYTHONPATH',
                'PYTHONHASHSEED', 'LD_LIBRARY_PATH')
_BROKER_ENV = ('MORI_CIRCLE_BROKER_SOCKET', 'MORI_CIRCLE_BROKER_TOKEN')


class FixtureHostClient:
    def __init__(self, model):
        self.model = model.name
        self.last_usage = None

    async def generate_with_context(self, system_message, messages, **kwargs):
        root = Path(os.environ['MORI_CIRCLE_REFERENCE_ROOT'])
        AppendOnlyStore(root / 'fixture-provider.jsonl').append('provider',
            {'system': system_message, 'messages': messages})
        self.last_usage = {'total_tokens': 7}
        return ('<<<<<<< SEARCH\n    n = 26\n=======\n'
                '    n = 26\n    # host fixture mutation\n>>>>>>> REPLACE\n')

    async def generate(self, prompt, **kwargs):
        return await self.generate_with_context('', [{'role': 'user', 'content': prompt}], **kwargs)


def fixture_client(model):
    return FixtureHostClient(model)


def fixture_broker_client(model):
    from zoo.circle_packing.host_transport import HostBridgeClient
    return HostBridgeClient(model)


def run_fixture(output, *, seed=0, iterations=1, fixture_broker=False):
    if type(seed) is not int or seed < 0 or type(iterations) is not int or not 1 <= iterations <= 6:
        raise ValueError('fixture requires nonnegative seed and one to six iterations')
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('fixture requires PYTHONHASHSEED=0 at process start')
    allowed = set(_ALLOWED_ENV) | (set(_BROKER_ENV) if fixture_broker else set())
    if set(os.environ) - allowed:
        raise ValueError('host fixture worker requires a sanitized environment')
    _verify_sources()
    policy_options({'seed': seed, 'migration_interval': 2})
    seed_code = _frozen_source(_SEED, _SEED_SHA).decode('utf-8')
    root = Path(output).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('host fixture output is nonempty')
    root.mkdir(parents=True, exist_ok=True)
    os.environ['MORI_CIRCLE_REFERENCE_ROOT'] = str(root)
    from openevolve.api import run_evolution
    from openevolve.config import Config, LLMModelConfig, PromptConfig
    import yaml
    config = Config()
    model = LLMModelConfig(name='circle-fixture', api_key=None,
                           init_client=fixture_broker_client if fixture_broker else fixture_client,
                           max_tokens=128, timeout=120, retries=0)
    config.llm.api_key = None
    config.llm.models = [model]
    config.llm.evaluator_models = [model]
    config.prompt = PromptConfig(**yaml.safe_load(_CONFIG.read_text())['prompt'])
    config.random_seed = seed
    config.diff_based_evolution = True
    config.enforce_evolve_blocks = True
    config.max_iterations = iterations
    config.log_level = 'WARNING'
    config.evaluator.parallel_evaluations = 1
    config.evaluator.max_retries = 0
    config.evaluator.timeout = 120
    config.evaluator.cascade_evaluation = True
    config.evaluator.cascade_thresholds = [.5, .75]
    for name, value in {'num_islands': 4, 'population_size': 60, 'archive_size': 25,
            'feature_dimensions': ['complexity', 'diversity'], 'feature_bins': 10,
            'elite_selection_ratio': .3, 'exploration_ratio': .2, 'exploitation_ratio': .7,
            'migration_interval': 2, 'migration_rate': .1}.items():
        setattr(config.database, name, value)
    evaluator = Path(__file__).with_name('reference_evaluator.py')
    with contextlib.redirect_stdout(sys.stderr):
        result = run_evolution(seed_code, evaluator, config=config, iterations=iterations,
                               output_dir=str(root / 'host'), cleanup=False)
    calls = len(list(AppendOnlyStore(root / 'fixture-provider.jsonl').read('provider')))
    stages = len(list(AppendOnlyStore(root / 'fixture-stages.jsonl').read('stage')))
    if result.best_code is None:
        raise RuntimeError('pinned host returned no evaluated program')
    return {'schema_version': 1, 'mode': 'fixture', 'performance_claim': False,
            'controller': 'pinned_openevolve', 'provider_calls': calls, 'stage_calls': stages,
            'fixture_broker': fixture_broker}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--iterations', type=int, default=1)
    parser.add_argument('--fixture-broker', action='store_true')
    args = parser.parse_args()
    # The vendored worker serializes its environment: start with a small
    # allowlist so no model credentials are copied to that worker.
    allowed = _ALLOWED_ENV + (_BROKER_ENV if args.fixture_broker else ())
    clean = {key: os.environ[key] for key in allowed if key in os.environ}
    os.environ.clear()
    os.environ.update(clean)
    print(json.dumps(run_fixture(args.output, seed=args.seed, iterations=args.iterations,
                                 fixture_broker=args.fixture_broker), sort_keys=True))


if __name__ == '__main__':
    main()
