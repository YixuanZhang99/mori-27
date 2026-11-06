"""Host worker transport never receives a provider credential."""
import asyncio
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from core.llm import UsageError


def serve_once(path, received, reply):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    def worker():
        conn, _ = listener.accept()
        with conn, conn.makefile('rb') as stream:
            received.append(json.loads(stream.readline()))
            if reply is not None:
                conn.sendall(json.dumps(reply).encode() + b'\n')
        listener.close()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def test_worker_sends_bound_host_messages_and_reports_usage(short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_transport import HostBridgeClient
    path = short_socket_dir / 'broker.sock'
    received = []
    thread = serve_once(path, received, {'state': 'ok', 'result': 'diff', 'usage': {
        'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}})
    monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
    monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
    client = HostBridgeClient(SimpleNamespace(name='fixture'))
    result = asyncio.run(client.generate_with_context('host system', [{'role': 'user', 'content': 'host user'}]))
    thread.join(timeout=5)
    assert result == 'diff' and client.last_usage['total_tokens'] == 7
    assert received[0]['argument']['host_messages'] == {'system': 'host system', 'user': 'host user'}
    assert received[0]['token'] == 'a' * 64
    assert 'api_key' not in json.dumps(received)


def test_lost_broker_reply_is_unknown_and_not_retried(short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_transport import HostBridgeClient
    path = short_socket_dir / 'broker.sock'
    received = []
    thread = serve_once(path, received, None)
    monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
    monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
    client = HostBridgeClient(SimpleNamespace(name='fixture'))
    with pytest.raises(UsageError):
        asyncio.run(client.generate_with_context('system', [{'role': 'user', 'content': 'user'}]))
    thread.join(timeout=5)
    assert client.last_usage is None and len(received) == 1
    with pytest.raises(UsageError):
        asyncio.run(client.generate_with_context('system', [{'role': 'user', 'content': 'user'}]))
    assert len(received) == 1


def test_broker_authenticates_and_invokes_only_bound_message(short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_transport import HostBridgeClient, HostBroker
    calls = []
    def dispatch(request_id, argument):
        calls.append((request_id, argument))
        return {'state': 'ok', 'result': 'diff', 'usage': {
            'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}}
    path = short_socket_dir / 'protected.sock'
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostBridgeClient(SimpleNamespace(name='fixture'))
        assert asyncio.run(client.generate_with_context('system', [{'role': 'user', 'content': 'user'}])) == 'diff'
        thread.join(timeout=5)
    assert len(calls) == 1 and calls[0][1]['host_messages'] == {'system': 'system', 'user': 'user'}
    assert not path.exists()


def test_broker_rejects_bad_token_before_dispatch(short_socket_dir):
    from zoo.circle_packing.host_transport import HostBroker
    calls = []
    path = short_socket_dir / 'protected.sock'
    with HostBroker(path, 'a' * 64, lambda *args: calls.append(args)) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(path))
            client.sendall(json.dumps({'schema_version': 1, 'request_id': 'b' * 32,
                                       'token': 'c' * 64, 'argument': {}}).encode() + b'\n')
            reply = json.loads(client.makefile('rb').readline())
        thread.join(timeout=5)
    assert reply['state'] != 'ok' and calls == []


def test_broker_serializes_multiple_worker_requests(short_socket_dir, monkeypatch):
    import time
    from zoo.circle_packing.host_transport import HostBridgeClient, HostBroker
    active, maximum = 0, 0
    def dispatch(request_id, argument):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        time.sleep(.05)
        active -= 1
        return {'state': 'ok', 'result': 'diff', 'usage': {
            'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}}
    path = short_socket_dir / 'serial.sock'
    with HostBroker(path, 'a' * 64, dispatch) as broker:
        workers = [threading.Thread(target=broker.serve_one, daemon=True) for _ in range(2)]
        for worker in workers:
            worker.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        async def calls():
            clients = [HostBridgeClient(SimpleNamespace(name='fixture')) for _ in range(2)]
            return await asyncio.gather(*(client.generate_with_context('system',
                [{'role': 'user', 'content': 'user'}]) for client in clients))
        assert asyncio.run(calls()) == ['diff', 'diff']
        for worker in workers:
            worker.join(timeout=5)
    assert maximum == 1


def test_known_billed_failure_retains_usage_and_stops_client(short_socket_dir, monkeypatch):
    from zoo.circle_packing.host_transport import HostBridgeClient, HostBroker
    path = short_socket_dir / 'failed.sock'
    usage = {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}
    with HostBroker(path, 'a' * 64, lambda *_: {'state': 'known_failed', 'result': None, 'usage': usage}) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostBridgeClient(SimpleNamespace(name='fixture'))
        with pytest.raises(UsageError):
            asyncio.run(client.generate_with_context('system', [{'role': 'user', 'content': 'user'}]))
        thread.join(timeout=5)
    assert client.last_usage == usage
