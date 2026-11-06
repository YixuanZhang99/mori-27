"""Credential-free worker side of a future locally governed host transport.

This module only exchanges framed messages with a local broker. It does not
create a broker, grant budget, dispatch provider HTTP, or enable live runs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import threading
import uuid

from core.llm import ProviderBudgetExhausted, UsageError
from core.x1.checkpoint import payload_digest
from zoo.mle_bench_lite.cny_budget import validate_detailed_usage

_MAX_FRAME = 8 * 1024 * 1024


def probe_broker(path, token):
    """Verify a local capability without dispatching a provider or stage call."""
    if not Path(path).is_absolute() or type(token) is not str or not re.fullmatch(r'[0-9a-f]{64}', token):
        raise ValueError('invalid local broker capability')
    request = {'schema_version': 1, 'request_id': uuid.uuid4().hex, 'token': token,
               'argument': {'probe': True}}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(path))
            if not hasattr(socket, 'SO_PEERCRED'):
                raise ValueError('local broker peer identity is unavailable')
            peer = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
            pid, uid, _gid = struct.unpack('3i', peer)
            if pid != os.getpid() or uid != os.getuid():
                raise ValueError('local broker peer identity differs from the trusted caller')
            connection.sendall(json.dumps(request, separators=(',', ':')).encode() + b'\n')
            with connection.makefile('rb') as stream:
                raw = stream.readline(_MAX_FRAME + 1)
        if not raw.endswith(b'\n') or len(raw) > _MAX_FRAME or \
                json.loads(raw) != {'state': 'ready', 'result': None, 'usage': None}:
            raise ValueError('broker rejected capability probe')
    except (OSError, TypeError, UnicodeError, struct.error, json.JSONDecodeError) as error:
        raise ValueError('local broker capability probe failed') from error


class StageEvidenceFailure(BaseException):
    """Abort the upstream worker if an unresolved stage cannot be recorded."""


class SettledProviderFailure(UsageError):
    """A provider attempt failed after its usage was durably accounted for."""


class HostBridgeClient:
    def __init__(self, model, *, continue_settled_failures=False):
        if type(continue_settled_failures) is not bool:
            raise ValueError('settled failure continuation must be boolean')
        self.model = model.name
        self._continue_settled_failures = continue_settled_failures
        self.last_usage = None
        self._halted = False
        self._path = os.environ.get('MORI_CIRCLE_BROKER_SOCKET', '')
        self._token = os.environ.get('MORI_CIRCLE_BROKER_TOKEN', '')
        if not Path(self._path).is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', self._token):
            raise ValueError('host broker requires a local path and private session token')

    def _exchange(self, system, user):
        messages = {'system': system, 'user': user}
        request_id = uuid.uuid4().hex
        from zoo.circle_packing.reference_iteration_trace import record_iteration_request
        record_iteration_request(messages, request_id)
        return self._exchange_argument({'host_messages': messages,
                                        'host_prompt_ref': 'sha256:' + payload_digest(messages)}, request_id=request_id)

    def _exchange_argument(self, argument, *, request_id=None):
        if self._halted:
            raise UsageError('host transport stopped after an unresolved operation')
        request = {'schema_version': 1, 'request_id': request_id or uuid.uuid4().hex,
                   'token': self._token, 'argument': argument}
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
            if reply['state'] == 'known_refused' and reply['result'] is None and reply['usage'] == {'total_tokens': 0}:
                self.last_usage = {'total_tokens': 0}
                self._halted = True
                raise ProviderBudgetExhausted('host provider request was refused before dispatch')
            if reply['usage'] is not None:
                self.last_usage = validate_detailed_usage(reply['usage'])
            if self._continue_settled_failures and 'host_messages' in argument and \
                    reply['state'] == 'known_failed' and reply['result'] is None and self.last_usage is not None:
                raise SettledProviderFailure('host provider attempt failed with settled usage')
            if reply['state'] != 'ok' or self.last_usage is None or \
                    type(reply['result']) is not str or not reply['result'].strip():
                raise ValueError('broker did not return a successful measured response')
            return reply['result']
        except ProviderBudgetExhausted:
            raise
        except SettledProviderFailure:
            raise
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


class HostEvaluationClient(HostBridgeClient):
    def evaluate(self, program, *, stage, prior_id=None):
        from zoo.circle_packing.host_physical import _validate_stage_result
        request_id = uuid.uuid4().hex
        if type(program) is not str:
            raise ValueError('stage program must be text')
        program_ref = 'sha256:' + hashlib.sha256(program.encode()).hexdigest()
        from zoo.circle_packing.reference_iteration_trace import record_iteration_stage
        record_iteration_stage(request_id, program_ref, stage=stage, prior_id=prior_id)
        argument = {'stage': stage, 'program': program, 'program_ref': program_ref, 'prior_id': prior_id}
        try:
            result = json.loads(self._exchange_argument(argument, request_id=request_id))
            _validate_stage_result(result, stage=stage, program_ref=program_ref)
        except (ValueError, TypeError, json.JSONDecodeError):
            self._halted = True
            raise UsageError('stage broker response is invalid') from None
        return request_id, result


def _validate_argument(argument):
    if type(argument) is not dict:
        raise ValueError('invalid host invocation')
    if set(argument) == {'probe'} and type(argument['probe']) is bool and argument['probe'] is True:
        return
    if set(argument) == {'host_messages', 'host_prompt_ref'}:
        messages = argument['host_messages']
        if type(messages) is not dict or set(messages) != {'system', 'user'} or \
                any(type(messages[k]) is not str or not messages[k].strip() for k in messages) or \
                argument['host_prompt_ref'] != 'sha256:' + payload_digest(messages):
            raise ValueError('host invocation binding differs')
    elif set(argument) == {'stage', 'program', 'program_ref', 'prior_id'}:
        stage, program, prior = argument['stage'], argument['program'], argument['prior_id']
        if type(stage) is not int or stage not in (1, 2) or type(program) is not str or not program.strip() or \
                len(program.encode()) > 1024 * 1024 or \
                argument['program_ref'] != 'sha256:' + hashlib.sha256(program.encode()).hexdigest() or \
                stage == 1 and prior is not None or stage == 2 and (
                    type(prior) is not str or not re.fullmatch(r'[0-9a-f]{32}', prior)):
            raise ValueError('stage invocation binding differs')
    else:
        raise ValueError('unsupported host invocation')


class HostBroker:
    """Authenticated local framing around an injected, trusted dispatcher.

    The caller must supply the existing durable budget/currency dispatcher;
    this class itself provides no admission authority.
    """
    def __init__(self, path, token, dispatch, *, continue_settled_failures=False):
        import hmac
        import stat
        self._hmac = hmac
        self.path = Path(path)
        self._token = token
        self._dispatch = dispatch
        if type(continue_settled_failures) is not bool:
            raise ValueError('settled failure continuation must be boolean')
        self._continue_settled_failures = continue_settled_failures
        self._halted = False
        self._seen = set()
        self._serve_lock = threading.Lock()
        self._connection_lock = threading.Lock()
        self._active_connection = None
        self._closing = False
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
        self.cancel_active()
        self._socket.close()
        try:
            if self.path.lstat().st_ino == self._identity:
                self.path.unlink()
        except FileNotFoundError:
            pass

    def serve_one(self):
        with self._serve_lock:
            self._serve_one()

    def cancel_active(self):
        """Stop accepting frames and interrupt an active connection's reads."""
        with self._connection_lock:
            self._closing = True
            if self._active_connection is not None:
                try:
                    self._active_connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _serve_one(self):
        connection, _ = self._socket.accept()
        with self._connection_lock:
            if self._closing:
                connection.close()
                return
            self._active_connection = connection
        try:
            self._handle_connection(connection)
        finally:
            with self._connection_lock:
                if self._active_connection is connection:
                    self._active_connection = None

    def _handle_connection(self, connection):
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
                _validate_argument(argument)
                self._seen.add(request['request_id'])
                try:
                    if argument == {'probe': True}:
                        response = {'state': 'ready', 'result': None, 'usage': None}
                    else:
                        response = self._dispatch(request['request_id'], argument)
                    if type(response) is not dict or set(response) != {'state', 'result', 'usage'} or \
                            response['state'] not in {'ok', 'known_failed', 'known_refused', 'unknown', 'ready'}:
                        raise ValueError('invalid dispatcher result')
                    if response['state'] == 'ready' and argument != {'probe': True}:
                        raise ValueError('only a probe may return readiness')
                    if response['state'] == 'known_refused' and response['usage'] != {'total_tokens': 0}:
                        raise ValueError('known refusal requires proof of zero usage')
                    if response['usage'] is not None and response['state'] != 'known_refused':
                        validate_detailed_usage(response['usage'])
                    if response['state'] == 'ok' and (response['usage'] is None or
                            type(response['result']) is not str or not response['result'].strip()):
                        raise ValueError('successful dispatcher result requires usage and content')
                    if response['state'] == 'known_failed' and response['usage'] is None:
                        raise ValueError('known failure requires measured usage')
                    if response['state'] != 'ok' and response['result'] is not None:
                        raise ValueError('failed dispatcher cannot return a result')
                    continuing = self._continue_settled_failures and response['state'] == 'known_failed' \
                        and 'host_messages' in argument
                    if response['state'] not in {'ok', 'ready'} and not continuing:
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
