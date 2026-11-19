"""A temporary historical audit prefix is never a new execution campaign."""
import sqlite3
from pathlib import Path

import pytest

from test_openevolve_continuation_event import fixture_pair_ledger
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def appended_fixture(tmp_path):
    ledger, proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    inv = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    draft = build_continuation_draft(inv, experiment_id='circle-v2', source_commit='6' * 40,
        dependency_lock_sha256='7' * 64, method_changes=['fixture continuation'])
    event = {'kind': 'bind_circle_continuation', 'schema_version': 2,
             'previous_head': before['journal_head'], 'draft': draft,
             'tree_ref': 'sha256:' + '8' * 64, 'runtime_ref': 'sha256:' + '9' * 64,
             'python_sha256': 'a' * 64, 'runtime_manifest_sha256': 'b' * 64}
    with ledger._transaction() as (db, _policy, state):
        ledger._append(db, state, event)
    return ledger, before, proof


def test_prefix_replays_original_identity_before_later_event(tmp_path):
    from zoo.circle_packing.historical_prefix import _temporary_verified_prefix
    ledger, before, proof = appended_fixture(tmp_path)
    latest = ledger.snapshot()
    with _temporary_verified_prefix(ledger, expected_head=before['journal_head']) as path:
        snapshot = CampaignBudget(path)
        assert snapshot.snapshot() == before and snapshot.first_pair_audit() == proof
        with snapshot._transaction() as (_db, _policy, state):
            assert state['governance']['circle_continuations'] == {}
        assert Path(path).stat().st_mode & 0o777 == 0o600
        assert ledger.snapshot() == latest
    assert not Path(path).exists() and ledger.snapshot() == latest


def test_prefix_cleanup_on_exception(tmp_path):
    from zoo.circle_packing.historical_prefix import _temporary_verified_prefix
    ledger, before, _proof = appended_fixture(tmp_path)
    path = None
    with pytest.raises(RuntimeError):
        with _temporary_verified_prefix(ledger, expected_head=before['journal_head']) as path:
            raise RuntimeError('fixture')
    assert path is not None and not Path(path).exists()


@pytest.mark.parametrize('damage', ['wrong_hash', 'future', 'corrupt'])
def test_prefix_rejects_invalid_head_or_damaged_current_journal(tmp_path, damage):
    from zoo.circle_packing.historical_prefix import _temporary_verified_prefix
    ledger, before, _proof = appended_fixture(tmp_path)
    head = dict(before['journal_head'])
    if damage == 'wrong_hash': head['sha256'] = '0' * 64
    elif damage == 'future': head['seq'] += 100
    else:
        with sqlite3.connect(ledger.path) as db:
            db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    with pytest.raises(ValueError):
        with _temporary_verified_prefix(ledger, expected_head=head):
            pytest.fail('invalid campaign yielded a prefix')


@pytest.mark.linux
def test_isolated_probe_uses_historical_prefix_and_no_credentials(tmp_path, monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace
    from zoo.circle_packing.historical_prefix import replay_historical_pair
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    ledger, before, _proof = appended_fixture(private)
    latest = ledger.snapshot()
    source = tmp_path / 'snapshot/m0'
    source.mkdir(parents=True)
    runtime = tmp_path / 'runtime'
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'bin/python').write_text('fixture')
    mori, vendor = tmp_path / 'mori', tmp_path / 'vendor'
    mori.mkdir(); vendor.mkdir()
    mori_output, vendor_output = tmp_path / 'mori-output', tmp_path / 'vendor-output'
    workspace, worker = tmp_path / 'workspace', tmp_path / 'worker'
    for item in (mori_output, vendor_output, workspace, worker): item.mkdir()
    mori_clock, vendor_clock = tmp_path / 'mori-clock', tmp_path / 'vendor-clock'
    mori_clock.write_text('fixture'); vendor_clock.write_text('fixture')
    replay_parent = tmp_path / 'replay-work'
    replay_parent.mkdir(mode=0o700)
    ref = 'sha256:' + 'a' * 64
    config = {'seed': 0, 'ledger': str(ledger.path), 'ref': ref, 'plan': {'fixture': True},
              'source': str(source), 'runtime': str(runtime), 'source_manifest': [], 'runtime_manifest': {}}
    (mori / 'config.json').write_text(json.dumps({**config, 'clock': str(mori_clock), 'output': str(mori_output)}))
    (vendor / 'config.json').write_text(json.dumps({**config, 'clock': str(vendor_clock), 'output': str(vendor_output),
                                                    'workspace': str(workspace), 'worker_directory': str(worker)}))
    monkeypatch.setattr('zoo.circle_packing.frozen_source.verify_frozen_source', lambda *_args, **_kwargs: None)
    monkeypatch.setattr('zoo.circle_packing.frozen_runtime.verify_frozen_runtime', lambda *_args, **_kwargs: None)
    monkeypatch.setattr('zoo.circle_packing.pilot_matrix._validate_replay_output', lambda path, **_kwargs: Path(path))
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-never-forwarded')
    mounted = []
    def fake_run(command, *, env, **kwargs):
        assert '--unshare-net' in command and '--unshare-pid' in command and '--seccomp' in command
        assert any(command[i:i+2] == ['--tmpfs', '/'] for i in range(len(command)-1))
        assert not any(command[i:i+3] == ['--ro-bind', '/', '/'] for i in range(len(command)-2))
        assert len(kwargs['pass_fds']) == 1
        output_mounts = [command[i+1] for i in range(len(command)-2) if command[i] == '--bind' and command[i+2] == str(replay_parent)]
        assert len(output_mounts) == 1 and Path(output_mounts[0]) != replay_parent
        (Path(output_mounts[0]) / 'replay').mkdir()
        assert 'DEEPSEEK_API_KEY' not in env and 'fixture-never-forwarded' not in str(command)
        index = command.index(str(ledger.path))
        prefix = Path(command[index - 1])
        assert prefix != ledger.path and CampaignBudget(prefix).snapshot() == before
        mounted.append(prefix)
        result = {'scope': 'paired_supervised_snapshots_with_independent_replay', 'seed': 0,
                  'plan_ref': ref, 'journal_head': before['journal_head'], 'performance_claim': False,
                  'mori': {'candidate': 'fixture', 'sum_radii': 1.0, 'validity': 1.0, 'settled_upper_bound_micro_cny': 1},
                  'reference': {'selected_program': {'code': 'PRIVATE-CANDIDATE'}, 'sum_radii': 2.0, 'validity': 1.0,
                                'settled_upper_bound_micro_cny': 2},
                  'sum_radii_difference': -1.0, 'replay': {'passed': True, 'external_calls': 0, 'candidate': 'fixture'}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr='')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    result = replay_historical_pair(ledger, expected_head=before['journal_head'], expected_plan_ref=ref,
        seed=0, mori_directory=mori, vendor_directory=vendor, replay_output=replay_parent / 'replay')
    assert result['replay']['passed'] and ledger.snapshot() == latest
    assert 'PRIVATE-CANDIDATE' not in str(result) and 'selected_program' not in result['reference']
    assert len(mounted) == 1 and not mounted[0].exists()


