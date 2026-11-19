"""Linux cgroup-v2 feasibility probe; not a live-supervision implementation.

Run inside a writable delegated user scope. A passing probe alone does not
prove the application uses this containment or handles supervisor crashes.
"""
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import pytest


@pytest.mark.linux
def test_delegated_cgroup_kills_detached_descendant_and_becomes_empty():
    membership = Path('/proc/self/cgroup').read_text().strip().splitlines()
    v2 = [row[3:] for row in membership if row.startswith('0::/')]
    if len(v2) != 1:
        pytest.skip('a unified cgroup-v2 hierarchy is required')
    parent = Path('/sys/fs/cgroup') / v2[0].lstrip('/')
    if not os.access(parent, os.W_OK) or not (parent / 'cgroup.kill').exists():
        pytest.skip('run inside a writable delegated cgroup-v2 scope')
    group = parent / f'mori-test-{os.getpid()}'
    group.mkdir()
    child = None
    try:
        script = ("import os,sys,time; sys.stdin.readline(); p=os.fork(); "
                  "(os.setsid(), print('ready',flush=True), time.sleep(60), os._exit(0)) "
                  "if p==0 else time.sleep(60)")
        child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={'PATH': '/usr/bin:/bin'})
        (group / 'cgroup.procs').write_text(str(child.pid))
        child.stdin.write('go\n')
        child.stdin.flush()
        assert select.select([child.stdout], [], [], 10)[0] and child.stdout.readline().strip() == 'ready'
        assert 'populated 1' in (group / 'cgroup.events').read_text()
        (group / 'cgroup.kill').write_text('1')
        child.wait(timeout=10)
        deadline = time.monotonic() + 10
        while 'populated 0' not in (group / 'cgroup.events').read_text() and time.monotonic() < deadline:
            time.sleep(.02)
        assert 'populated 0' in (group / 'cgroup.events').read_text()
    finally:
        if group.exists():
            (group / 'cgroup.kill').write_text('1')
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        if group.exists():
            deadline = time.monotonic() + 10
            while 'populated 0' not in (group / 'cgroup.events').read_text() and time.monotonic() < deadline:
                time.sleep(.02)
            group.rmdir()


