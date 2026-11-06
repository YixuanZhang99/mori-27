"""Full continuation Mori fixture: local HTTP, offline runtime, no paid work."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from core.composition.recovery import ContinuationStore
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_continuation_event import fixture_pair_ledger
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
from zoo.circle_packing.continuation_binding import bind_fixture_continuation
from zoo.circle_packing.mori_controller import build_controller
from zoo.mle_bench_lite.composed_domain import SandboxRunner

pytestmark = pytest.mark.linux


def test_continuation_mori_search_uses_bound_runtime_and_shared_ledger(tmp_path, local_endpoint, monkeypatch):
    cache = os.environ.get('MORI_TEST_OFFLINE_CACHE')
    if not cache:
        pytest.skip('requires an explicitly supplied offline uv cache')
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger, original_proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    inventory = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    draft = build_continuation_draft(inventory, experiment_id='circle-v2', source_commit=commit,
        dependency_lock_sha256=hashlib.sha256((checkout / 'm0/uv.lock').read_bytes()).hexdigest(),
        method_changes=['fixture loopback continuation'])
    source, runtime = tmp_path / 'source-bundle', tmp_path / 'runtime-bundle'
    prepared = prepare_continuation_runtime(ledger, draft, checkout=checkout, source_directory=source,
        directory=runtime, uv_cache=cache, base_python='/usr/bin/python3.12')
    bind_fixture_continuation(ledger, draft, checkout=checkout, source_directory=source,
                              runtime_directory=runtime, base_python='/usr/bin/python3.12')
    ref = 'sha256:' + draft['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--mori-0', plan_ref=ref, seconds=draft['limits']['wallclock_seconds'])
    ledger.claim_cell_worker('circle-v2--mori-0', clock._record['record_sha256'], 'a' * 64)
    runner = SandboxRunner.for_fixture_continuation(ledger, draft=draft, source_directory=source,
        runtime_directory=runtime, base_python='/usr/bin/python3.12')
    config = {'plan': draft, 'ref': ref, 'runtime_manifest': {}, 'source_manifest': {},
              'source': str(source / 'source/m0'), 'runtime': prepared['runtime'],
              'ledger': str(ledger.path), 'clock': str(tmp_path / 'clock.jsonl'),
              'output': str(tmp_path / 'controller'), 'base_url': local_endpoint.url,
              'campaign_id': draft['campaign_id'], 'seed': 0}
    content = '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # fixture\n>>>>>>> REPLACE\n'
    local_endpoint.responses.extend([reply(choices=[{'finish_reason': 'stop', 'message': {'content': content}}]) for _ in range(16)])
    framework, _provider, _profile, adapters = build_controller(config, ledger=ledger, clock=clock,
        runner=runner, api_key='fixture-only-secret')
    result = framework.evolve('Improve the arrangement of 26 circles in a square')
    snapshot = ledger.snapshot()
    assert result['runtime'] and framework.inspect()['governance']['completed'] == 1
    assert local_endpoint.requests and not snapshot['pending_calls'] and not snapshot['protected_micro_cny']
    assert snapshot['settled_upper_bound_micro_cny'] > before['settled_upper_bound_micro_cny']
    assert ledger.first_pair_audit() == original_proof
    assert len(local_endpoint.requests) == 6
    assert all(json.loads(request)['thinking'] == {'type': 'disabled'} for request in local_endpoint.requests)
    rows = [json.loads(line) for line in (tmp_path / 'controller/framework/x1.jsonl').read_text().splitlines()]
    assert [row['payload']['cycle'] for row in rows if row['kind'] == 'composed_cycle_started'] == list(range(7))
    assert len([row for row in rows if row['kind'] == 'composed_decision']) == 7
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    from zoo.circle_packing.domain import CirclePackingDomain
    def forbidden(*_args, **_kwargs):
        raise AssertionError('recorded replay attempted external work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    assert framework.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 6 and ledger.snapshot() == snapshot