@pytest.mark.linux
def test_real_replay_sandbox_hides_host_files_and_blocks_socket_syscalls(tmp_path):
    import errno
    import os
    import socket
    import subprocess
    from zoo.circle_packing.historical_prefix import _historical_network_filter
    secret = tmp_path / 'fixture-key'
    secret.write_text('fixture-secret')
    listener_path = tmp_path / 'proxy.sock'
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(listener_path))
    listener.listen(1)
    host = subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(60)'],
                            env={'MORI_TEST_SECRET': 'fixture-process-secret'})
    script = '''import errno,os,socket,subprocess,sys
assert not os.path.exists(sys.argv[1])
assert not os.path.exists('/proc/'+sys.argv[2]+'/environ')
pair=socket.socketpair(); pair[0].send(b'x'); assert pair[1].recv(1)==b'x'
try: pair[0].sendmsg([b'x'])
except OSError as e: assert e.errno==errno.EPERM
else: raise AssertionError('sendmsg allowed')
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
assert s.connect_ex('/tmp/proxy.sock')==errno.EPERM
udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try: udp.sendto(b'x',('127.0.0.1',9999))
except OSError as e: assert e.errno==errno.EPERM
else: raise AssertionError('sendto allowed')
child=subprocess.run([sys.executable,'-c',"import errno,socket; s=socket.socket(socket.AF_UNIX); assert s.connect_ex('/tmp/proxy.sock')==errno.EPERM"])
assert child.returncode==0
'''
    try:
        with _historical_network_filter() as fd:
            result = subprocess.run(['bwrap', '--die-with-parent', '--unshare-net', '--unshare-pid', '--tmpfs', '/',
                '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
                '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--ro-bind', str(listener_path),
                '/tmp/proxy.sock', '--seccomp', str(fd), '--', '/usr/bin/python3', '-c', script, str(secret), str(host.pid)],
                pass_fds=(fd,), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    finally:
        host.terminate()
        host.wait(timeout=10)
        listener.close()


@pytest.mark.linux
def test_output_mount_hides_and_preserves_existing_parent_files(tmp_path):
    import os
    import subprocess
    from zoo.circle_packing.historical_prefix import _historical_network_filter
    parent = tmp_path / 'output-parent'
    parent.mkdir(mode=0o700)
    secret = parent / 'fixture-key'
    secret.write_text('fixture-secret')
    staging = parent / '.staging'
    staging.mkdir(mode=0o700)
    script = "import os,sys; assert not os.path.exists(sys.argv[1]); open(sys.argv[2], 'w').write('replayed')"
    with _historical_network_filter() as fd:
        result = subprocess.run(['bwrap', '--die-with-parent', '--unshare-net', '--unshare-pid', '--tmpfs', '/',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--proc', '/proc', '--dev', '/dev', '--bind', str(staging), str(parent), '--seccomp', str(fd),
            '--', '/usr/bin/python3', '-c', script, str(secret), str(parent / 'replay')],
            pass_fds=(fd,), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert secret.read_text() == 'fixture-secret' and (staging / 'replay').read_text() == 'replayed'
