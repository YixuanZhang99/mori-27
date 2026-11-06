"""Offline timed host controller reaches the existing physical/CNY broker."""
import asyncio
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_host_control import control_authority
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_source import freeze_source_plan, verify_frozen_source
from zoo.circle_packing.host_control import HostSeedControl
from zoo.circle_packing.host_dispatch import HostDispatchCoordinator, HostDispatchRouter
from zoo.circle_packing.host_physical import HostStageAdmission
from zoo.circle_packing.host_transport import HostBroker
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.composed_domain import SandboxRunner

pytestmark = pytest.mark.linux


def test_timed_isolated_host_routes_model_and_stages_through_authorities(control_authority, local_endpoint, tmp_path):
    ledger, budget, bridge, run, ready, domain = control_authority
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'clean-checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    # Include the candidate named entry even when testing before its commit.
    shutil.copyfile(repository / 'm0/zoo/circle_packing/reference_worker.py',
                    checkout / 'm0/zoo/circle_packing/reference_worker.py')
    subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/reference_worker.py'], check=True)
    subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '--allow-empty',
                    '-m', 'fixture worker entry'], check=True)
    commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    lock = hashlib.sha256((checkout / 'm0' / 'uv.lock').read_bytes()).hexdigest()
    plan = build_draft_plan(ledger.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)
    ref = 'sha256:' + plan['draft_sha256']
    campaign_id = ledger.manifest_binding()['campaign_id']
    exported = freeze_source_plan(ledger, plan, checkout=checkout, destination=tmp_path / 'exported-source',
                                  expected_plan_ref=ref, expected_campaign_id=campaign_id)
    assert exported['source_commit'] == commit
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    verify_frozen_source(ledger, plan, snapshot=tmp_path / 'exported-source', manifest=exported['manifest'],
                         expected_plan_ref=ref, expected_campaign_id=campaign_id)
    bridge.bind_cell_deadline(deadline, plan=plan, expected_plan_ref=ref, cell_id='vendor-0')
    assert asyncio.run(HostSeedControl(budget, bridge, run, ready, domain).execute('control-0000'))['status'] == 'evaluated'
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    workspace = tmp_path / 'worker-workspace'
    workspace.mkdir(mode=0o700)
    socket_path, token_path = workspace / 'broker.sock', workspace / 'token'
    token_path.write_text('a' * 64)
    token_path.chmod(0o600)
    source = tmp_path / 'exported-source' / 'm0'
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'stages', control_authority=provider)
    with HostBroker(socket_path, 'a' * 64, HostDispatchRouter(provider, stages)) as broker:
        from zoo.circle_packing.reference_worker import run_reference_fixture
        thread = threading.Thread(target=lambda: [broker.serve_one() for _ in range(5)], daemon=True)
        thread.start()
        result = run_reference_fixture(deadline, tmp_path / 'worker', workspace,
            snapshot=tmp_path / 'exported-source', source_manifest=exported['manifest'],
            frozen_plan=plan, expected_plan_ref=ref, expected_campaign_id=campaign_id,
            broker=broker, broker_token_file=token_path, iterations=1)
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert result['state'] == 'completed'
    verify_frozen_source(ledger, plan, snapshot=tmp_path / 'exported-source', manifest=exported['manifest'],
                         expected_plan_ref=ref, expected_campaign_id=campaign_id)
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    assert budget.audit_governance()['physical_totals']['token'] == 7
    assert provider.audit()['currency']['protection_valid']
    assert stages.audit()['stage_calls'] == 3
    # The fixture capability is available to the worker, but the normal path
    # must not copy it into execution transcripts or accounting evidence.
    for root in (tmp_path / 'worker', workspace / 'host-run', tmp_path / 'events.jsonl'):
        files = [root] if root.is_file() else (path for path in root.rglob('*') if path.is_file())
        for path in files:
            assert b'a' * 64 not in path.read_bytes(), path
