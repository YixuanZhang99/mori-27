"""Prepare a real-provider Mori controller without dispatching any work.

This uses a new temporary ledger and a fake credential. It does not enable a
live pilot or exercise the user's existing campaign.
"""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
from zoo.circle_packing.frozen_source import freeze_source_plan
from zoo.circle_packing.mori_controller import build_controller
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


@pytest.mark.linux
def test_real_provider_composition_requires_no_network_or_candidate_execution(tmp_path, monkeypatch):
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