@pytest.mark.linux
def test_cell_containment_stops_detached_child_after_controller_exits():
    from zoo.circle_packing.cell_containment import contained_command, delegated_cell_group
    membership = Path('/proc/self/cgroup').read_text().strip().splitlines()
    v2 = [row[3:] for row in membership if row.startswith('0::/')]
    if len(v2) != 1 or not os.access(Path('/sys/fs/cgroup') / v2[0].lstrip('/'), os.W_OK):
        pytest.skip('run inside a writable delegated cgroup-v2 scope')
    script = ("import os,time; p=os.fork(); "
              "(os.setsid(), print('ready',flush=True), time.sleep(60), os._exit(0)) "
              "if p==0 else time.sleep(.5)")
    with delegated_cell_group() as group:
        child = subprocess.Popen(contained_command(group, [sys.executable, '-c', script]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={'PATH': '/usr/bin:/bin'})
        try:
            assert select.select([child.stdout], [], [], 10)[0] and child.stdout.readline().strip() == 'ready'
            assert child.wait(timeout=10) == 0
            assert 'populated 1' in (group / 'cgroup.events').read_text().splitlines()
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()
            child.stderr.close()
    assert not group.exists()


@pytest.mark.linux
def test_containment_refuses_to_kill_a_group_with_the_wrong_identity():
    from zoo.circle_packing.cell_containment import delegated_cell_group, finish_cell_group
    membership = Path('/proc/self/cgroup').read_text().strip().splitlines()
    v2 = [row[3:] for row in membership if row.startswith('0::/')]
    if len(v2) != 1 or not os.access(Path('/sys/fs/cgroup') / v2[0].lstrip('/'), os.W_OK):
        pytest.skip('run inside a writable delegated cgroup-v2 scope')
    with delegated_cell_group() as group:
        info = group.stat()
        with pytest.raises(ValueError, match='identity'):
            finish_cell_group(group, expected_identity={'device': info.st_dev, 'inode': info.st_ino + 1})
        assert group.exists()


@pytest.mark.linux
@pytest.mark.parametrize('case', ['cleanup', 'supervisor_alive', 'wrapper_alive', 'wrong_config',
                                  'wrong_inode', 'wrong_claim'])
def test_interrupted_supervisor_reconciles_original_group_without_restarting(tmp_path, case):
    from core.composition.recovery import ContinuationStore
    from core.executor.process_identity import start_ticks
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.cell_containment import contained_command, delegated_cell_group
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.mori_supervisor import reconcile_live_containment
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    membership = Path('/proc/self/cgroup').read_text().strip().splitlines()
    v2 = [row[3:] for row in membership if row.startswith('0::/')]
    if len(v2) != 1 or not os.access(Path('/sys/fs/cgroup') / v2[0].lstrip('/'), os.W_OK):
        pytest.skip('run inside a writable delegated cgroup-v2 scope')
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    ref = 'sha256:' + 'a' * 64
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
                               cell_id='mori-0', plan_ref=ref, seconds=30)
    config = {'ledger': str(ledger.path), 'clock': str(clock._store.path), 'seed': 0, 'ref': ref}
    directory = tmp_path / 'controller'
    directory.mkdir(mode=0o700)
    old = subprocess.Popen(['/bin/sleep', '30'])
    old_ticks = start_ticks(old.pid)
    old.kill(); old.wait()
    with delegated_cell_group() as group:
        info = group.stat()
        binding = {'schema_version': 1, 'cell_id': 'mori-0', 'deadline_ref': clock._record['record_sha256'],
            'config_sha256': payload_digest(config), 'directory': str(directory),
            'entry': 'zoo.circle_packing.mori_live_worker', 'containment_group': str(group),
            'containment_identity': {'device': info.st_dev, 'inode': info.st_ino},
            'supervisor_pid': old.pid, 'supervisor_start_ticks': old_ticks, 'boot_id': clock._record['boot_id']}
        if case == 'supervisor_alive':
            binding['supervisor_pid'], binding['supervisor_start_ticks'] = os.getpid(), start_ticks(os.getpid())
        if case == 'wrong_inode':
            binding['containment_identity']['inode'] += 1
        worker_ref = payload_digest(binding)
        ledger.claim_cell_worker('mori-0', clock._record['record_sha256'], worker_ref)
        if case == 'wrong_claim':
            binding['containment_identity']['inode'] += 1
        journal = ContinuationStore(directory / 'controller.jsonl')
        wrapper_pid = os.getpid() if case == 'wrapper_alive' else old.pid
        wrapper_ticks = start_ticks(os.getpid()) if case == 'wrapper_alive' else old_ticks
        journal.append('executor_process_started', {'execution_id': 'a' * 32, 'candidate_id': 'fixture-coordinator',
            'attempt': 1, 'worker_ref': worker_ref, 'containment_required': True, 'containment_binding': binding,
            'wrapper_pid': wrapper_pid, 'wrapper_start_ticks': wrapper_ticks})
        child = subprocess.Popen(contained_command(group, [sys.executable, '-c',
            "import time; print('ready',flush=True); time.sleep(60)"]), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env={'PATH': '/usr/bin:/bin'})
        try:
            assert select.select([child.stdout], [], [], 10)[0] and child.stdout.readline().strip() == 'ready'
            if case != 'cleanup':
                test_config = {**config, 'altered': True} if case == 'wrong_config' else config
                with pytest.raises((ValueError, RuntimeError)):
                    reconcile_live_containment(test_config, deadline=clock, directory=directory)
                assert child.poll() is None and group.exists()
                assert [row['kind'] for row in ContinuationStore(directory / 'controller.jsonl').read()] == [
                    'executor_process_started']
                return
            result = reconcile_live_containment(config, deadline=clock, directory=directory)
            assert result == {'state': 'group_cleaned_cell_unresolved', 'execution_id': 'a' * 32}
            child.wait(timeout=10)
            rows = list(ContinuationStore(directory / 'controller.jsonl').read())
            assert [row['kind'] for row in rows] == ['executor_process_started', 'circle_containment_reconciled']
            assert ledger.cell_worker_claim('mori-0')['worker_ref'] == worker_ref
        finally:
            if child.poll() is None:
                child.kill(); child.wait()
            child.stdout.close(); child.stderr.close()
