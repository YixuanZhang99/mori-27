"""Detached evaluation wrapper; writes an atomic result for owner-crash recovery."""
from __future__ import annotations

import sys
# Direct execution puts core/executor on sys.path before stdlib imports; remove
# it immediately so executor/types.py can never shadow the standard library.
if sys.path and sys.path[0].replace("\\", "/").endswith("/core/executor"):
    del sys.path[0]

import importlib.util
import json
import os
import resource
import signal
import subprocess
import threading
import time
from pathlib import Path

# Load the policy by file path.  Importing core.executor would run package
# initializers, and direct script execution must not let executor/types.py shadow
# the standard-library types module.
_POLICY_PATH = Path(__file__).resolve().with_name("seccomp.py")
_POLICY_SPEC = importlib.util.spec_from_file_location("_autoresearch_seccomp", _POLICY_PATH)
if _POLICY_SPEC is None or _POLICY_SPEC.loader is None:
    raise RuntimeError("cannot load the canonical seccomp policy")
_POLICY = importlib.util.module_from_spec(_POLICY_SPEC)
_POLICY_SPEC.loader.exec_module(_POLICY)
materialize_seccomp = _POLICY.materialize_seccomp
direct_seccomp_preexec = _POLICY.direct_seccomp_preexec
validate_seccomp_delivery = _POLICY.validate_seccomp_delivery

_IDENTITY_PATH = Path(__file__).resolve().with_name("process_identity.py")
_IDENTITY_SPEC = importlib.util.spec_from_file_location("_autoresearch_process_identity",
                                                      _IDENTITY_PATH)
if _IDENTITY_SPEC is None or _IDENTITY_SPEC.loader is None:
    raise RuntimeError("cannot load the canonical process identity reader")
_IDENTITY = importlib.util.module_from_spec(_IDENTITY_SPEC)
_IDENTITY_SPEC.loader.exec_module(_IDENTITY)
_start_ticks = _IDENTITY.start_ticks

_GATE = '''import ctypes,os,select,sys,time
fd=int(sys.argv[1]); boot=sys.argv[2]; end=int(sys.argv[3]); parent=int(sys.argv[4]); command=sys.argv[5:]
if ctypes.CDLL(None,use_errno=True).prctl(1,9,0,0,0)!=0 or os.getppid()!=parent:
    sys.exit(125)
while True:
    if open('/proc/sys/kernel/random/boot_id', encoding='ascii').read().strip()!=boot:
        sys.exit(125)
    remaining=(end-time.clock_gettime_ns(time.CLOCK_BOOTTIME))/1_000_000_000
    if remaining<=0:
        sys.exit(125)
    ready,_,_=select.select([fd],[],[],min(remaining,.1))
    if ready:
        if os.read(fd,1)!=b'G':
            sys.exit(125)
        os.close(fd)
        if open('/proc/sys/kernel/random/boot_id', encoding='ascii').read().strip()!=boot or time.clock_gettime_ns(time.CLOCK_BOOTTIME)>=end:
            sys.exit(125)
        os.execvpe(command[0],command,os.environ)
'''


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _record_target_identity(target: subprocess.Popen, path: Path, *, cleanup_on_error=True) -> None:
    """Publish only a stable identity; stop an owned child if publication fails."""
    try:
        ticks = _start_ticks(target.pid)
        if ticks is None:
            raise RuntimeError("target process requires a stable OS start identity")
        _atomic_json(path, {"pid": target.pid, "start_ticks": ticks})
    except BaseException:
        if not cleanup_on_error:
            raise
        # This is the wrapper's unreaped direct child, not a recovered numeric PID.
        # Its PID cannot be reused while poll() reports it is still running.
        if target.poll() is None:
            try:
                os.killpg(target.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        target.wait()
        raise


def _apply_resource_limits(spec: dict) -> None:
    limits = spec.get("resource_limits", {})
    names = {"memory_bytes": resource.RLIMIT_AS, "file_bytes": resource.RLIMIT_FSIZE,
             "process_count": resource.RLIMIT_NPROC}
    if not isinstance(limits, dict) or not set(limits).issubset(names):
        raise ValueError("invalid durable resource-limit payload")
    for name, value in limits.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"invalid resource limit: {name}")
        resource.setrlimit(names[name], (value, value))


def _check_absolute_deadline(spec: dict) -> bool:
    deadline = spec.get('absolute_deadline')
    if deadline is None:
        return True
    if type(deadline) is not dict or set(deadline) != {'boot_id', 'deadline_ns'} or \
            type(deadline['boot_id']) is not str or not deadline['boot_id'] or \
            type(deadline['deadline_ns']) is not int or deadline['deadline_ns'] < 0 or \
            not hasattr(time, 'CLOCK_BOOTTIME'):
        raise ValueError('invalid absolute process deadline')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    if boot != deadline['boot_id']:
        raise ValueError('absolute process deadline boot identity changed')
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME) < deadline['deadline_ns']


def _apply_target_policy(spec: dict, seccomp_installer) -> None:
    if not _check_absolute_deadline(spec):
        raise TimeoutError('absolute process deadline expired before exec')
    _apply_resource_limits(spec)
    if seccomp_installer is not None:
        seccomp_installer()
    if not _check_absolute_deadline(spec):
        raise TimeoutError('absolute process deadline expired before exec')


