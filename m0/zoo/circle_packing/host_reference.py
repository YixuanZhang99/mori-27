"""Offline fixture for the actual pinned OpenEvolve controller and worker.

This entry point refuses live use and does not implement the paid comparison.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

# Installs the pinned vendored OpenEvolve package path.
from core.openevolve_interop import ProgramDatabase as _ProgramDatabase  # noqa: F401
from core.composition.openevolve_registration import (
    _SEED, _SEED_SHA, _frozen_source, host_database_options, policy_options,
)
from core.composition.openevolve_prompt import _CONFIG, _verify_sources
from core.x1.store import AppendOnlyStore
from zoo.circle_packing.reproducibility import require_hash_seed_zero

_ALLOWED_ENV = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'PYTHONPATH',
                'PYTHONHASHSEED', 'LD_LIBRARY_PATH')
_BROKER_ENV = ('MORI_CIRCLE_BROKER_SOCKET', 'MORI_CIRCLE_BROKER_TOKEN')
_FIXTURE_LOCK = threading.RLock()


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


def reference_model(name, max_completion_tokens, *, fixture_broker):
    """Build the upstream model configuration without giving it a credential."""
    from openevolve.config import LLMModelConfig
    if type(name) is not str or not name.strip() or type(max_completion_tokens) is not int or \
            not 1 <= max_completion_tokens <= 16384 or type(fixture_broker) is not bool:
        raise ValueError('invalid reference model configuration')
    return LLMModelConfig(name=name, api_key=None,
        init_client=fixture_broker_client if fixture_broker else fixture_client,
        max_tokens=max_completion_tokens, timeout=120, retries=0)


@contextlib.contextmanager
def _hide_stage_receipts_from_prompts():
    """Keep the internal receipt in the database, outside upstream prompts."""
    with _FIXTURE_LOCK:
        original = _ProgramDatabase.get_artifacts
        def public_artifacts(database, program_id):
            return {key: value for key, value in original(database, program_id).items()
                    if key != 'mori_stage_request_id'}
        _ProgramDatabase.get_artifacts = public_artifacts
        try:
            yield
        finally:
            _ProgramDatabase.get_artifacts = original


def run_fixture(output, *, seed=0, iterations=1, fixture_broker=False, fixture_stage_broker=False,
                model_name='circle-fixture', max_completion_tokens=128):
    # The pinned controller and its environment use process-global state.
    with _FIXTURE_LOCK:
        previous_root = os.environ.get('MORI_CIRCLE_REFERENCE_ROOT')
        try:
            return _run_fixture(output, seed=seed, iterations=iterations, fixture_broker=fixture_broker,
                                fixture_stage_broker=fixture_stage_broker, model_name=model_name,
                                max_completion_tokens=max_completion_tokens)
        finally:
            if previous_root is None:
                os.environ.pop('MORI_CIRCLE_REFERENCE_ROOT', None)
            else:
                os.environ['MORI_CIRCLE_REFERENCE_ROOT'] = previous_root


def _run_fixture(output, *, seed, iterations, fixture_broker, fixture_stage_broker,
                 model_name, max_completion_tokens):
    if type(seed) is not int or seed < 0 or type(iterations) is not int or not 1 <= iterations <= 6:
        raise ValueError('fixture requires nonnegative seed and one to six iterations')
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('fixture requires PYTHONHASHSEED=0 at process start')
    if fixture_stage_broker and not fixture_broker:
        raise ValueError('fixture stage broker requires the fixture transport')
    if fixture_stage_broker and os.environ.get('MORI_CIRCLE_STAGE_BROKER') != '1':
        raise ValueError('fixture stage broker must be explicitly enabled')
    allowed = set(_ALLOWED_ENV) | (set(_BROKER_ENV) if fixture_broker else set()) | \
              ({'MORI_CIRCLE_STAGE_BROKER'} if fixture_stage_broker else set())
    if set(os.environ) - allowed:
        raise ValueError('host fixture worker requires a sanitized environment')
    require_hash_seed_zero()
    _verify_sources()
    policy_options({'seed': seed, 'migration_interval': 2})
    seed_code = _frozen_source(_SEED, _SEED_SHA).decode('utf-8')
    root = Path(output).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('host fixture output is nonempty')
    root.mkdir(parents=True, exist_ok=True)
    os.environ['MORI_CIRCLE_REFERENCE_ROOT'] = str(root)
    from openevolve.api import run_evolution
    from openevolve.config import Config, PromptConfig
    import yaml
    config = Config()
    model = reference_model(model_name, max_completion_tokens, fixture_broker=fixture_broker)
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
    # Broker requests time out at 120 seconds; leave headroom for their
    # fail-closed response before the upstream outer timeout can fire.
    config.evaluator.timeout = 180
    config.evaluator.cascade_evaluation = True
    config.evaluator.cascade_thresholds = [.5, .75]
    for name, value in host_database_options(2).items():
        setattr(config.database, name, value)
    evaluator = Path(__file__).with_name('reference_evaluator.py')
    from openevolve import process_parallel
    from zoo.circle_packing.reference_iteration_trace import capture_reference_iterations
    with contextlib.redirect_stdout(sys.stderr), _hide_stage_receipts_from_prompts(), \
            capture_reference_iterations(process_parallel.ProcessParallelController, parallel_module=process_parallel) as capture:
        result = run_evolution(seed_code, evaluator, config=config, iterations=iterations,
                               output_dir=str(root / 'host'), cleanup=False)
        iteration_trace = capture.snapshot()
        iteration_trace['prompt_bindings'] = [row['payload'] for row in
            AppendOnlyStore(root / 'iteration-prompts.jsonl').read('reference_iteration_prompt')]
        iteration_trace['request_bindings'] = [row['payload'] for row in
            AppendOnlyStore(root / 'iteration-requests.jsonl').read('reference_iteration_request')]
    calls = None if fixture_broker else len(list(AppendOnlyStore(root / 'fixture-provider.jsonl').read('provider')))
    stages = len(list(AppendOnlyStore(root / 'fixture-stages.jsonl').read('stage')))
    if list(AppendOnlyStore(root / 'fixture-unresolved.jsonl').read('unresolved')):
        raise RuntimeError('host fixture has unresolved stage execution')
    if type(result.best_code) is not str or not result.best_code or result.best_program is None or \
            type(result.best_program.id) is not str or not result.best_program.id or \
            result.best_program.code != result.best_code or type(result.metrics) is not dict or \
            result.best_program.metrics != result.metrics:
        raise RuntimeError('pinned host returned no evaluated program')
    selected = {'id': result.best_program.id,
                'program_ref': 'sha256:' + hashlib.sha256(result.best_code.encode('utf-8')).hexdigest(),
                'metrics': result.metrics}
    report = {'schema_version': 1, 'mode': 'fixture', 'performance_claim': False,
              'controller': 'pinned_openevolve', 'provider_calls': calls, 'stage_calls': stages,
              'fixture_broker': fixture_broker, 'fixture_stage_broker': fixture_stage_broker,
              'iteration_trace': iteration_trace,
              'model_config': {'model': model.name, 'max_completion_tokens': model.max_tokens},
              'selected_program': selected}
    if fixture_stage_broker:
        import re
        try:
            artifacts = json.loads(result.best_program.artifacts_json)
            receipt = artifacts['mori_stage_request_id']
        except (TypeError, ValueError, KeyError) as error:
            raise RuntimeError('selected host program lacks its evaluation receipt') from error
        if type(receipt) is not str or not re.fullmatch(r'[0-9a-f]{32}', receipt):
            raise RuntimeError('selected host program has an invalid evaluation receipt')
        report['selection_stage_request_id'] = receipt
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--iterations', type=int, default=1)
    parser.add_argument('--fixture-broker', action='store_true')
    parser.add_argument('--fixture-stage-broker', action='store_true')
    args = parser.parse_args()
    # The vendored worker serializes its environment: start with a small
    # allowlist so no model credentials are copied to that worker.
    allowed = _ALLOWED_ENV + (_BROKER_ENV if args.fixture_broker else ())
    clean = {key: os.environ[key] for key in allowed if key in os.environ}
    if args.fixture_stage_broker:
        clean['MORI_CIRCLE_STAGE_BROKER'] = '1'
    os.environ.clear()
    os.environ.update(clean)
    print(json.dumps(run_fixture(args.output, seed=args.seed, iterations=args.iterations,
                                 fixture_broker=args.fixture_broker,
                                 fixture_stage_broker=args.fixture_stage_broker), sort_keys=True))


if __name__ == '__main__':
    main()
