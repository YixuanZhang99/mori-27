"""Prepare a real-provider Mori controller without dispatching any work.

This uses a new temporary ledger and a fake credential. It does not enable a
live pilot or exercise the user's existing campaign.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from core.composition.recovery import ContinuationStore
from core.executor.sandbox import sandbox_child_path
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
from zoo.circle_packing.frozen_source import freeze_source_plan
from zoo.circle_packing.mori_controller import build_controller
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


@pytest.fixture
def prepared_cell(tmp_path):
    cache = os.environ['MORI_TEST_OFFLINE_CACHE']
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    lock = hashlib.sha256((checkout / 'm0' / 'uv.lock').read_bytes()).hexdigest()
    plan = build_draft_plan(ledger.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)
    ref, campaign_id = 'sha256:' + plan['draft_sha256'], ledger.manifest_binding()['campaign_id']
    source, runtime = tmp_path / 'source', tmp_path / 'runtime'
    exported = freeze_source_plan(ledger, plan, checkout=checkout, destination=source,
        expected_plan_ref=ref, expected_campaign_id=campaign_id, require_runtime=True)
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=source, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    output = tmp_path / 'mori'
    config = {'plan': plan, 'ref': ref, 'runtime_manifest': frozen['manifest'],
        'source_manifest': exported['manifest'], 'campaign_id': campaign_id, 'seed': 0,
        'source': str(source / 'm0'), 'runtime': str(runtime), 'ledger': str(ledger.path),
        'clock': str(clock._store.path), 'output': str(output),
        'base_url': ledger.manifest_binding()['provider_base_url']}
    return config, ledger, clock, runner


@pytest.mark.linux
def test_real_provider_composition_requires_no_network_or_candidate_execution(prepared_cell, monkeypatch):
    config, ledger, clock, runner = prepared_cell
    plan, output = config['plan'], Path(config['output'])
    def forbidden(*args, **kwargs):
        raise AssertionError('preparation attempted external or candidate work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(SandboxRunner, 'execute', forbidden)
    framework, provider, profile, adapters = build_controller(
        config, ledger=ledger, clock=clock, runner=runner, api_key='fixture-only-secret')
    assert framework is not None and callable(adapters)
    assert provider.manifest_binding()['base_url'] == ledger.manifest_binding()['provider_base_url']
    assert provider.manifest_binding()['requested_model'] == plan['model']
    assert profile['budget']['options']['limits']['global']['token'] == plan['limits']['token']
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 0
    assert not ledger.snapshot()['pending_calls']
    if output.exists():
        for path in output.rglob('*'):
            if path.is_file() and not path.is_symlink():
                assert b'fixture-only-secret' not in path.read_bytes(), f'fixture credential persisted in {path}'


@pytest.mark.linux
def test_real_provider_mode_runs_six_rounds_with_network_blocked(prepared_cell, tmp_path):
    config, ledger, _clock, _runner = prepared_cell
    setup = tmp_path / 'setup.json'
    setup.write_text(json.dumps(config))
    script = r'''
import json, pathlib, socket, sys, urllib.request
import core.loop
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.frozen_source import verify_frozen_source
from zoo.circle_packing.mori_controller import build_controller
from zoo.circle_packing.runner import TASK
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider

config = json.loads(pathlib.Path(sys.argv[1]).read_text())
ledger = CampaignBudget(config['ledger'])
plan = config['plan']
verify_frozen_source(ledger, plan, snapshot=pathlib.Path(config['source']).parent,
    manifest=config['source_manifest'], expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'])
assert sys.executable == str(pathlib.Path(config['runtime']) / 'bin' / 'python')
assert pathlib.Path(core.loop.__file__).resolve() == pathlib.Path(config['source']) / 'core' / 'loop.py'
clock = CellDeadline.restore(ContinuationStore(config['clock']), lifecycle=CellLifecycle(ledger),
    cell_id='mori-0', plan_ref=config['ref'], seconds=plan['limits']['wallclock_seconds'])
runner = SandboxRunner.for_campaign_runtime(ledger, runtime=config['runtime'],
    manifest=config['runtime_manifest'], base_python='/usr/bin/python3.12')
calls = []
def forbidden(*args, **kwargs):
    raise AssertionError('unexpected external work')
socket.socket.connect = forbidden
diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
        '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
        '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
class Response:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self):
        return json.dumps({'model': plan['model'],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
            'choices': [{'finish_reason': 'stop', 'message': {'content': diff}}]}).encode()
class Opener:
    def open(self, request, timeout):
        assert request.full_url == config['base_url'] + '/chat/completions'
        assert request.get_header('Authorization') == 'Bearer fixture-only-secret'
        calls.append(1)
        return Response()
urllib.request.build_opener = lambda *args: Opener()
framework, provider, profile, adapters = build_controller(
    config, ledger=ledger, clock=clock, runner=runner, api_key='fixture-only-secret')
outcome = framework.evolve(TASK)
GovernedCNYProvider.perform_request = forbidden
CirclePackingDomain.evaluate = forbidden
certificate = framework.replay(adapter_factory=adapters)['replay_certificate']
final = outcome['reporting']['final_audit']
metrics = final['evidence']['evidence']['eval_result']['metrics']
print(json.dumps({'candidate': outcome['best_candidate_id'], 'state': final['state'],
    'metrics': metrics, 'calls': len(calls), 'replay': certificate['passed']}))
'''
    code = tmp_path / 'blocked_transport.py'
    code.write_text(script)
    env = {'PATH': sandbox_child_path(), 'PYTHONPATH': config['source'],
           'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    process = subprocess.run([str(Path(config['runtime']) / 'bin' / 'python'), '-B', str(code), str(setup)],
                             cwd=tmp_path, env=env, capture_output=True, text=True, timeout=240)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['candidate'] and result['state'] == 'completed' and result['replay']
    assert result['metrics']['test/validity'] == 1.0
    assert result['metrics']['test/sum_radii'] > 0
    assert 1 <= result['calls'] <= 2 * config['plan']['iterations'] + 2
    snapshot = ledger.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == result['calls'] * 38
    assert not snapshot['pending_calls']
    for path in Path(config['output']).rglob('*'):
        if path.is_file() and not path.is_symlink():
            assert b'fixture-only-secret' not in path.read_bytes(), f'fixture credential persisted in {path}'
