"""Named fixture entry keeps broker capability out of durable commands."""
import socket
import subprocess
import sys
import threading

import pytest

from test_openevolve_cell_worker import setup


@pytest.mark.linux
def test_reference_fixture_rejects_symlinked_capability_before_claim(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path = workspace / 'broker.sock'
    original = workspace / 'token-original'
    original.write_text('a' * 64)
    token = workspace / 'token'
    token.symlink_to(original)
    with HostBroker(socket_path, 'a' * 64, lambda *_: None) as broker:
        with pytest.raises(ValueError, match='broker'):
            run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=tmp_path / 'snapshot',
                source_manifest=[], frozen_plan={}, expected_plan_ref='sha256:' + 'a' * 64,
                expected_campaign_id='0' * 32, broker=broker, broker_token_file=token)
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None


def test_capability_reader_rejects_nonprivate_file(tmp_path):
    from zoo.circle_packing.reference_worker import _token
    path = tmp_path / 'token'
    path.write_text('a' * 64)
    path.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        _token(path)
    path.chmod(0o600)
    assert _token(path) == 'a' * 64


@pytest.mark.linux
def test_invalid_capability_is_rejected_before_worker_claim(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path, token = workspace / 'broker.sock', workspace / 'token'
    token.write_text('short-fixture')
    token.chmod(0o600)
    (tmp_path / 'snapshot' / 'm0').mkdir(parents=True)
    with HostBroker(socket_path, 'a' * 64, lambda *_: None) as broker:
        with pytest.raises(ValueError, match='capability'):
            run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=tmp_path / 'snapshot',
                source_manifest=[], frozen_plan={}, expected_plan_ref='sha256:' + 'a' * 64,
                expected_campaign_id='0' * 32, broker=broker, broker_token_file=token)
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None


@pytest.mark.linux
def test_missing_named_entry_is_rejected_before_worker_claim(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path, token = workspace / 'broker.sock', workspace / 'token'
    token.write_text('a' * 64)
    token.chmod(0o600)
    (tmp_path / 'snapshot' / 'm0').mkdir(parents=True)
    with HostBroker(socket_path, 'a' * 64, lambda *_: None) as broker:
        with pytest.raises(ValueError, match='entry'):
            run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=tmp_path / 'snapshot',
                source_manifest=[], frozen_plan={}, expected_plan_ref='sha256:' + 'a' * 64,
                expected_campaign_id='0' * 32, broker=broker, broker_token_file=token)
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None


@pytest.mark.linux
def test_nonempty_output_is_rejected_before_broker_probe(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path, token = workspace / 'broker.sock', workspace / 'token'
    token.write_text('a' * 64)
    token.chmod(0o600)
    entry = tmp_path / 'snapshot' / 'm0' / 'zoo' / 'circle_packing' / 'reference_worker.py'
    entry.parent.mkdir(parents=True)
    entry.write_text('# fixture only\n')
    output = workspace / 'host-run'
    output.mkdir()
    (output / 'keep').write_text('original')
    with HostBroker(socket_path, 'a' * 64, lambda *_: None) as broker:
        with pytest.raises(ValueError, match='output'):
            run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=tmp_path / 'snapshot',
                source_manifest=[], frozen_plan={}, expected_plan_ref='sha256:' + 'a' * 64,
                expected_campaign_id='0' * 32, broker=broker, broker_token_file=token)
    assert (output / 'keep').read_text() == 'original'
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None


@pytest.mark.linux
def test_broker_probe_checks_capability_without_dispatch(short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker, probe_broker
    path = short_socket_dir / 'broker.sock'
    calls = []
    with HostBroker(path, 'a' * 64, lambda *args: calls.append(args)) as broker:
        thread = threading.Thread(target=lambda: [broker.serve_one(), broker.serve_one()], daemon=True)
        thread.start()
        probe_broker(path, 'a' * 64)
        with pytest.raises(ValueError, match='broker'):
            probe_broker(path, 'b' * 64)
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert calls == []


@pytest.mark.linux
def test_probe_does_not_disclose_capability_to_another_process(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import probe_broker
    path, received = short_socket_dir / 'fake.sock', tmp_path / 'received'
    script = """import socket,sys
s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(1); print('ready',flush=True)
c,_=s.accept(); data=c.recv(4096); open(sys.argv[2],'wb').write(data)
try: c.sendall(b'{"state":"ready","result":null,"usage":null}\\n')
except OSError: pass
c.close(); s.close()
"""
    process = subprocess.Popen([sys.executable, '-c', script, str(path), str(received)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert process.stdout.readline().strip() == b'ready'
        with pytest.raises(ValueError, match='broker'):
            probe_broker(path, 'a' * 64)
        process.wait(timeout=5)
        assert received.read_bytes() == b''
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


@pytest.mark.linux
def test_wrong_broker_capability_does_not_consume_cell_claim(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path, token = workspace / 'broker.sock', workspace / 'token'
    token.write_text('b' * 64)
    token.chmod(0o600)
    entry = tmp_path / 'snapshot' / 'm0' / 'zoo' / 'circle_packing' / 'reference_worker.py'
    entry.parent.mkdir(parents=True)
    entry.write_text('# fixture only\n')
    calls = []
    with HostBroker(socket_path, 'a' * 64, lambda *args: calls.append(args)) as broker:
        with pytest.raises(ValueError, match='broker'):
            run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=tmp_path / 'snapshot',
                source_manifest=[], frozen_plan={}, expected_plan_ref='sha256:' + 'a' * 64,
                expected_campaign_id='0' * 32, broker=broker, broker_token_file=token)
    assert calls == [] and deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None


@pytest.mark.linux
def test_replaced_socket_is_rejected_before_capability_probe(tmp_path, short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    from zoo.circle_packing.reference_worker import run_reference_fixture
    deadline, _ = setup(tmp_path, 30)
    workspace = short_socket_dir
    workspace.chmod(0o700)
    socket_path, token = workspace / 'broker.sock', workspace / 'token'
    token.write_text('a' * 64)
    token.chmod(0o600)
    with HostBroker(socket_path, 'a' * 64, lambda *_: None) as broker:
        socket_path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
            replacement.bind(str(socket_path))
            replacement.listen(1)
            with pytest.raises(ValueError, match='broker'):
                run_reference_fixture(deadline, tmp_path / 'worker', workspace, snapshot=tmp_path / 'snapshot',
                    source_manifest=[], frozen_plan={}, expected_plan_ref='sha256:' + 'a' * 64,
                    expected_campaign_id='0' * 32, broker=broker, broker_token_file=token)
    assert deadline._lifecycle.ledger.cell_worker_claim('vendor-0') is None
