"""Offline timed host controller reaches the existing physical/CNY broker."""
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
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

pytestmark = pytest.mark.linux


@pytest.mark.parametrize('control_authority', ['locked'], indirect=True)
def test_timed_isolated_host_routes_model_and_stages_through_authorities(control_authority, local_endpoint, tmp_path):
    ledger, budget, bridge, run, ready, domain = control_authority
    frozen = domain._fixture_frozen
    if frozen:
        plan, ref, campaign_id = frozen['plan'], frozen['ref'], frozen['campaign_id']
        snapshot, manifest = frozen['source'], frozen['source_manifest']
        runtime_args = {'runtime': frozen['runtime'], 'runtime_manifest': frozen['runtime_manifest'],
                        'base_python': '/usr/bin/python3.12'}
    else:
        repository = Path(__file__).resolve().parents[2]
        commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
        checkout = tmp_path / 'clean-checkout'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
        # Export the candidate reference entry before its commit when testing a worktree.
        shutil.copyfile(repository / 'm0/zoo/circle_packing/host_reference.py',
                        checkout / 'm0/zoo/circle_packing/host_reference.py')
        subprocess.run(['git', '-C', str(checkout), 'add', 'm0/zoo/circle_packing/host_reference.py'], check=True)
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '--allow-empty',
                        '-m', 'fixture reference selection'], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        lock = hashlib.sha256((checkout / 'm0' / 'uv.lock').read_bytes()).hexdigest()
        plan = build_draft_plan(ledger.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)
        ref = 'sha256:' + plan['draft_sha256']
        campaign_id = ledger.manifest_binding()['campaign_id']
        snapshot = tmp_path / 'exported-source'
        exported = freeze_source_plan(ledger, plan, checkout=checkout, destination=snapshot,
                                      expected_plan_ref=ref, expected_campaign_id=campaign_id)
        manifest, runtime_args = exported['manifest'], {}
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='vendor-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    verify_frozen_source(ledger, plan, snapshot=snapshot, manifest=manifest,
                         expected_plan_ref=ref, expected_campaign_id=campaign_id)
    bridge.bind_cell_deadline(deadline, plan=plan, expected_plan_ref=ref, cell_id='vendor-0')
    control = HostSeedControl(budget, bridge, run, ready, domain)
    assert asyncio.run(control.execute('control-0000'))['status'] == 'evaluated'
    diff = ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
            '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
            '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content': diff}}]))
    workspace = tmp_path / 'worker-workspace'
    workspace.mkdir(mode=0o700)
    socket_path, token_path = workspace / 'broker.sock', workspace / 'token'
    token_path.write_text('a' * 64)
    token_path.chmod(0o600)
    provider = HostDispatchCoordinator(budget, bridge, run, ready, runner=domain.runner)
    stages = HostStageAdmission(budget, runner=domain.runner.independent_runner(),
                                workspace=tmp_path / 'stages', control_authority=provider)
    if frozen:
        runtime_ref = ledger.circle_runtime_binding()['runtime_ref']
        assert control.domain.runner.manifest_binding['runtime_ref'] == runtime_ref
        assert provider.control_domain.runner.manifest_binding['runtime_ref'] == runtime_ref
        assert stages.runner.manifest_binding['runtime_ref'] == runtime_ref
    with HostBroker(socket_path, 'a' * 64, HostDispatchRouter(provider, stages)) as broker:
        from zoo.circle_packing.reference_worker import run_reference_fixture
        thread = threading.Thread(target=lambda: [broker.serve_one() for _ in range(5)], daemon=True)
        thread.start()
        result = run_reference_fixture(deadline, tmp_path / 'worker', workspace,
            snapshot=snapshot, source_manifest=manifest,
            frozen_plan=plan, expected_plan_ref=ref, expected_campaign_id=campaign_id,
            broker=broker, broker_token_file=token_path, iterations=1, **runtime_args)
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert result['state'] == 'completed'
    verify_frozen_source(ledger, plan, snapshot=snapshot, manifest=manifest,
                         expected_plan_ref=ref, expected_campaign_id=campaign_id)
    assert len(local_endpoint.requests) == 1 and not ledger.snapshot()['pending_calls']
    assert budget.audit_governance()['physical_totals']['token'] == 7
    assert provider.audit()['currency']['protection_valid']
    assert stages.audit()['stage_calls'] == 3
    from core.executor.process import ProcessJournal
    worker_store = ContinuationStore(tmp_path / 'worker' / 'worker.jsonl')
    started = list(worker_store.read('executor_process_started'))
    assert len(started) == 1
    report = json.loads(ProcessJournal(worker_store).completed_result(started[0]['payload'])['stdout'])
    best = workspace / 'host-run' / 'host' / 'best' / 'best_program.py'
    info = json.loads((best.parent / 'best_program_info.json').read_text())
    selected = report['selected_program']
    assert selected == {'id': info['id'], 'metrics': info['metrics'],
                        'program_ref': 'sha256:' + hashlib.sha256(best.read_bytes()).hexdigest()}
    measured = [row['payload']['result'] for row in budget.store.read('host_stage_completed')]
    assert any(row['program_ref'] == selected['program_ref'] and row['metrics'] == selected['metrics']
               for row in measured if row['status'] == 'ok')
    # The fixture capability is available to the worker, but the normal path
    # must not copy it into execution transcripts or accounting evidence.
    for root in (tmp_path / 'worker', workspace / 'host-run', tmp_path / 'events.jsonl'):
        files = [root] if root.is_file() else (path for path in root.rglob('*') if path.is_file())
        for path in files:
            assert b'a' * 64 not in path.read_bytes(), path
