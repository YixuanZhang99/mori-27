"""Detached trusted supervisor and pre-exec child gate (stdlib only).

This script is launched by absolute path. It never imports candidate packages or
writes X1; the single coordinator reconciles its immutable sidecar records.
"""
from __future__ import annotations

import sys
if sys.path and sys.path[0].replace("\\", "/").endswith("/core/composition"):
    del sys.path[0]

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "executor" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IDENTITY = load_module("_worktree_identity", "process_identity.py")
POLICY = load_module("_worktree_seccomp", "seccomp.py")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic(path, value):
    path = Path(path)
    if path.exists():
        if read(path) != value:
            raise ValueError("immutable process sidecar changed")
        return
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def identity(token, spec_sha):
    ticks = IDENTITY.start_ticks(os.getpid())
    if ticks is None:
        raise RuntimeError("stable process start identity is unavailable")
    return {"pid": os.getpid(), "start_ticks": ticks, "execution_token": token, "spec_sha256": spec_sha}


def gated(directory, filename, expected, owner=None):
    path = directory / filename
    while not path.exists():
        if owner is not None and not IDENTITY.process_alive(owner["pid"], owner["start_ticks"]):
            raise RuntimeError("supervisor disappeared before target authorization")
        time.sleep(0.02)
    if read(path) != expected:
        raise ValueError("process authorization binding mismatch")


def child(directory, spec, spec_sha):
    own = identity(spec["execution_token"], spec_sha)
    owner = read(directory / "supervisor.json")
    gated(directory, "target-authorized.json", own, owner)
    policy, delivery = spec["seccomp_policy"], spec["seccomp_delivery"]
    POLICY.validate_seccomp_delivery(policy, delivery)
    args, descriptor = POLICY.materialize_seccomp(spec["args"], policy, delivery)
    if descriptor is not None:
        os.set_inheritable(descriptor, True)
    names = {"memory_bytes": resource.RLIMIT_AS, "file_bytes": resource.RLIMIT_FSIZE,
             "process_count": resource.RLIMIT_NPROC}
    for name, value in spec["resource_limits"].items():
        if name not in names or type(value) is not int or value <= 0:
            raise ValueError("invalid resource policy")
        resource.setrlimit(names[name], (value, value))
    if delivery == "direct_prctl":
        POLICY.direct_seccomp_preexec(policy)()
    os.chdir(spec["cwd"])
    os.execvpe(args[0], args, os.environ)


def supervise(directory, spec, spec_sha):
    # The OS releases this lease on supervisor death. A new supervisor is never
    # automatically launched for an existing launch intent, even after death.
    with (directory / "invocation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / "process-result.json").exists():
            return
        owner = identity(spec["execution_token"], spec_sha)
        atomic(directory / "supervisor.json", owner)
        gated(directory, "authorized.json", owner)
        request = Path(spec["request_path"]).read_bytes()
        if "sha256:" + hashlib.sha256(request).hexdigest() != spec["request_sha256"]:
            raise ValueError("evaluation request changed before launch")
        POLICY.validate_seccomp_delivery(spec["seccomp_policy"], spec["seccomp_delivery"])
        started, target, target_identity = time.monotonic(), None, None
        try:
            with (directory / "stdout.txt").open("wb") as stdout, (directory / "stderr.txt").open("wb") as stderr:
                bootstrap = "import runpy,sys; p=sys.argv[1]; sys.argv=[p]+sys.argv[2:]; runpy.run_path(p,run_name='__main__')"
                target = subprocess.Popen([sys.executable, "-I", "-c", bootstrap,
                    str(Path(__file__).resolve()), str(directory / "spec.json"), "--child"],
                    cwd=spec["cwd"], stdout=stdout, stderr=stderr, start_new_session=True)
                ticks = IDENTITY.start_ticks(target.pid)
                if ticks is None:
                    raise RuntimeError("target has no stable OS start identity")
                target_identity = {"pid": target.pid, "start_ticks": ticks,
                    "execution_token": spec["execution_token"], "spec_sha256": spec_sha}
                atomic(directory / "target.json", target_identity)
                atomic(directory / "target-authorized.json", target_identity)
                timeout = False
                try:
                    returncode = target.wait(timeout=spec["time_limit"])
                except subprocess.TimeoutExpired:
                    timeout = True
                    os.killpg(target.pid, signal.SIGKILL)
                    returncode = target.wait()
            result = {"returncode": returncode, "timeout": timeout, "wrapper_error": None}
        except BaseException as error:
            if target is not None and target.poll() is None:
                try:
                    os.killpg(target.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                target.wait()
            result = {"returncode": 127, "timeout": False,
                      "wrapper_error": type(error).__name__ + ": " + str(error)}
        response_sha = None
        response = Path(spec["response_path"])
        if response.is_file() and not response.is_symlink():
            raw = response.read_bytes()
            with (directory / "raw-response.json").open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            response_sha = "sha256:" + hashlib.sha256(raw).hexdigest()
        atomic(directory / "process-result.json", {**result, "execution_token": spec["execution_token"],
            "spec_sha256": spec_sha, "request_sha256": spec["request_sha256"],
            "response_sha256": response_sha,
            "supervisor": owner, "target": target_identity,
            "wall_seconds": max(0.0, time.monotonic() - started)})


def main():
    path = Path(sys.argv[1]).resolve()
    envelope = read(path)
    if type(envelope) is not dict or set(envelope) != {"spec", "spec_sha256"} \
            or digest(envelope["spec"]) != envelope["spec_sha256"]:
        raise ValueError("invalid durable command specification")
    if len(sys.argv) == 3 and sys.argv[2] == "--child":
        child(path.parent, envelope["spec"], envelope["spec_sha256"])
    else:
        supervise(path.parent, envelope["spec"], envelope["spec_sha256"])


if __name__ == "__main__":
    main()
