"""Credential-free worker side of a future locally governed host transport.

This module only exchanges framed messages with a local broker. It does not
create a broker, grant budget, dispatch provider HTTP, or enable live runs.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import socket
import threading
import uuid

from core.llm import UsageError
from core.x1.checkpoint import payload_digest
from zoo.mle_bench_lite.cny_budget import validate_detailed_usage

_MAX_FRAME = 8 * 1024 * 1024


class HostBridgeClient:
    def __init__(self, model):
        self.model = model.name
        self.last_usage = None
        self._halted = False
        self._path = os.environ.get('MORI_CIRCLE_BROKER_SOCKET', '')
        self._token = os.environ.get('MORI_CIRCLE_BROKER_TOKEN', '')
        if not Path(self._path).is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', self._token):
            raise ValueError('host broker requires a local path and private session token')

    def _exchange(self, system, user):
        if self._halted:
            raise UsageError('host transport stopped after an unresolved operation')
        messages = {'system': system, 'user': user}
        request = {'schema_version': 1, 'request_id': uuid.uuid4().hex, 'token': self._token,
                   'argument': {'host_messages': messages,
                                'host_prompt_ref': 'sha256:' + payload_digest(messages)}}
        encoded = json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
        if len(encoded) > _MAX_FRAME:
            raise ValueError('host request exceeds local transport bound')
        self.last_usage = None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(120)
                connection.connect(self._path)
                connection.sendall(encoded)
                with connection.makefile('rb') as stream:
                    raw = stream.readline(_MAX_FRAME + 1)
            if not raw.endswith(b'\n') or len(raw) > _MAX_FRAME:
                raise ValueError('invalid broker frame')
            reply = json.loads(raw)
            if type(reply) is not dict or set(reply) != {'state', 'result', 'usage'}:
                raise ValueError('invalid broker response')
            if reply['usage'] is not None:
                self.last_usage = validate_detailed_usage(reply['usage'])
            if reply['state'] != 'ok' or self.last_usage is None or \
                    type(reply['result']) is not str or not reply['result'].strip():
                raise ValueError('broker did not return a successful measured response')
            return reply['result']
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._halted = True
            raise UsageError('host broker operation failed or is unresolved') from None

    async def generate_with_context(self, system_message, messages, **kwargs):
        if type(system_message) is not str or not system_message.strip() or type(messages) is not list or \
                len(messages) != 1 or type(messages[0]) is not dict or set(messages[0]) != {'role', 'content'} or \
                messages[0]['role'] != 'user' or type(messages[0]['content']) is not str or \
                not messages[0]['content'].strip() or kwargs:
            raise ValueError('host transport accepts only the pinned upstream message shape')
        return await asyncio.to_thread(self._exchange, system_message, messages[0]['content'])

    async def generate(self, prompt, **kwargs):
        raise ValueError('host transport requires explicit upstream system and user messages')


class HostBroker:
    """Authenticated local framing around an injected, trusted dispatcher.

    The caller must supply the existing durable budget/currency dispatcher;
    this class itself provides no admission authority.
    """
    def __init__(self, path, token, dispatch):
        import hmac
        import stat
        self._hmac = hmac
        self.path = Path(path)
        self._token = token
        self._dispatch = dispatch
        self._halted = False
        self._seen = set()
        self._serve_lock = threading.Lock()
        if not self.path.is_absolute() or type(token) is not str or not re.fullmatch(r'[0-9a-f]{64}', token) \
                or not callable(dispatch):
            raise ValueError('broker requires absolute socket path, session token and trusted dispatcher')
        parent = self.path.parent
        info = parent.stat()
        if parent.resolve() != parent or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() \
                or stat.S_IMODE(info.st_mode) & 0o077 or self.path.exists() or self.path.is_symlink():
            raise ValueError('broker requires a private directory and unused socket path')
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._socket.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self._identity = self.path.lstat().st_ino
            self._socket.listen(1)
        except BaseException:
            self._socket.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._socket.close()
        try:
            if self.path.lstat().st_ino == self._identity:
                self.path.unlink()
        except FileNotFoundError:
            pass

    def serve_one(self):
        with self._serve_lock:
            self._serve_one()

    def _serve_one(self):
        connection, _ = self._socket.accept()
        with connection:
            connection.settimeout(120)
            response = {'state': 'refused', 'result': None, 'usage': None}
            try:
                with connection.makefile('rb') as stream:
                    raw = stream.readline(_MAX_FRAME + 1)
                if not raw.endswith(b'\n') or len(raw) > _MAX_FRAME:
                    raise ValueError('invalid request frame')
                request = json.loads(raw)
                if type(request) is not dict or set(request) != {'schema_version', 'request_id', 'token', 'argument'} \
                        or type(request['schema_version']) is not int or request['schema_version'] != 1 \
                        or type(request['request_id']) is not str or not re.fullmatch(r'[0-9a-f]{32}', request['request_id']) \
                        or type(request['token']) is not str or not self._hmac.compare_digest(request['token'], self._token) \
                        or self._halted or request['request_id'] in self._seen:
                    raise ValueError('invalid or unauthorized broker request')
                argument = request['argument']
                if type(argument) is not dict or set(argument) != {'host_messages', 'host_prompt_ref'}:
                    raise ValueError('invalid host invocation')
                messages = argument['host_messages']
                if type(messages) is not dict or set(messages) != {'system', 'user'} or \
                        any(type(messages[k]) is not str or not messages[k].strip() for k in messages) or \
                        argument['host_prompt_ref'] != 'sha256:' + payload_digest(messages):
                    raise ValueError('host invocation binding differs')
                self._seen.add(request['request_id'])
                try:
                    response = self._dispatch(request['request_id'], argument)
                    if type(response) is not dict or set(response) != {'state', 'result', 'usage'} or \
                            response['state'] not in {'ok', 'known_failed', 'unknown'}:
                        raise ValueError('invalid dispatcher result')
                    if response['usage'] is not None:
                        validate_detailed_usage(response['usage'])
                    if response['state'] == 'ok' and (response['usage'] is None or
                            type(response['result']) is not str or not response['result'].strip()):
                        raise ValueError('successful dispatcher result requires usage and content')
                    if response['state'] == 'known_failed' and response['usage'] is None:
                        raise ValueError('known failure requires measured usage')
                    if response['state'] != 'ok' and response['result'] is not None:
                        raise ValueError('failed dispatcher cannot return a result')
                    if response['state'] != 'ok':
                        self._halted = True
                except Exception:
                    self._halted = True
                    response = {'state': 'unknown', 'result': None, 'usage': None}
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            try:
                encoded = json.dumps(response, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
                if len(encoded) > _MAX_FRAME:
                    raise ValueError('broker response exceeds bound')
                connection.sendall(encoded)
            except (OSError, ValueError, TypeError):
                self._halted = True