def _prepare_seccomp(spec: dict):
    """Validate durable policy and prepare its explicit delivery before fork."""
    payload = spec.get("seccomp_policy")
    delivery = spec.get("seccomp_delivery")
    if payload is not None and delivery is None:
        delivery = "bwrap_memfd"  # v56 durable-spec compatibility
    validate_seccomp_delivery(payload, delivery)
    args, fd = materialize_seccomp(spec["args"], payload, delivery)
    installer = direct_seccomp_preexec(payload) if delivery == "direct_prctl" else None
    return args, fd, installer


def _wait_target(target, spec):
    """Apply the absolute boot clock while also respecting a relative limit."""
    relative = spec.get('time_limit')
    if spec.get('absolute_deadline') is None:
        return target.wait(timeout=relative)
    relative_end = None if relative is None else time.monotonic() + relative
    while True:
        if not _check_absolute_deadline(spec):
            raise subprocess.TimeoutExpired(target.args, relative)
        remaining = (spec['absolute_deadline']['deadline_ns'] -
                     time.clock_gettime_ns(time.CLOCK_BOOTTIME)) / 1_000_000_000
        if relative_end is not None:
            remaining = min(remaining, relative_end - time.monotonic())
        if remaining <= 0:
            raise subprocess.TimeoutExpired(target.args, relative)
        try:
            return target.wait(timeout=min(remaining, .2))
        except subprocess.TimeoutExpired:
            continue


def _absolute_watch(target, spec, stop, outcome, ready):
    """Watch before identity I/O; leave the child unreaped until the caller joins."""
    try:
        relative = spec.get('time_limit')
        relative_end = None if relative is None else time.monotonic() + relative
        ready.set()
        while not stop.is_set():
            # WNOWAIT keeps the PID allocated, preventing reuse before killpg.
            if os.waitid(os.P_PID, target.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return
            expired = not _check_absolute_deadline(spec)
            remaining = (spec['absolute_deadline']['deadline_ns'] -
                         time.clock_gettime_ns(time.CLOCK_BOOTTIME)) / 1_000_000_000
            if relative_end is not None:
                remaining = min(remaining, relative_end - time.monotonic())
            if expired or remaining <= 0:
                outcome['timeout'] = True
                try:
                    os.killpg(target.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return
            stop.wait(min(remaining, .1))
    except BaseException as error:
        ready.set()
        outcome['error'] = error
        try:
            os.killpg(target.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    result_path = Path(spec["result_path"])
    target_path = Path(spec["target_path"])
    try:
        with Path(spec["stdout_path"]).open("w+", encoding="utf-8") as stdout, \
                Path(spec["stderr_path"]).open("w+", encoding="utf-8") as stderr:
            if not _check_absolute_deadline(spec):
                _atomic_json(result_path, {"returncode": -1, "timeout": True})
                return 0
            args, seccomp_fd, seccomp_installer = _prepare_seccomp(spec)
            gate_read = gate_write = None
            if spec.get('absolute_deadline') is not None:
                gate_read, gate_write = os.pipe()
                deadline = spec['absolute_deadline']
                args = [sys.executable, '-I', '-S', '-c', _GATE, str(gate_read),
                        deadline['boot_id'], str(deadline['deadline_ns']), str(os.getpid()), *args]
            try:
                target = subprocess.Popen(
                    args, cwd=spec["cwd"], text=True, stdout=stdout, stderr=stderr,
                    start_new_session=True, pass_fds=tuple(fd for fd in (seccomp_fd, gate_read) if fd is not None),
                    preexec_fn=lambda: _apply_target_policy(spec, seccomp_installer))
            except BaseException:
                if gate_write is not None:
                    os.close(gate_write)
                raise
            finally:
                if seccomp_fd is not None:
                    os.close(seccomp_fd)
                if gate_read is not None:
                    os.close(gate_read)
            stop = threading.Event()
            ready = threading.Event()
            outcome = {'timeout': False, 'error': None}
            watcher = None
            if spec.get('absolute_deadline') is not None:
                watcher = threading.Thread(target=_absolute_watch, args=(target, spec, stop, outcome, ready))
                try:
                    watcher.start()
                    ready.wait()
                except BaseException:
                    os.close(gate_write)
                    try:
                        os.killpg(target.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    target.wait()
                    raise
            try:
                _record_target_identity(target, target_path, cleanup_on_error=watcher is None)
                if gate_write is not None:
                    try:
                        if _check_absolute_deadline(spec):
                            os.write(gate_write, b'G')
                    except BrokenPipeError:
                        pass
                    finally:
                        os.close(gate_write)
            except BaseException:
                if gate_write is not None:
                    try:
                        os.close(gate_write)
                    except OSError:
                        pass
                if watcher is not None:
                    stop.set()
                    watcher.join()
                    try:
                        os.killpg(target.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    target.wait()
                raise
            timed_out = False
            try:
                if watcher is None:
                    returncode = _wait_target(target, spec)
                else:
                    watcher.join()
                    if outcome['error'] is not None:
                        raise outcome['error']
                    returncode = target.wait()
                    timed_out = outcome['timeout']
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(target.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                returncode = target.wait()
            except BaseException:
                try:
                    os.killpg(target.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                target.wait()
                raise
        _atomic_json(result_path, {"returncode": returncode, "timeout": timed_out})
        return 0
    except BaseException as exc:
        _atomic_json(result_path, {"returncode": 127, "timeout": False,
                                   "wrapper_error": f"{type(exc).__name__}: {exc}"})
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
