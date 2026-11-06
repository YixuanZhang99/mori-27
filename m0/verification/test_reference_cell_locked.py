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
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
from zoo.circle_packing.frozen_source import freeze_source_plan
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
    # Mori uses the same campaign, plan, sandbox runtime, seed and nominal
    # resource ceilings. Its controller runs in this pytest process, not from
    # the frozen source/runtime. Vendor runs one iteration while Mori is
    # configured for six: this is not a fair performance comparison.
    from core.loop import Framework, LoopConfig
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.runner import TASK
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    mori_clock = CellDeadline.start(ContinuationStore(tmp_path / 'mori-clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                    cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    mori_output = tmp_path / 'mori'
    options = dict(ledger=ledger, api_key='fixture-only-secret', seed=0, iterations=plan['iterations'],
                   base_url=local_endpoint.url, max_completion_tokens=plan['max_completion_tokens'],
                   total_token_ceiling=plan['limits']['token'], cell_deadline=mori_clock,
                   draft_plan=plan, expected_plan_ref=ref, runner=runner)
    profile, registry, provider = governed_setup(mori_output, **options)
    assert profile['budget']['options']['limits']['global'] == reference_limits
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    cfg = LoopConfig(max_generations=plan['iterations'], total_budget=plan['limits']['token'],
                     reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(mori_output / 'domain', runner=runner.independent_runner())
    fw = Framework.from_profile(profile, provider, domain, cfg, str(mori_output / 'framework'),
                                component_registry=registry)
    outcome = fw.evolve(TASK)
    assert outcome['best_candidate_id'] is not None
    assert outcome['reporting']['final_audit']['state'] == 'completed'
    assert len(local_endpoint.requests) == 2 and not ledger.snapshot()['pending_calls']

    def adapters(path, store):
        _, _, replay_provider = governed_setup(mori_output, **options)
        return replay_provider, CirclePackingDomain(tmp_path / 'mori-replay', runner=runner.independent_runner())
    def forbidden(*args, **kwargs):
        raise AssertionError('paired recorded replay performed live work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 2
