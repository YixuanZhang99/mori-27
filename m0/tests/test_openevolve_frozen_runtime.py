"""Disposable, locked runtime bound to the original campaign."""
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import pytest

from core.composition.recovery import ContinuationStore
from test_governed_cny_framework import campaign_fixture
from test_openevolve_source_preflight import draft
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.frozen_source import freeze_source_plan


pytestmark = pytest.mark.linux


def test_installer_inputs_reject_local_sources_and_artifacts(tmp_path):
    from zoo.circle_packing.frozen_runtime import _validate_install_inputs
    project = tmp_path / 'project'
    project.mkdir()
    config = project / 'pyproject.toml'
    lock = project / 'uv.lock'
    config.write_text('[project]\nname="fixture"\nversion="1"\ndependencies=[]\n')
    lock.write_text('[[package]]\nname="fixture"\nversion="1"\nsource={virtual="."}\n')
    _validate_install_inputs(project)
    lock.write_text('[[package]]\nname="fixture"\nversion="1"\nsource={path="../private"}\n')
    with pytest.raises(ValueError, match='source'):
        _validate_install_inputs(project)
    lock.write_text('[[package]]\nname="fixture"\nversion="1"\nsource={registry="https://pypi.org/simple"}\n'
                    'wheels=[{url="file:///private",hash="sha256:' + 'a' * 64 + '"}]\n')
    with pytest.raises(ValueError, match='artifact'):
        _validate_install_inputs(project)
    config.write_text('[project]\nname="fixture"\nversion="1"\ndependencies=["x @ file:///private"]\n')
    with pytest.raises(ValueError, match='direct'):
        _validate_install_inputs(project)
    config.write_text('[project]\nname="fixture"\nversion="1"\ndependencies=[]\n'
                      '[tool.uv]\noverride-dependencies=["x @ file:///private"]\n')
    with pytest.raises(ValueError, match='custom'):
        _validate_install_inputs(project)


def fixture(tmp_path, *, require_runtime=False):
    uv = shutil.which('uv')
    assert uv is not None
    root = tmp_path / 'checkout'
    project = root / 'm0'
    project.mkdir(parents=True)
    (project / 'pyproject.toml').write_text('[project]\nname="fixture-runtime"\nversion="1.0.0"\n'
                                             'requires-python=">=3.12"\ndependencies=[]\n')
    (project / 'source.py').write_text('value = 1\n')
    entry = project / 'zoo' / 'circle_packing' / 'reference_worker.py'
    entry.parent.mkdir(parents=True)
    entry.write_text('# fixture entry\n')
    cache = tmp_path / 'uv-cache'
    env = {'PATH': os.defpath, 'UV_CACHE_DIR': str(cache), 'UV_PYTHON': '/usr/bin/python3.12',
           'UV_OFFLINE': '1', 'UV_NO_CONFIG': '1'}
    subprocess.run([uv, 'lock', '--project', str(project), '--offline'], env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'fixture@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Fixture'], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'fixture'], check=True)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    ledger = campaign_fixture(tmp_path)
    plan, ref = draft(ledger, root, commit)
    campaign_id = ledger.manifest_binding()['campaign_id']
    snapshot = tmp_path / 'source'
    exported = freeze_source_plan(ledger, plan, checkout=root, destination=snapshot,
                                  expected_plan_ref=ref, expected_campaign_id=campaign_id,
                                  require_runtime=require_runtime)
    return ledger, plan, ref, campaign_id, snapshot, exported, cache


def test_locked_runtime_is_created_and_bound_before_any_cell(tmp_path):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime, verify_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path)
    runtime = tmp_path / 'runtime'
    result = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    assert ledger.circle_runtime_binding()['runtime_ref'] == result['runtime_ref']
    assert verify_frozen_runtime(ledger, runtime=runtime, manifest=result['manifest'],
                                 base_python='/usr/bin/python3.12')['runtime_ref'] == result['runtime_ref']
    output = subprocess.check_output([str(runtime / 'bin/python'), '-c', 'print(17)'], text=True)
    assert output.strip() == '17'
    (runtime / 'pyvenv.cfg').write_text('changed')
    with pytest.raises(ValueError):
        verify_frozen_runtime(ledger, runtime=runtime, manifest=result['manifest'],
                              base_python='/usr/bin/python3.12')


def test_stage_runner_executes_and_verifies_campaign_runtime(tmp_path):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path, require_runtime=True)
    runtime = tmp_path / 'runtime'
    frozen = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=frozen['manifest'],
                                                 base_python='/usr/bin/python3.12')
    independent = runner.independent_runner()
    assert independent is not runner and independent.manifest_binding == runner.manifest_binding
    assert runner.manifest_binding['runtime_ref'] == frozen['runtime_ref']
    with pytest.raises(ValueError, match='visible'):
        runner.validate_paths(runtime / 'protected')
    with pytest.raises(ValueError, match='visible'):
        runner.validate_paths(tmp_path)
    workspace = tmp_path / 'evaluation'
    workspace.mkdir()
    (workspace / 'data').mkdir()
    (workspace / 'program.py').write_text('import sys; print(sys.prefix)')
    outcome = runner.execute(workspace, timeout=15)
    assert outcome['returncode'] == 0
    assert (workspace / 'stdout.log').read_text().strip() == str(runtime)
    (runtime / 'pyvenv.cfg').write_text('tampered')
    with pytest.raises(ValueError, match='runtime'):
        independent.execute(workspace, timeout=15)


