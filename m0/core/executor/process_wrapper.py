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


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _record_target_identity(target: subprocess.Popen, path: Path) -> None:
    """Publish only a stable identity; stop an owned child if publication fails."""
    try:
        ticks = _start_ticks(target.pid)
        if ticks is None:
            raise RuntimeError("target process requires a stable OS start identity")
        _atomic_json(path, {"pid": target.pid, "start_ticks": ticks})
    except BaseException:
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


def _apply_target_policy(spec: dict, seccomp_installer) -> None:
    _apply_resource_limits(spec)
    if seccomp_installer is not None:
        seccomp_installer()


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


def main() -> int:
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    result_path = Path(spec["result_path"])
    target_path = Path(spec["target_path"])
    try:
        with Path(spec["stdout_path"]).open("w+", encoding="utf-8") as stdout, \
                Path(spec["stderr_path"]).open("w+", encoding="utf-8") as stderr:
            args, seccomp_fd, seccomp_installer = _prepare_seccomp(spec)
            try:
                target = subprocess.Popen(
                    args, cwd=spec["cwd"], text=True, stdout=stdout, stderr=stderr,
                    start_new_session=True, pass_fds=() if seccomp_fd is None else (seccomp_fd,),
                    preexec_fn=lambda: _apply_target_policy(spec, seccomp_installer))
            finally:
                if seccomp_fd is not None:
                    os.close(seccomp_fd)
            _record_target_identity(target, target_path)
            timed_out = False
            try:
                returncode = target.wait(timeout=spec.get("time_limit"))
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(target.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                returncode = target.wait()
        _atomic_json(result_path, {"returncode": returncode, "timeout": timed_out})
        return 0
    except BaseException as exc:
        _atomic_json(result_path, {"returncode": 127, "timeout": False,
                                   "wrapper_error": f"{type(exc).__name__}: {exc}"})
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
