"""Readers and writers must not observe a cooperating writer's partial JSONL."""
import json
import multiprocessing
from pathlib import Path

import pytest

from core.x1.store import AppendOnlyStore


def _fragmented_writer(path, partial, finish, result):
    original_open = Path.open

    class PausedFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, text):
            split = len(text) // 2
            self.stream.write(text[:split])
            self.stream.flush()
            partial.set()
            if not finish.wait(10):
                raise TimeoutError('test writer was not released')
            self.stream.write(text[split:])
            return len(text)

    def opening(self, mode='r', *args, **kwargs):
        stream = original_open(self, mode, *args, **kwargs)
        return PausedFile(stream) if self == Path(path) and mode == 'a' else stream

    Path.open = opening
    try:
        AppendOnlyStore(path).append('large', {'text': 'x' * 12000})
        result.send(('ok', None))
    except Exception as error:
        result.send(('error', type(error).__name__))
    finally:
        Path.open = original_open


def _competing_operation(path, action, attempted, result):
    store = AppendOnlyStore(path)
    attempted.set()
    try:
        if action == 'read':
            rows = list(store.read())
        else:
            store.append('second', 2)
            rows = None
        result.send(('ok', rows))
    except Exception as error:
        result.send(('error', type(error).__name__))


@pytest.mark.parametrize('action', ['read', 'append'])
def test_separate_process_waits_for_complete_record_before_read_or_append(tmp_path, action):
    context = multiprocessing.get_context('spawn')
    partial, finish, attempted = context.Event(), context.Event(), context.Event()
    writer_result, writer_send = context.Pipe(duplex=False)
    other_result, other_send = context.Pipe(duplex=False)
    path = tmp_path / 'events.jsonl'
    writer = context.Process(target=_fragmented_writer, args=(path, partial, finish, writer_send))
    other = context.Process(target=_competing_operation, args=(path, action, attempted, other_send))
    writer.start()
    try:
        assert partial.wait(5), 'writer did not reach the partial record window'
        other.start()
        assert attempted.wait(5)
        assert not other_result.poll(0.3), 'another process observed/interleaved an incomplete record'
        finish.set()
        assert writer_result.poll(5) and writer_result.recv() == ('ok', None)
        assert other_result.poll(5)
        status, rows = other_result.recv()
        assert status == 'ok'
        expected = [{'kind': 'large', 'payload': {'text': 'x' * 12000}}]
        if action == 'read':
            assert rows == expected
        else:
            expected.append({'kind': 'second', 'payload': 2})
        assert list(AppendOnlyStore(path).read()) == expected
    finally:
        finish.set()
        for process in (writer, other):
            if process.pid is not None:
                process.join(5)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
        for connection in (writer_result, writer_send, other_result, other_send):
            connection.close()


def _append_during_iteration(path, result):
    store = AppendOnlyStore(path)
    store.append('first', 1)
    iterator = store.read()
    first = next(iterator)
    store.append('second', 2)
    result.send((first, list(iterator), list(store.read())))


def test_snapshot_iteration_does_not_hold_file_lock_across_caller_code(tmp_path):
    context = multiprocessing.get_context('spawn')
    result, sender = context.Pipe(duplex=False)
    child = context.Process(target=_append_during_iteration, args=(tmp_path / 'events.jsonl', sender))
    child.start()
    try:
        assert result.poll(5), 'append while consuming a reader deadlocked'
        first, remainder, current = result.recv()
        assert first == {'kind': 'first', 'payload': 1}
        assert remainder == []
        assert current == [first, {'kind': 'second', 'payload': 2}]
    finally:
        child.join(1)
        if child.is_alive():
            child.terminate()
            child.join(5)
        result.close()
        sender.close()


@pytest.mark.parametrize('tail', ['{"kind":', '{not-json}\n'])
def test_persistent_corruption_is_not_silently_skipped(tmp_path, tail):
    store = AppendOnlyStore(tmp_path / 'events.jsonl')
    store.append('valid', 1)
    with store.path.open('a') as stream:
        stream.write(tail)
    before = store.path.read_bytes()
    with pytest.raises(json.JSONDecodeError):
        list(store.read())
    assert store.path.read_bytes() == before