def test_runtime_creation_rejects_started_cell_and_existing_destination(tmp_path):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path)
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                  cell_id='vendor-0', plan_ref=ref, seconds=2700)
    with pytest.raises(ValueError, match='cell'):
        prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
            expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=tmp_path / 'runtime',
            base_python='/usr/bin/python3.12', uv_cache=cache)
    assert ledger.circle_runtime_binding() is None and deadline.remaining() > 0


def test_runtime_verification_rejects_escaping_symlink(tmp_path):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime, verify_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path)
    runtime = tmp_path / 'runtime'
    result = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    (runtime / 'unexpected').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='symlink'):
        verify_frozen_runtime(ledger, runtime=runtime, manifest=result['manifest'],
                              base_python='/usr/bin/python3.12')


def test_runtime_cannot_be_created_inside_frozen_source(tmp_path):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path)
    destination = snapshot / 'runtime'
    with pytest.raises(ValueError, match='separate'):
        prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
            expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=destination,
            base_python='/usr/bin/python3.12', uv_cache=cache)
    assert not destination.exists() and ledger.circle_runtime_binding() is None


def test_bound_runtime_is_required_and_verified_by_cell_worker(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path)
    runtime = tmp_path / 'runtime'
    prepared = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                  cell_id='vendor-0', plan_ref=ref, seconds=2700)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    common = {'readonly_source': snapshot / 'm0', 'readonly_runtime': runtime, 'frozen_plan': plan,
              'snapshot': snapshot, 'source_manifest': exported['manifest'],
              'expected_plan_ref': ref, 'expected_campaign_id': campaign_id}
    with pytest.raises(ValueError, match='runtime'):
        run_cell_worker(deadline, tmp_path / 'worker', workspace,
                        [str(runtime / 'bin/python'), '-c', 'print(17)'], **common)
    assert ledger.cell_worker_claim('vendor-0') is None
    result = run_cell_worker(deadline, tmp_path / 'worker', workspace,
        [str(runtime / 'bin/python'), '-c', 'print(17)'], runtime_manifest=prepared['manifest'],
        base_python='/usr/bin/python3.12', **common)
    assert result['state'] == 'completed'


def test_required_runtime_blocks_cell_until_environment_is_anchored(tmp_path):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path, require_runtime=True)
    with pytest.raises(ValueError, match='runtime'):
        CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                           cell_id='vendor-0', plan_ref=ref, seconds=2700)
    assert ledger.cell_deadline_claim('vendor-0') is None
    prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=tmp_path / 'runtime',
        base_python='/usr/bin/python3.12', uv_cache=cache)
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='vendor-0', plan_ref=ref, seconds=2700)
    assert clock.remaining() > 0


def test_named_reference_uses_the_bound_runtime_before_worker_start(tmp_path, monkeypatch):
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path)
    runtime = tmp_path / 'runtime'
    prepared = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                  cell_id='vendor-0', plan_ref=ref, seconds=2700)
    workspace = tmp_path / 'workspace'
    workspace.mkdir(mode=0o700)
    token = workspace / 'token'
    token.write_text('a' * 64)
    token.chmod(0o600)
    seen = []
    def capture(*args, **kwargs):
        seen.append((args, kwargs))
        return {'state': 'completed'}
    monkeypatch.setattr('zoo.circle_packing.reference_worker.run_cell_worker', capture)
    with HostBroker(workspace / 'broker.sock', 'a' * 64, lambda *_: None) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        result = run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=snapshot,
            source_manifest=exported['manifest'], frozen_plan=plan, expected_plan_ref=ref,
            expected_campaign_id=campaign_id, broker=broker, broker_token_file=token,
            runtime=runtime, runtime_manifest=prepared['manifest'], base_python='/usr/bin/python3.12')
        thread.join(timeout=5)
    assert result['state'] == 'completed' and not thread.is_alive()
    assert seen[0][0][3][2] == str(runtime / 'bin/python')
    assert seen[0][1]['runtime_manifest'] == prepared['manifest']


def test_worker_rejects_runtime_changed_during_execution(tmp_path):
    from zoo.circle_packing.cell_worker import run_cell_worker
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    ledger, plan, ref, campaign_id, snapshot, exported, cache = fixture(tmp_path, require_runtime=True)
    runtime = tmp_path / 'runtime'
    prepared = prepare_frozen_runtime(ledger, plan, snapshot=snapshot, source_manifest=exported['manifest'],
        expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
        base_python='/usr/bin/python3.12', uv_cache=cache)
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                                  cell_id='vendor-0', plan_ref=ref, seconds=2700)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    def mutate():
        until = time.monotonic() + 10
        while not (workspace / 'ready').exists() and time.monotonic() < until:
            time.sleep(.01)
        if (workspace / 'ready').exists():
            (runtime / 'pyvenv.cfg').write_text('changed')
    thread = threading.Thread(target=mutate)
    thread.start()
    try:
        with pytest.raises(ValueError, match='runtime'):
            run_cell_worker(deadline, tmp_path / 'worker', workspace,
                [str(runtime / 'bin/python'), '-c', "import time; open('ready','w').write('ready'); time.sleep(1)"],
                readonly_source=snapshot / 'm0', readonly_runtime=runtime, frozen_plan=plan, snapshot=snapshot,
                source_manifest=exported['manifest'], expected_plan_ref=ref, expected_campaign_id=campaign_id,
                runtime_manifest=prepared['manifest'], base_python='/usr/bin/python3.12')
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive() and ledger.cell_worker_claim('vendor-0') is not None
