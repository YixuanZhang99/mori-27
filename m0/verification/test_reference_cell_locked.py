"""Explicit locked-environment reference-cell integration; loopback HTTP only.

Run with MORI_TEST_OFFLINE_CACHE pointing to a populated uv cache and
PYTHONPATH=.:tests. This check is not collected by the default pytest suite.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint, reply
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime, verify_frozen_runtime
from zoo.circle_packing.frozen_source import freeze_source_plan, verify_frozen_source
from zoo.circle_packing.host_runtime import build_reference_authorities
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.composed_domain import SandboxRunner


@pytest.fixture
def short_workspace():
    with tempfile.TemporaryDirectory(prefix='mori-worker-', dir='/tmp') as directory:
        yield Path(directory).resolve()


@pytest.mark.parametrize('tamper_selection', [False, True])
def test_reference_cell_uses_production_authorities_with_shared_frozen_runtime(tmp_path, local_endpoint,
                                                                                monkeypatch, tamper_selection,
                                                                                short_workspace):
    cache = os.environ['MORI_TEST_OFFLINE_CACHE']
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger = campaign_fixture(tmp_path)
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
                               cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                base_python='/usr/bin/python3.12')
    authority = build_reference_authorities(tmp_path / 'reference', ledger=ledger, plan=plan,
        expected_plan_ref=ref, expected_campaign_id=campaign_id, deadline=clock,
        snapshot=source, source_manifest=exported['manifest'], runner=runner,
        api_key='fixture-only-secret', base_url=local_endpoint.url)
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    workspace = short_workspace
    from zoo.circle_packing.host_runtime import run_reference_cell_fixture
    if tamper_selection:
        from core.executor.process import ProcessJournal
        original = ProcessJournal.completed_result
        def changed_report(self, record):
            result = original(self, record)
            report = json.loads(result['stdout'])
            report['selected_program']['program_ref'] = 'sha256:' + 'f' * 64
            return {**result, 'stdout': json.dumps(report)}
        monkeypatch.setattr(ProcessJournal, 'completed_result', changed_report)
        with pytest.raises(ValueError, match='unique eligible stage'):
            run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
                source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
                expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
                base_python='/usr/bin/python3.12', iterations=1)
        assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
        authority.close()
        return
    result = run_reference_cell_fixture(authority, clock, tmp_path / 'worker', workspace, snapshot=source,
        source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
        expected_campaign_id=campaign_id, runtime=runtime, runtime_manifest=frozen['manifest'],
        base_python='/usr/bin/python3.12', iterations=1)
    assert result['state'] == 'completed'
    assert result['mode'] == 'fixture' and result['performance_claim'] is False
    assert result['selected_program']['metrics']['validity'] == 1.0
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    assert authority.dispatch.audit()['currency']['protection_valid']
    assert authority.stages.audit()['stage_calls'] == 3
    assert authority.budget.audit_governance()['physical_totals']['token'] == 7
    reference_limits = authority.budget.options['limits']['global']
    authority.close()
    # Mori starts in the same frozen source and Python runtime as the vendor
    # worker. Vendor runs one iteration while Mori is configured for six;
    # this checks integration, not a fair performance comparison.
    mori_clock = CellDeadline.start(ContinuationStore(tmp_path / 'mori-clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                    cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    mori_output = tmp_path / 'mori'
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    setup_path = tmp_path / 'mori-fixture.json'
    setup_path.write_text(json.dumps({'plan': plan, 'ref': ref, 'runtime_manifest': frozen['manifest'],
        'source': str(source / 'm0'), 'runtime': str(runtime), 'ledger': str(ledger.path),
        'clock': str(mori_clock._store.path), 'output': str(mori_output), 'base_url': local_endpoint.url}))
    script = r'''
import json, sys
from pathlib import Path
config = json.loads(Path(sys.argv[1]).read_text())
sys.path.insert(0, config['source'])
import core.loop
from core.loop import Framework, LoopConfig
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.governed import governed_setup
from zoo.circle_packing import governed
from zoo.circle_packing.runner import TASK
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
ledger = CampaignBudget(config['ledger'])
plan = config['plan']
clock = CellDeadline.restore(ContinuationStore(config['clock']), lifecycle=CellLifecycle(ledger),
    cell_id='mori-0', plan_ref=config['ref'], seconds=plan['limits']['wallclock_seconds'])
runner = SandboxRunner.for_campaign_runtime(ledger, runtime=config['runtime'],
    manifest=config['runtime_manifest'], base_python='/usr/bin/python3.12')
root = Path(config['output'])
options = dict(ledger=ledger, api_key='fixture-only-secret', seed=0, iterations=plan['iterations'],
    base_url=config['base_url'], max_completion_tokens=plan['max_completion_tokens'],
    total_token_ceiling=plan['limits']['token'], cell_deadline=clock,
    draft_plan=plan, expected_plan_ref=config['ref'], runner=runner)
profile, registry, provider = governed_setup(root, **options)
cfg = LoopConfig(max_generations=plan['iterations'], total_budget=plan['limits']['token'],
                 reeval_floor=0, baseline_every=100)
domain = CirclePackingDomain(root / 'domain', runner=runner.independent_runner())
fw = Framework.from_profile(profile, provider, domain, cfg, str(root / 'framework'), component_registry=registry)
outcome = fw.evolve(TASK)
def adapters(path, store):
    _, _, replay_provider = governed_setup(root, **options)
    return replay_provider, CirclePackingDomain(root / 'replay-domain', runner=runner.independent_runner())
def forbidden(*args, **kwargs):
    raise AssertionError('paired recorded replay performed live work')
GovernedCNYProvider.perform_request = forbidden
CirclePackingDomain.evaluate = forbidden
certificate = fw.replay(adapter_factory=adapters)['replay_certificate']
import openevolve
print(json.dumps({'limits': profile['budget']['options']['limits']['global'],
    'candidate': outcome['best_candidate_id'], 'final_state': outcome['reporting']['final_audit']['state'],
    'replay_passed': certificate['passed'], 'source': core.loop.__file__,
    'governed_source': governed.__file__, 'vendor_source': openevolve.__file__, 'executable': sys.executable}))
'''
    process = subprocess.run([str(runtime / 'bin' / 'python'), '-c', script, str(setup_path)],
        env={'PATH': os.defpath, 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'},
        text=True, capture_output=True, timeout=240)
    assert process.returncode == 0, process.stderr
    mori = json.loads(process.stdout)
    assert mori['limits'] == reference_limits
    assert mori['candidate'] is not None and mori['final_state'] == 'completed' and mori['replay_passed']
    assert Path(mori['source']).resolve() == (source / 'm0' / 'core' / 'loop.py').resolve()
    assert Path(mori['governed_source']).resolve() == (source / 'm0' / 'zoo' / 'circle_packing' / 'governed.py').resolve()
    assert (source / 'm0' / 'vendor' / 'openevolve').resolve() in Path(mori['vendor_source']).resolve().parents
    assert mori['executable'] == str(runtime / 'bin' / 'python')
    verify_frozen_source(ledger, plan, snapshot=source, manifest=exported['manifest'],
                         expected_plan_ref=ref, expected_campaign_id=campaign_id)
    verify_frozen_runtime(ledger, runtime=runtime, manifest=frozen['manifest'], base_python='/usr/bin/python3.12')
    assert len(local_endpoint.requests) == 2
    assert not ledger.snapshot()['pending_calls']
